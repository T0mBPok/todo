from sqlalchemy import Uuid, any_, bindparam, delete, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import load_only
from app.tasks.models import Task

class TaskDAO:
    def __init__(self, session):
        self.session = session

    def list(self, start=None, end=None):
        query = select(Task).order_by(Task.start)
        if start is not None:
            query = query.where(Task.end > start)
        if end is not None:
            query = query.where(Task.start < end)
        return list(self.session.scalars(query))

    def get(self, task_id):
        return self.session.get(Task, task_id)

    def for_plan(self, plan_id):
        return list(self.session.scalars(select(Task).where(Task.plan_id == plan_id).order_by(Task.start)))

    def add(self, data, plan_id=None):
        task = Task(**data.model_dump(), plan_id=plan_id)
        self.session.add(task)
        return task

    def calendar_rows(self, owner_id):
        query = select(Task).options(load_only(
            Task.id, Task.title, Task.start, Task.end, Task.recurrence, Task.series_parent_id, Task.is_all_day,
        )).where(Task.owner_id == owner_id).order_by(Task.id)
        return list(self.session.scalars(query))

    def delete_calendar(self, owner_id, task_ids):
        confirmed_ids = bindparam('confirmed_ids', type_=ARRAY(Uuid()))
        statement = delete(Task).where(Task.owner_id == owner_id, Task.id == any_(confirmed_ids))
        self.session.execute(statement.execution_options(synchronize_session=False), {'confirmed_ids': task_ids})

    def delete(self, task):
        self.session.delete(task)
