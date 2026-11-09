from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from app.tasks.schemas import TaskInput
from sqlalchemy import select
from app.tasks.models import Task
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from app.tasks.dao import TaskDAO
from app.tasks.schemas import TaskRead
from app.recurrences.dao import RecurrenceDAO
from app.recurrences.service import instances, validate_conflicts, require_occurrence, shift_occurrence, wall_offset

def calendar_lock(session):
    # Serialize all calendar writes so virtual repetitions cannot race inserts.
    owner = session.info.get('owner_id')
    session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': (owner.int & ((1 << 63) - 1)) if owner else 83910241})

def commit(session):
    try: session.commit()
    except IntegrityError as error:
        session.rollback()
        if getattr(error.orig,'sqlstate',None)=='23P01':
            raise HTTPException(409,'Задачи пересекаются по времени. Измените время.') from error
        raise

class TaskService:
    def __init__(self,session):
        self.session=session
        self.dao=TaskDAO(session)
        self.recurrences=RecurrenceDAO(session)

    def list(self,start=None,end=None):
        if (start is None)!=(end is None):
            raise HTTPException(422,'Укажите обе границы диапазона.')
        bounded=start is not None
        if not bounded:
            start=datetime.now(timezone.utc)-timedelta(days=30)
            end=start+timedelta(days=120)
        if start>=end or end-start>timedelta(days=367):
            raise HTTPException(422,'Диапазон должен быть от 1 секунды до одного года.')
        exceptions=self.recurrences.exceptions()
        result=[]
        for task in self.dao.list():
            if not bounded and not task.recurrence:
                result.append(TaskRead.model_validate(task)); continue
            for occurrence,finish in instances(task,start,end,exceptions.get(task.id,set())):
                value=TaskRead.model_validate(task)
                value.start=occurrence; value.end=finish
                if task.recurrence:
                    value.occurrence_start=occurrence
                    value.occurrence_id=f'{task.id}:{occurrence.isoformat()}'
                result.append(value)
        return sorted(result,key=lambda task:task.start)

    def require(self,task_id):
        task=self.dao.get(task_id)
        if task is None: raise HTTPException(404,'Задача не найдена')
        return task

    def validate(self,data,ignore=None):
        existing=[task for task in self.dao.list() if task.id!=ignore and not task.is_all_day]
        validate_conflicts(data,existing,self.recurrences.exceptions())

    def create(self,data):
        calendar_lock(self.session)
        self.validate([data])
        task=self.dao.add(data)
        commit(self.session)
        return task

    def validate_edit(self, task, data, start, end, ignore=None):
        if task.is_all_day:
            return
        if (data.start, data.end) != (start, end) or data.recurrence:
            self.validate([data], ignore=ignore)

    def update_google_series(self, root, task, data, occurrence_start):
        if task.series_parent_id:
            selected, finish = task.start, task.end
        else:
            selected = occurrence_start or root.start
            finish = require_occurrence(root, selected)
        zone = ZoneInfo(root.recurrence['timezone'])
        offset = wall_offset(selected, data.start, zone)
        duration = root.end - root.start
        if data.end - data.start != finish - selected:
            duration = data.end - data.start
        start = shift_occurrence(root.start, offset, zone)
        end = start + duration
        rule = dict(root.recurrence)
        if offset:
            if not rule.get('source_start'):
                rule['source_start'] = root.start.isoformat()
            excluded = self.recurrences.exceptions().get(root.id, set())
            self.recurrences.clear(root.id)
            for previous in excluded:
                self.recurrences.exclude(root.id, shift_occurrence(previous, offset, zone))
        if not root.is_all_day and (start, end) != (root.start, root.end):
            candidate = Task(id=root.id, title=data.title, start=start, end=end, recurrence=rule, is_all_day=False)
            self.validate([candidate], ignore=root.id)

        fields = data.model_dump(include={'title', 'description', 'category', 'is_fixed'})
        children = self.session.scalars(select(Task).where(Task.series_parent_id == root.id))
        for child in children:
            for field, value in fields.items():
                if getattr(child, field) == getattr(root, field):
                    setattr(child, field, value)
            if offset and child.series_original_start:
                child.series_original_start = shift_occurrence(child.series_original_start, offset, zone)
        for field, value in fields.items():
            setattr(root, field, value)
        root.start, root.end, root.recurrence = start, end, rule
        return root

    def update(self,task_id,data,scope=None,occurrence_start=None,commit_changes=True):
        calendar_lock(self.session)
        task=self.require(task_id)
        if task.is_all_day and (data.start.time() != datetime.min.time() or data.end.time() != datetime.min.time()):
            raise HTTPException(422, 'Укажите даты начала и окончания события на весь день.')
        if 'is_fixed' not in data.model_fields_set:
            data.is_fixed=task.is_fixed
        if 'category' not in data.model_fields_set:
            data.category=task.category
        try:
            if task.recurrence or task.series_parent_id:
                if scope not in ('occurrence','series'):
                    raise HTTPException(422,'Выберите: изменить одно событие или всю серию.')
                root=self.require(task.series_parent_id) if task.series_parent_id else task
                if scope=='series' and (root.recurrence or {}).get('frequency') == 'google':
                    changed = self.update_google_series(root, task, data, occurrence_start)
                elif scope=='occurrence' and not task.series_parent_id:
                    if occurrence_start is None: raise HTTPException(422,'Укажите выбранное повторение.')
                    finish = require_occurrence(root,occurrence_start)
                    if occurrence_start in self.recurrences.exceptions().get(root.id,set()):
                        raise HTTPException(409,"Это повторение уже удалено или изменено.")
                    self.recurrences.exclude(root.id,occurrence_start)
                    single=TaskInput(**{**data.model_dump(),'recurrence':None})
                    self.validate_edit(root, single, occurrence_start, finish)
                    changed=self.dao.add(single)
                    changed.from_google=root.from_google
                    changed.is_all_day=root.is_all_day
                    changed.series_parent_id=root.id
                    changed.series_original_start=occurrence_start
                elif scope=='series':
                    selected=occurrence_start or task.series_original_start or task.start
                    if not task.series_parent_id: require_occurrence(root,selected)
                    zone=ZoneInfo(root.recurrence['timezone'])
                    old_anchor=root.start
                    delta=data.start.astimezone(zone).replace(tzinfo=None)-selected.astimezone(zone).replace(tzinfo=None)
                    new_anchor=(root.start.astimezone(zone).replace(tzinfo=None)+delta).replace(tzinfo=zone).astimezone(timezone.utc)
                    changes=TaskInput(is_fixed=data.is_fixed,category=data.category,title=data.title,description=data.description,start=new_anchor,
                        end=new_anchor+(data.end-data.start),recurrence=data.recurrence or root.recurrence)
                    excluded=self.recurrences.exceptions().get(root.id,set())
                    self.recurrences.clear(root.id)
                    step=7 if root.recurrence['frequency']=='weekly' else 1
                    for previous in excluded:
                        index=(previous.astimezone(zone).date()-old_anchor.astimezone(zone).date()).days//step
                        shifted=new_anchor.astimezone(zone)+timedelta(days=index*step)
                        self.recurrences.exclude(root.id,shifted.astimezone(timezone.utc))
                    self.validate([changes],ignore=root.id)
                    for key,value in changes.model_dump().items(): setattr(root,key,value)
                    root.recurrence=changes.recurrence.model_dump()
                    # Keep renamed descriptions in detached occurrences coherent;
                    # their explicitly moved times remain individual exceptions.
                    for child in self.session.scalars(select(Task).where(Task.series_parent_id==root.id)):
                        child.is_fixed=data.is_fixed;child.title=data.title;child.description=data.description;child.category=data.category
                    changed=root
                else:
                    self.validate_edit(task, data, task.start, task.end, ignore=task.id)
                    for key,value in data.model_dump().items(): setattr(task,key,value)
                    task.recurrence=None
                    changed=task
            else:
                if task.is_all_day:
                    data.recurrence = None
                self.validate_edit(task, data, task.start, task.end, ignore=task.id)
                for key,value in data.model_dump().items(): setattr(task,key,value)
                task.recurrence=data.recurrence.model_dump() if data.recurrence else None
                changed=task
            if commit_changes: commit(self.session)
            else: self.session.flush()
            return changed
        except HTTPException:
            self.session.rollback()
            raise

    def delete(self,task_id,scope=None,occurrence_start=None,commit_changes=True):
        calendar_lock(self.session)
        task=self.require(task_id)
        if task.recurrence or task.series_parent_id:
            if scope=='occurrence':
                if task.series_parent_id: self.dao.delete(task)
                else:
                    if occurrence_start is None: raise HTTPException(422,'Укажите начало удаляемого повторения.')
                    require_occurrence(task,occurrence_start)
                    self.recurrences.exclude(task.id,occurrence_start)
            elif scope=='series':
                root=self.require(task.series_parent_id) if task.series_parent_id else task
                self.dao.delete(root)
            else: raise HTTPException(422,'Выберите: удалить одно событие или всю серию.')
        else: self.dao.delete(task)
        if commit_changes: commit(self.session)
        else: self.session.flush()
