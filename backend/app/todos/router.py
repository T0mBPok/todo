from uuid import UUID
from fastapi import APIRouter,Depends,Response
from app.core.database import get_session
from app.todos.schemas import TodoInput,TodoRead,VoiceRequest
from app.todos.service import TodoService
router=APIRouter(prefix='/todos',tags=['todos'])
@router.post('/classify')
def classify(data: TodoInput):
    from app.core.priority import classify_category
    return {'category': classify_category(data.title,data.description)}

@router.get('',response_model=list[TodoRead])
def list_tasks(session=Depends(get_session)):return TodoService(session).dao.list()
@router.post('',response_model=TodoRead,status_code=201)
def create(data:TodoInput,session=Depends(get_session)):return TodoService(session).create(data)
@router.put('/{id}',response_model=TodoRead)
def update(id:UUID,data:TodoInput,session=Depends(get_session)):return TodoService(session).update(id,data)
@router.delete('/{id}',status_code=204)
def delete(id:UUID,session=Depends(get_session)):TodoService(session).delete(id);return Response(status_code=204)
@router.post('/commands/prepare')
def prepare(data:VoiceRequest,session=Depends(get_session)):return TodoService(session).prepare(data)
@router.post('/commands/{id}/execute')
def execute(id:UUID,session=Depends(get_session)):return TodoService(session).execute(id)
