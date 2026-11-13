from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from uuid import UUID,uuid4
import re
from sqlalchemy import select
from fastapi import HTTPException
from app.commands.models import Command
from app.commands.dao import CommandDAO
from app.commands.calendar_clear import ENTITY as CALENDAR_CLEAR, is_calendar_clear, prepare_clear
from app.commands.ai import interpret
from app.commands.matching import deletion_request, exact_title, explicit_calendar_add, score_name, timed_creation, timed_deletion, tokens
from app.commands.recurrence import existing_recurrence
from app.tasks.models import Task
from app.tasks.schemas import TaskRead,TaskInput
from app.tasks.service import TaskService,calendar_lock
from app.plans.dates import resolve_anchor
def words(value):
    return [w[:5] for w in re.findall(r"[а-яёa-z0-9]+",value.lower()) if len(w)>1 and w not in {"задача","событие","это","эту","эта","по","на","в"}]
from app.plans.schemas import PlanOutput, PlanRead, PlanRequest
from app.core import config
from app.plans.ai import AIPlanner
from app.plans.service import PlanService
from app.recurrences.service import instances
def anchor(value,today):
    if not value: return None
    try: result=resolve_anchor(value,today)
    except ValueError: result=None
    if result is None: raise HTTPException(422,'Не понял дату. Назовите день недели или точную дату.')
    return result
def clock(value):
    if value and 'T' in value:
        try:
            parsed = datetime.fromisoformat(value)
            return parsed.hour, parsed.minute
        except ValueError:
            pass
    if not re.fullmatch(r'\d{1,2}:\d{2}',value or ''): raise HTTPException(422,'Не понял время. Укажите часы и минуты.')
    h,m=map(int,value.split(':'))
    if h>23 or m>59: raise HTTPException(422,'Некорректное время.')
    return h,m
