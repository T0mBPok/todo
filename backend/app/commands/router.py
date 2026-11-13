from uuid import UUID
from fastapi import APIRouter,Depends
from sqlalchemy.orm import Session
from app.core.database import get_session
from app.commands.schemas import ClearCalendar,CommandRequest,Execute
from app.commands.service import CommandService
from app.commands.calendar_clear import execute_clear
router=APIRouter(prefix='/commands',tags=['commands'])
@router.post('')
def prepare(data:CommandRequest,session:Session=Depends(get_session)):
    return CommandService(session).prepare(data)
@router.post('/{command_id}/execute')
def execute(command_id:UUID,data:Execute,session:Session=Depends(get_session)):
    return CommandService(session).execute(command_id,data)


@router.post('/{command_id}/clear-calendar')
def clear_calendar(command_id: UUID, data: ClearCalendar | None = None, session: Session = Depends(get_session)):
    return execute_clear(session, command_id, data.choices if data else [])
