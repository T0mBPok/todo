from sqlalchemy import select,delete
from sqlalchemy.dialects.postgresql import insert
from app.recurrences.models import RecurrenceException
from app.tasks.models import Task

class RecurrenceDAO:
    def __init__(self,session):
        self.session=session

    def exceptions(self):
        result={}
        for exception in self.session.scalars(select(RecurrenceException).join(Task, Task.id == RecurrenceException.task_id)):
            result.setdefault(exception.task_id,set()).add(exception.occurrence_start)
        return result

    def exclude(self,task_id,start):
        if self.session.scalar(select(Task.id).where(Task.id == task_id)) is None:
            return
        self.session.execute(insert(RecurrenceException).values(task_id=task_id,occurrence_start=start).on_conflict_do_nothing())

    def clear(self,task_id):
        if self.session.scalar(select(Task.id).where(Task.id == task_id)) is not None:
            self.session.execute(delete(RecurrenceException).where(RecurrenceException.task_id == task_id))