class CommandService:
    def __init__(self,session):
        self.session=session;self.tasks=TaskService(session);self.dao=CommandDAO(session)
    def prepare(self,request):
        if is_calendar_clear(request.text):
            return prepare_clear(self.session, request.text)
        from app.commands.context import calendar_context
        from app.commands.grounded_ai import Decision, SelectedOperation, interpret_calendar
        from app.commands.schemas import Operation
        from app.plans.colloquial_time import resolve_colloquial_ranges
        from app.plans.dates import ANCHOR

        zone = ZoneInfo(request.timezone)
        today = datetime.now(zone).date()
        explicit_days = {anchor(match.group(), today) for match in ANCHOR.finditer(request.text)}
        from app.plans.prompts import normalize_transcript
        time_reviews = []
        normalized_command = normalize_transcript(
            resolve_colloquial_ranges(request.text, request.timezone, reviews=time_reviews)
        )
        exact_create = None if time_reviews else timed_creation(normalized_command)
        if exact_create:
            day_word, title, first, last = exact_create
            day = anchor(day_word, today)
            start_hour, start_minute = clock(first)
            start = datetime(day.year, day.month, day.day, start_hour, start_minute, tzinfo=zone)
            end = start + timedelta(hours=1)
            if last is not None:
                end_hour, end_minute = clock(last)
                end = start.replace(hour=end_hour, minute=end_minute)
                if end == start:
                    raise HTTPException(422, 'Начало и конец совпадают. Уточните время окончания.')
                if end < start:
                    end += timedelta(days=1)
            task = TaskInput(title=title, start=start, end=end)
            normalized = normalized_command
            draft = PlanService(self.session).save_draft(
                request, PlanOutput(tasks=[task], note=f'Понял: {title}, {start:%d.%m %H:%M}–{end:%d.%m %H:%M}.',
                                    normalized_text=normalized))
            plan = PlanRead.model_validate(draft)
            plan.normalized_text = normalized
            return {'kind': 'plan', 'plan': plan}
        exact_delete = timed_deletion(request.text)
        if exact_delete:
            day_word, title, start_time = exact_delete
            day = anchor(day_word, today)
            start = datetime.combine(day, datetime.min.time(), zone)
            matches = [event for event in self.tasks.list(start, start + timedelta(days=1))
                       if exact_title(title, event.title)
                       and event.start.astimezone(zone).date() == day
                       and event.start.astimezone(zone).strftime('%H:%M') == start_time]
            if not matches:
                raise HTTPException(422, f'Не нашёл «{title}» на {day:%d.%m} в {start_time}. Проверьте название и время.')
            mapping = {f'E{i}': event for i, event in enumerate(matches, 1)}
            decision = Decision(intent='manage', note=f'Удалить событие на {day:%d.%m} в {start_time}.',
                                operations=[SelectedOperation(action='delete', refs=list(mapping), scope='occurrence')])
        else:
            if config.AI_PROVIDER == 'gigachat':
                normalized_command, _ = AIPlanner().normalize(normalized_command)
            if len(request.text) > 750 and explicit_calendar_add(request.text):
                decision = Decision(intent='create', note='')
            else:
                context, mapping = calendar_context(request, self.tasks)
                model_request = request.model_copy(update={'text': normalized_command})
                decision = interpret_calendar(model_request, context)
        if decision.intent=='clarify':raise HTTPException(422,decision.note)
        if decision.intent=='create':
            plan_request = PlanRequest(text=decision.create_text or normalized_command, timezone=request.timezone)
            plan_request._spoken_text = request.text
            if config.AI_PROVIDER == 'gigachat':
                plan_request._normalized_text = normalized_command
            plan = PlanService(self.session).create(plan_request)
            value=PlanRead.model_validate(plan)
            marker=' Нормализованный текст: '
            value.normalized_text=plan.note.split(marker,1)[1].split(' Без указанной длительности',1)[0] if marker in plan.note else request.text
            return {'kind':'plan','plan':value}
        if time_reviews:
            raise HTTPException(422, time_reviews[0].message)
        if 'кроме' in request.text.lower() and any(action.action=='delete' for action in decision.operations) and not decision.keep_refs:
            raise HTTPException(422,'Модель не определила, какие события сохранить. Календарь не изменён; уточните исключение.')
        append = re.fullmatch(r'\s*добавь\s+в\s+описание\s+([^:;.!?]+):\s*(.+)', request.text, re.I | re.S)
        operations=[];seen=set()
        for action in decision.operations:
            chosen=list(dict.fromkeys(action.refs))
            if action.scope=='series':
                roots=set();unique=[]
                for ref in chosen:
                    if ref not in mapping:raise HTTPException(502,'Выбрано неизвестное событие.')
                    root=mapping[ref].series_parent_id or mapping[ref].id
                    if root not in roots:unique.append(ref);roots.add(root)
                chosen=unique
            if not chosen or any(ref not in mapping for ref in chosen):raise HTTPException(502,'Выбрано неизвестное событие. Календарь не изменён.')
            if set(chosen)&set(decision.keep_refs):raise HTTPException(502,'Исключённое событие попало в действие.')
            groups=[[ref] for ref in chosen] if action.selection=='all' else [chosen]
            for refs in groups:
                candidates=[mapping[ref] for ref in refs]
                for candidate in candidates:
                    if action.action=='delete' and len(explicit_days)==1 and candidate.start.astimezone(ZoneInfo(request.timezone)).date() not in explicit_days:
                        raise HTTPException(422,'Выбранное моделью событие находится в другом дне. Уточните дату; календарь не изменён.')
                    key=(str(candidate.id),candidate.start.isoformat())
                    if key in seen:raise HTTPException(422,'Одно событие выбрано дважды. Разделите действия.')
                    seen.add(key)
                changes=action.model_dump(exclude={'action','refs','selection'})
                if (append and action.action == 'update' and len(decision.operations) == 1
                        and not decision.new_events and action.selection == 'one'
                        and all(exact_title(append[1], candidate.title) for candidate in candidates)):
                    changes['description'] = append[2].strip()[:5000]
                    changes['append_description'] = True
                if action.action=='update' and not any(changes.get(k) is not None for k in ('new_title','description','new_time','new_date_reference','duration_minutes','new_recurrence')):
                    raise HTTPException(422,'Не определено, что изменить в выбранной задаче.')
                recurring = any(candidate.recurrence or candidate.series_parent_id for candidate in candidates)
                if recurring:
                    changes['scope'] = 'unspecified'
                instruction=Operation(operation=action.action,target=candidates[0].title,**changes)
                operations.append({'instruction':instruction.model_dump(),'timezone':request.timezone,'candidates':[task.model_dump(mode='json') for task in candidates],
                    'requires_confirmation':recurring or action.selection=='all' or bool(decision.keep_refs)})
        if decision.new_events:
            from app.plans.dates import enforce_date_context
            additions=enforce_date_context(decision.new_events,request.text,request.timezone)
            for event in additions:
                if not re.search(r'\b(?:час\w*|минут\w*|полчаса|полтора|полторы|до)\b',request.text,re.I):event.end=event.start+timedelta(hours=1)
                snapshot=TaskRead(id=uuid4(),**event.model_dump())
                instruction=Operation(operation='create',target=event.title,scope='occurrence')
                operations.append({'instruction':instruction.model_dump(),'timezone':request.timezone,'candidates':[snapshot.model_dump(mode='json')],'requires_confirmation':True})
            # A mixed replacement must be reviewed as one indivisible change.
            for item in operations:item['requires_confirmation']=True
        if not operations or len(operations)>30:raise HTTPException(422,'Уточните количество изменяемых событий.')
        if sum(item['instruction']['operation']=='delete' for item in operations)>1:
            for item in operations:item['requires_confirmation']=True
        kept=[mapping[ref].title for ref in decision.keep_refs]
        note=re.sub(r'\(?\bE\d+\b\)?','',decision.note)+(' Сохранить: '+', '.join(dict.fromkeys(kept))+'.' if kept else '')
        if decision.new_events:
            removed=[item['instruction']['target'] for item in operations if item['instruction']['operation']=='delete']
            additions=[item['candidates'][0] for item in operations if item['instruction']['operation']=='create']
            note='План замены. '+('Удалить: '+', '.join(removed)+'. ' if removed else '')+'Добавить: '+ '; '.join(value['title']+' '+datetime.fromisoformat(value['start']).astimezone(ZoneInfo(request.timezone)).strftime('%d.%m %H:%M') for value in additions)+'. Подтвердите все действия вместе.'
        command=Command(text=request.text,operations=operations,note=note)
        self.session.add(command);self.session.commit()
        return {'kind':'command','id':command.id,'operations':operations,'note':note}
    def prepare_legacy(self,request):
        all_tasks=self.tasks.dao.list()
        parsed=deletion_request(request) or existing_recurrence(request,all_tasks) or interpret(request,list(dict.fromkeys(t.title for t in all_tasks))[:200])
        if parsed.intent=='create':
            plan=PlanService(self.session).create(PlanRequest(text=request.text,timezone=request.timezone))
            value=PlanRead.model_validate(plan)
            marker=' Нормализованный текст: '
            value.normalized_text=plan.note.split(marker,1)[1].split(' Без указанной длительности',1)[0] if marker in plan.note else request.text
            return {'kind':'plan','plan':value}
        if not parsed.operations: raise HTTPException(422,'Назовите задачу и что нужно изменить.')
        zone=ZoneInfo(request.timezone);now=datetime.now(zone);today=now.date()
        exceptions=self.tasks.recurrences.exceptions();operations=[]
        for op in parsed.operations:
            # A model may resolve a name, but cannot invent an unrelated deletion target.
            if op.operation=='delete' and op.target and not op.all_matches:
                spoken=tokens(request.text)
                if not any(score_name(token,word) for token in tokens(op.target) for word in spoken):
                    raise HTTPException(422,'Не удалось связать удаление с названной задачей. Уточните её название и день; календарь не изменён.')
            target=set(words(op.target));matches=[];scores={};protected=[]
            date=anchor(op.date_reference,today)
            if op.all_matches and date is None:
                raise HTTPException(422,'Для удаления нескольких задач назовите день. Например: «в субботу всё, кроме пары в университете».')
            if op.all_matches and op.operation!='delete': raise HTTPException(422,'Групповая команда поддерживает удаление за указанный день.')
            for task in all_tasks:
                score=score_name(op.target,task.title) if target else 1.0
                if not score: continue
                if not target and not op.all_matches and task.id!=request.context_task_id: continue
                date=anchor(op.date_reference,today)
                start=datetime.combine(date,datetime.min.time(),zone) if date else now
                end=start+timedelta(days=1 if date else 366)
                if task.recurrence:
                    pairs=list(instances(task,start,end,exceptions.get(task.id,set())))
                    if not date: pairs=pairs[:1]
                else: pairs=[(task.start,task.end)]
                for begin,finish in pairs:
                    local=begin.astimezone(zone)
                    if date and local.date()!=date: continue
                    if op.time_reference and (local.hour,local.minute)!=clock(op.time_reference): continue
                    value=TaskRead.model_validate(task);value.start=begin;value.end=finish
                    if task.recurrence: value.occurrence_start=begin
                    if op.exclude_target and score_name(op.exclude_target,task.title):
                        protected.append(value);continue
                    scores[value.id]=score
                    matches.append(value)
            if op.exclude_target and not protected:
                raise HTTPException(422,f'Не нашёл исключение «{op.exclude_target}» в выбранный день. Ничего не удалено. Уточните название или дату.')
            if target and matches and not op.all_matches:
                best=max(scores.values())
                matches=[t for t in matches if scores[t.id]>=best-0.03]
            matches.sort(key=lambda t:t.start)
            if op.nearest: matches=[t for t in matches if t.start>=now][:1]
            if not matches: raise HTTPException(422,f'Не нашёл задачу «{op.target or "эта задача"}». Назовите её название и день.')
            if len(matches)>30: raise HTTPException(422,'Слишком много совпадений. Уточните день и время.')
            if op.all_matches:
                for task in matches:
                    instruction=op.model_copy(update={'target':task.title,'scope':'occurrence'})
                    operations.append({'instruction':instruction.model_dump(),'timezone':request.timezone,'candidates':[task.model_dump(mode='json')]})
            else:
                operations.append({'instruction':op.model_dump(),'timezone':request.timezone,'candidates':[t.model_dump(mode='json') for t in matches]})
        if len(operations)>30: raise HTTPException(422,'Слишком много событий. Уточните команду.')
        confirmation=any(op.all_matches for op in parsed.operations) or any(any(0<score_name(op.target,t['title'])<1 for t in item['candidates']) for op,item in zip(parsed.operations,operations))
        if confirmation:
            for item in operations:item['requires_confirmation']=True
        note='Проверьте найденные задачи и выберите область изменения.'
        if any(op.exclude_target for op in parsed.operations):
            note='Удалить остальные события только указанного дня. Сохранить: '+', '.join(op.exclude_target for op in parsed.operations if op.exclude_target)+'. Повторения в другие дни сохранятся.'
        command=Command(text=request.text,operations=operations,note=note)
        self.session.add(command);self.session.commit()
        return {'kind':'command','id':command.id,'operations':operations,'note':command.note}
    def execute(self,command_id,data):
        calendar_lock(self.session)
        command=self.dao.locked(command_id)
        if not command: raise HTTPException(404,'Команда не найдена.')
        if any(op.get('entity') == CALENDAR_CLEAR for op in command.operations):
            raise HTTPException(422, 'Для очистки календаря требуется отдельное подтверждение.')
        if any(op.get('entity') in {'todo','balance'} for op in command.operations):raise HTTPException(404,'Используйте соответствующий раздел для этой команды.')
        if command.status=='executed': return command.result
        if len(data.choices)!=len(command.operations): raise HTTPException(422,'Выберите задачу для каждого действия.')
        results=[];deleted_series=set()
        try:
            # Delete before insert/update so replacement can reuse the released interval.
            ordered=sorted(zip(command.operations,data.choices),key=lambda pair: {'delete':0,'update':1,'create':2}[pair[0]['instruction']['operation']])
            for operation,choice in ordered:
                if choice.candidate>=len(operation['candidates']): raise HTTPException(422,'Неверный вариант.')
                snapshot=TaskRead.model_validate(operation['candidates'][choice.candidate]);op=operation['instruction']
                if op['operation']=='create':
                    creation=TaskInput(**{key:getattr(snapshot,key) for key in TaskInput.model_fields})
                    self.tasks.validate([creation])
                    created=self.tasks.dao.add(creation);self.session.flush()
                    results.append(TaskRead.model_validate(created).model_dump(mode='json'))
                    continue
                requested_scope=choice.scope
                root_id=snapshot.series_parent_id or snapshot.id
                if op['operation']=='delete' and requested_scope=='series' and root_id in deleted_series:continue
                task=self.tasks.require(snapshot.id)
                if task.category!=snapshot.category or task.title!=snapshot.title or task.description!=snapshot.description or task.recurrence!=(snapshot.recurrence.model_dump(exclude_none=True) if snapshot.recurrence else None):
                    raise HTTPException(409,'Задача уже изменилась. Повторите команду.')
                if not task.recurrence and (task.start!=snapshot.start or task.end!=snapshot.end): raise HTTPException(409,'Время задачи уже изменилось. Повторите команду.')
                if task.recurrence:
                    valid=list(instances(task,snapshot.start,snapshot.start+timedelta(seconds=1),self.tasks.recurrences.exceptions().get(task.id,set())))
                    if not valid or valid[0]!=(snapshot.start,snapshot.end): raise HTTPException(409,'Это повторение уже изменилось. Повторите команду.')
                recurring=bool(task.recurrence or task.series_parent_id)
                scope=choice.scope or (op['scope'] if op['scope']!='unspecified' else None)
                if recurring and choice.scope is None: raise HTTPException(422,'Выберите одно событие или всю серию.')
                if op['operation']=='delete':
                    self.tasks.delete(task.id,scope,snapshot.occurrence_start,commit_changes=False)
                    if scope=='series':deleted_series.add(root_id)
                else:
                    zone=ZoneInfo(operation['timezone']);start=snapshot.start.astimezone(zone);duration=snapshot.end-snapshot.start
                    if op['new_date_reference']:
                        date=anchor(op['new_date_reference'],datetime.now(zone).date());start=start.replace(year=date.year,month=date.month,day=date.day)
                    if op['new_time']:
                        h,m=clock(op['new_time']);start=start.replace(hour=h,minute=m)
                    if op['duration_minutes']: duration=timedelta(minutes=op['duration_minutes'])
                    description=task.description
                    if op['description'] is not None:
                        description=(description+'\n'+op['description']).strip() if op['append_description'] else op['description']
                    recurrence = task.recurrence
                    if recurrence and recurrence.get('frequency') == 'google':
                        recurrence = None
                    if op.get('new_recurrence'):
                        recurrence = {'frequency': op['new_recurrence'], 'timezone': operation['timezone']}
                    changes=TaskInput(category=op.get('new_category') or task.category,title=op['new_title'] or task.title,description=description,start=start,end=start+duration,recurrence=recurrence)
                    updated=self.tasks.update(task.id,changes,scope,snapshot.occurrence_start,commit_changes=False)
                    results.append(TaskRead.model_validate(updated).model_dump(mode='json'))
            result={'kind':'executed','note':'Готово. Календарь обновлён.','tasks':results}
            command.status='executed';command.result=result;self.session.commit();return result
        except Exception:
            self.session.rollback();raise
