from sqlalchemy import select
from app.plans.models import Plan

class PlanDAO:
    def __init__(self, session):
        self.session = session

    def add(self, request, result):
        plan = Plan(text=request.text, timezone=request.timezone,
                    tasks=[task.model_dump(mode='json') for task in result.tasks],
                    review=[item.model_dump(mode='json') for item in result.review], note=result.note)
        self.session.add(plan)
        return plan

    def get(self, plan_id, lock=False):
        query = select(Plan).where(Plan.id == plan_id)
        if lock:
            query = query.with_for_update()
        return self.session.scalar(query)
