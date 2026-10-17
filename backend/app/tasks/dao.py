from sqlalchemy import select
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

    def delete(self, task):
        self.session.delete(task)
