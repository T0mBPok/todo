from uuid import UUID
import re
from fastapi import HTTPException
from sqlalchemy import select
from app.todos.dao import TodoDAO
from app.todos.schemas import TodoInput,TodoRead
from app.todos.ai import interpret
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
        for k,v in data.model_dump().items():setattr(task,k,v)
        self.session.commit();return task
    def delete(self,id):
        calendar_lock(self.session);self.session.delete(self.require(id));self.session.commit()
    def prepare(self,data):
        tasks=self.dao.list()
        if len(tasks)>150:raise HTTPException(422,'Список слишком большой для локальной модели. Архивируйте ненужные задачи.')
        mapping={f'T{i+1}':task for i,task in enumerate(tasks)}
        context=[{'ref':ref,**TodoRead.model_validate(task).model_dump(mode='json')} for ref,task in mapping.items()]
        if sum(len(t['description'])+len(t['title']) for t in context)>22000:raise HTTPException(422,'Слишком много подробностей для одного запроса к локальной модели.')
        result=interpret(data.text,context,[item.model_dump() for item in data.history])
        if result.clarification:raise HTTPException(422,result.clarification)
        if not result.actions:raise HTTPException(422,result.note or 'Назовите задачу, которую нужно сделать.')
        operations=[];seen=set()
        for action in result.actions:
            snapshot=None
            if action.action=='create':
                if not action.title:raise HTTPException(502,'Модель не указала название задачи.')
                if not action.title.strip():raise HTTPException(502,'Модель вернула пустое название задачи.')
                TodoInput(title=action.title,description=action.description or '')
            else:
                if action.ref not in mapping:raise HTTPException(502,'Модель выбрала задачу вне списка. Ничего не изменено.')
                if action.ref in seen:raise HTTPException(422,'Несколько изменений одной задачи: уточните итоговый результат.')
                seen.add(action.ref);snapshot=TodoRead.model_validate(mapping[action.ref]).model_dump(mode='json')
                if action.action=='update' and action.title is None and action.description is None:raise HTTPException(422,'Уточните, что изменить в задаче.')
            operations.append({'entity':'todo','action':action.model_dump(),'snapshot':snapshot})
        note=re.sub(r'\bT\d+\b',lambda match:'«'+mapping[match.group()].title+'»' if match.group() in mapping else '',result.note)
        command=Command(text=data.text,status='draft',operations=operations,note=note)
        self.session.add(command);self.session.commit()
        return {'id':command.id,'note':note,'operations':operations,'requires_confirmation':any(a.action=='delete' for a in result.actions)}
    def execute(self,id):
        calendar_lock(self.session)
        command=self.session.scalar(select(Command).where(Command.id==id).with_for_update())
        if not command or any(op.get('entity')!='todo' for op in command.operations):raise HTTPException(404,'Команда задач не найдена.')
        if command.status=='executed':return command.result
        changed=[]
        try:
            for op in command.operations:
                action=op['action'];snapshot=op['snapshot']
                if action['action']=='create':task=self.dao.add(TodoInput(title=action['title'],description=action['description'] or ''))
                else:
                    task=self.require(UUID(snapshot['id']))
                    if TodoRead.model_validate(task).model_dump(mode='json')!=snapshot:raise HTTPException(409,'Задача уже изменилась. Повторите команду.')
                    if action['action']=='delete':self.session.delete(task);continue
                    if action['action']=='complete':task.completed=True
                    if action['action']=='reopen':task.completed=False
                    if action['action']=='update':
                        if action['title'] is not None:task.title=TodoInput(title=action['title']).title
                        if action['description'] is not None:task.description=action['description']
                changed.append(TodoRead.model_validate(task).model_dump(mode='json'))
            result={'note':'Готово. Список задач обновлён.','tasks':changed}
            command.status='executed';command.result=result;self.session.commit();return result
        except Exception:self.session.rollback();raise
