from fastapi import HTTPException
from app.plans.ai import AIPlanner
from app.plans.dao import PlanDAO
from app.plans.schemas import PlanReview
from app.recurrences.service import validate_conflicts
from app.tasks.dao import TaskDAO
from app.tasks.schemas import TaskRead
from app.tasks.service import commit,calendar_lock,TaskService

class PlanService:
    def __init__(self, session, planner=None):
        self.session = session
        self.dao = PlanDAO(session)
        self.tasks = TaskDAO(session)
        self.planner = planner or AIPlanner()

    def require(self, plan_id, lock=False):
        plan = self.dao.get(plan_id, lock)
        if plan is None:
            raise HTTPException(404, 'План не найден')
        return plan

    def create(self, request):
        # Send each stored series once; expanding months of repetitions exhausts the local model context.
        calendar = self.tasks.list()
        existing = [TaskRead.model_validate(task).model_dump(mode='json',exclude={'description','occurrence_id','occurrence_start','series_parent_id','series_original_start','plan_id'}) for task in calendar[:100]]
        result = self.planner.generate(request, existing)
        return self.save_draft(request, result, calendar)

    def save_draft(self, request, result, calendar=None):
        calendar = self.tasks.list() if calendar is None else calendar
        existing = [task for task in calendar if not task.is_all_day]
        exceptions = TaskService(self.session).recurrences.exceptions()
        reviews = {item.task_index: item for item in result.review}
        for index, task in enumerate(result.tasks):
            others = result.tasks[:index] + result.tasks[index+1:]
            try:
                validate_conflicts([task], existing + others, exceptions)
            except HTTPException as error:
                if error.status_code != 409:
                    raise
                reason = error.detail.split(').', 1)[0] + ').'
                if index in reviews:
                    reviews[index].reason = (reviews[index].reason + ' ' + reason)[:500]
                else:
                    reviews[index] = PlanReview(task_index=index, reason=reason[:500])
        result.review = sorted(reviews.values(), key=lambda item: item.task_index)
        plan = self.dao.add(request, result)
        commit(self.session)
        return plan

    def confirm(self, plan_id, data):
        calendar_lock(self.session)
        plan = self.require(plan_id, lock=True)
        if plan.status == 'confirmed':
            return self.tasks.for_plan(plan_id)
        TaskService(self.session).validate(data.tasks)
        tasks = [self.tasks.add(task, plan_id=plan.id) for task in data.tasks]
        plan.tasks = [task.model_dump(mode='json') for task in data.tasks]
        plan.review = []
        plan.status = 'confirmed'
        commit(self.session)
        return tasks
