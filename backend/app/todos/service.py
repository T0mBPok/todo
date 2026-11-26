from uuid import UUID
from datetime import datetime
from zoneinfo import ZoneInfo
import re
from fastapi import HTTPException
from sqlalchemy import select
from app.todos.dao import TodoDAO
from app.todos.schemas import TodoInput,TodoRead
from app.todos.ai import interpret
from app.todos.scheduling import grounded_schedule, task_fragment, clean_scheduled_title, DATE_TOKEN
from app.todos.deadlines import deadline_parts
from pydantic import ValidationError
from app.commands.models import Command
from app.tasks.service import calendar_lock
class TodoService:
    def __init__(self,session):self.session=session;self.dao=TodoDAO(session)
    def require(self,id):
        task=self.dao.get(id)
        if not task:raise HTTPException(404,'Задача не найдена.')
        return task
    def create(self,data):
        task=self.dao.add(data);self.session.commit();return task
    def update(self,id,data):
        calendar_lock(self.session);task=self.require(id)
        merged=TodoRead.model_validate(task).model_dump(exclude={'id','created_at'})
        merged.update(data.model_dump(exclude_unset=True))
        try: validated=TodoInput.model_validate(merged)
        except ValidationError as error: raise HTTPException(422,'Проверьте дату и время задачи.') from error
        for k,v in validated.model_dump().items():setattr(task,k,v)
        self.session.commit();return task
    def complete(self,id,completed):
        calendar_lock(self.session)
        task=self.require(id)
        task.completed=completed
        self.session.commit()
        return task
    def delete(self,id):
        calendar_lock(self.session);self.session.delete(self.require(id));self.session.commit()
    def prepare(self,data):
        tasks=self.dao.list()
        if len(tasks)>150:raise HTTPException(422,'Список слишком большой для локальной модели. Архивируйте ненужные задачи.')
        mapping={f'T{i+1}':task for i,task in enumerate(tasks)}
        context=[{'ref':ref,**TodoRead.model_validate(task).model_dump(mode='json')} for ref,task in mapping.items()]
        if sum(len(t['description'])+len(t['title']) for t in context)>22000:raise HTTPException(422,'Слишком много подробностей для одного запроса к локальной модели.')
        result=interpret(data.text,context,[item.model_dump() for item in data.history],data.timezone)
        if result.clarification:raise HTTPException(422,result.clarification)
        if not result.actions:raise HTTPException(422,result.note or 'Назовите задачу, которую нужно сделать.')
        operations=[];seen=set(); schedule_review=False
        schedule_actions=[a for a in result.actions if a.action in {'create','update'}]
        for action in result.actions:
            snapshot=None
            schedule=None
            deadline=None
            if action.action in {'create','update'}:
                fragment=action.schedule_text or ''
                literal=' '.join(fragment.lower().split()) in ' '.join(data.text.lower().split())
                source=(data.text if len(schedule_actions)==1 else task_fragment(data.text,action.title or '')) or (fragment if literal else '')
                source,deadline,deadline_uncertain=deadline_parts(action,source,data.timezone)
                schedule_review=schedule_review or deadline_uncertain
                if deadline is not None and not DATE_TOKEN.search(source):
                    action=action.model_copy(update={'scheduled_date':None,'scheduled_at':None,'schedule_text':None})
                    action._invalid_schedule=False
                if action.action=='create' or action.scheduled_date or action.scheduled_at or action.clear_schedule or action.clear_time or action.schedule_text:
                    schedule, uncertain=grounded_schedule(action,source,data.timezone)
                    schedule_review=schedule_review or uncertain
            if action.action=='create':
                if action.title:action.title=clean_scheduled_title(action.title,schedule)
                if not action.title:raise HTTPException(502,'Модель не указала название задачи.')
                if not action.title.strip():raise HTTPException(502,'Модель вернула пустое название задачи.')
                TodoInput(title=action.title,description=action.description or '',**{**(schedule or {}),**(deadline or {})})
            else:
                if action.ref not in mapping:raise HTTPException(502,'Модель выбрала задачу вне списка. Ничего не изменено.')
                if action.ref in seen:raise HTTPException(422,'Несколько изменений одной задачи: уточните итоговый результат.')
                seen.add(action.ref);snapshot=TodoRead.model_validate(mapping[action.ref]).model_dump(mode='json')
                if action.action=='update' and action.title is None and action.description is None and action.category is None and schedule is None and deadline is None:raise HTTPException(422,'Уточните, что изменить в задаче.')
            if action.action=='update' and schedule is not None and not action.clear_schedule:
                if action.clear_time:
                    schedule['scheduled_at']=None
                    schedule['scheduled_date']=schedule['scheduled_date'] or snapshot.get('scheduled_date')
                elif schedule['scheduled_at'] is None and schedule['scheduled_date'] and snapshot.get('scheduled_at'):
                    previous=datetime.fromisoformat(snapshot['scheduled_at']).astimezone(ZoneInfo(data.timezone))
                    day=schedule['scheduled_date']
                    schedule['scheduled_at']=previous.replace(year=day.year,month=day.month,day=day.day)
            operations.append({'entity':'todo','action':action.model_dump(mode='json'),'snapshot':snapshot,'deadline':TodoInput(title=action.title or (snapshot or {}).get('title','Задача'), **deadline).model_dump(mode='json', include={'deadline_date','deadline_at','timezone'}) if deadline is not None else None,'schedule':TodoInput(title=action.title or (snapshot or {}).get('title','Задача'), **schedule).model_dump(mode='json', include={'scheduled_date','scheduled_at','timezone'}) if schedule is not None else None})
        note=re.sub(r'\bT\d+\b',lambda match:'«'+mapping[match.group()].title+'»' if match.group() in mapping else '',result.note)
        command=Command(text=data.text,status='draft',operations=operations,note=note)
        self.session.add(command);self.session.commit()
        return {'id':command.id,'note':note,'operations':operations,'requires_confirmation':schedule_review or any(a.action=='delete' for a in result.actions)}
    def execute(self,id):
        calendar_lock(self.session)
        command=self.session.scalar(select(Command).where(Command.id==id).with_for_update())
        if not command or any(op.get('entity')!='todo' for op in command.operations):raise HTTPException(404,'Команда задач не найдена.')
        if command.status=='executed':return command.result
        changed=[]
        try:
            for op in command.operations:
                action=op['action'];snapshot=op['snapshot']
                if action['action']=='create':task=self.dao.add(TodoInput(title=action['title'],description=action['description'] or '',category=action.get('category') or 'important_not_urgent',**{**(op.get('schedule') or {}),**(op.get('deadline') or {})}))
                else:
                    task=self.require(UUID(snapshot['id']))
                    if TodoRead.model_validate(task).model_dump(mode='json')!=snapshot:raise HTTPException(409,'Задача уже изменилась. Повторите команду.')
                    if action['action']=='delete':self.session.delete(task);continue
                    if action['action']=='complete':task.completed=True
                    if action['action']=='reopen':task.completed=False
                    if action['action']=='update':
                        if action['title'] is not None:task.title=TodoInput(title=action['title']).title
                        if action['description'] is not None:task.description=action['description']
                        if action.get('category') is not None:task.category=action['category']
                        if op.get('schedule') is not None:
                            values=TodoInput(title=task.title,**op['schedule'])
                            task.scheduled_date=values.scheduled_date;task.scheduled_at=values.scheduled_at;task.timezone=values.timezone
                        if op.get('deadline') is not None:
                            values=TodoInput(title=task.title,**op['deadline'])
                            task.deadline_date=values.deadline_date;task.deadline_at=values.deadline_at
                changed.append(TodoRead.model_validate(task).model_dump(mode='json'))
            result={'note':'Готово. Список задач обновлён.','tasks':changed}
            command.status='executed';command.result=result;self.session.commit();return result
        except Exception:self.session.rollback();raise
