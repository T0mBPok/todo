from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_session
from app.plans.schemas import ConfirmPlan, PlanRead, PlanRequest
from app.plans.service import PlanService
from app.tasks.schemas import TaskRead

router = APIRouter(prefix='/plans', tags=['plans'])

@router.post('', response_model=PlanRead, status_code=201)
def create_plan(data: PlanRequest, session: Session = Depends(get_session)):
    plan = PlanService(session).create(data)
    result = PlanRead.model_validate(plan)
    marker = ' Нормализованный текст: '
    if marker in plan.note:
        result.normalized_text = plan.note.split(marker,1)[1].split(' Без указанной длительности',1)[0]
    else:
        result.normalized_text = data.text
    return result

@router.get('/{plan_id}', response_model=PlanRead)
def get_plan(plan_id: UUID, session: Session = Depends(get_session)):
    return PlanService(session).require(plan_id)

@router.post('/{plan_id}/confirm', response_model=list[TaskRead])
def confirm_plan(plan_id: UUID, data: ConfirmPlan, session: Session = Depends(get_session)):
    return PlanService(session).confirm(plan_id, data)
