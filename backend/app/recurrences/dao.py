from sqlalchemy import select,delete
from sqlalchemy.dialects.postgresql import insert
from app.recurrences.models import RecurrenceException

class RecurrenceDAO:
    def __init__(self,session):
        self.session=session

    def exceptions(self):
        result={}
        for exception in self.session.scalars(select(RecurrenceException)):
            result.setdefault(exception.task_id,set()).add(exception.occurrence_start)
        return result

    def exclude(self,task_id,start):
        self.session.execute(insert(RecurrenceException).values(task_id=task_id,occurrence_start=start).on_conflict_do_nothing())

    def clear(self,task_id):
        self.session.execute(delete(RecurrenceException).where(RecurrenceException.task_id==task_id))
