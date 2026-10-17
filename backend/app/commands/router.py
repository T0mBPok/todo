from uuid import UUID
from fastapi import APIRouter,Depends
from sqlalchemy.orm import Session
from app.core.database import get_session
from app.commands.schemas import CommandRequest,Execute
from app.commands.service import CommandService
router=APIRouter(prefix='/commands',tags=['commands'])
@router.post('')
def prepare(data:CommandRequest,session:Session=Depends(get_session)):
    return CommandService(session).prepare(data)
@router.post('/{command_id}/execute')
def execute(command_id:UUID,data:Execute,session:Session=Depends(get_session)):
    return CommandService(session).execute(command_id,data)
