from uuid import UUID
from fastapi import APIRouter,Depends
from app.core.database import get_session
from app.balance.schemas import BalanceRequest,Apply
from app.balance.service import BalanceService
router=APIRouter(prefix='/balance',tags=['balance'])
@router.post('')
def prepare(data:BalanceRequest,session=Depends(get_session)):return BalanceService(session).prepare(data)
@router.post('/{id}/apply')
def apply(id:UUID,data:Apply,session=Depends(get_session)):return BalanceService(session).apply(id,data)

@router.post('/scan')
def scan(session=Depends(get_session)):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return BalanceService(session).prepare(BalanceRequest(day=datetime.now(ZoneInfo('Asia/Tomsk')).date(),scan_days=7,horizon_days=7))
