from uuid import UUID
from typing import Literal
from fastapi import APIRouter, Depends, Response
from pydantic import AwareDatetime
from sqlalchemy.orm import Session
from app.core.database import get_session
from app.tasks.schemas import TaskInput, TaskRead
from app.tasks.service import TaskService

router = APIRouter(prefix='/tasks', tags=['tasks'])

@router.get('', response_model=list[TaskRead])
def list_tasks(start: AwareDatetime | None = None, end: AwareDatetime | None = None, session: Session = Depends(get_session)):
    return TaskService(session).list(start, end)

@router.post('', response_model=TaskRead, status_code=201)
def create_task(data: TaskInput, session: Session = Depends(get_session)):
    return TaskService(session).create(data)

@router.put('/{task_id}', response_model=TaskRead)
def update_task(task_id: UUID, data: TaskInput, scope: Literal['occurrence','series'] | None = None, occurrence_start: AwareDatetime | None = None, session: Session = Depends(get_session)):
    return TaskService(session).update(task_id, data,scope,occurrence_start)

@router.delete('/{task_id}', status_code=204)
def delete_task(task_id: UUID, scope: Literal['occurrence','series'] | None = None, occurrence_start: AwareDatetime | None = None, session: Session = Depends(get_session)):
    TaskService(session).delete(task_id,scope,occurrence_start)
    return Response(status_code=204)
