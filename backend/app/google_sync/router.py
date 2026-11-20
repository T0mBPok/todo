from typing import Annotated, Literal
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import config
from app.core.database import get_session
from app.google_sync.models import GoogleConnection, GoogleState, GoogleLink
from app.google_sync.oauth import begin, cipher, complete
from app.google_sync.service import sync, conflict_records, resolve_conflict

router = APIRouter(prefix='/google', tags=['google'])
DB = Annotated[Session, Depends(get_session)]


class GoogleCallbackRoute(APIRoute):
    def get_route_handler(self):
        handle = super().get_route_handler()

        async def redirect_on_missing_session(request: Request):
            try:
                return await handle(request)
            except HTTPException as error:
                if error.status_code == 401:
                    return RedirectResponse('/', status_code=303)
                raise

        return redirect_on_missing_session


class SyncRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    direction: Literal['pull', 'push']
    kind: Literal['event', 'todo']


@router.get('/status')
def status(db: DB):
    try:
        cipher()
        configured = True
    except HTTPException:
        configured = False
    connection=db.scalar(select(GoogleConnection))
    return {'configured':configured,'connected':connection is not None,
            'auto_sync':bool(connection and connection.sync_enabled),
            'last_synced_at':connection.last_synced_at if connection else None,
            'sync_error':connection.sync_error if connection else None,
            'conflicts':connection.sync_conflicts if connection else 0,
            'partial':bool(connection and connection.sync_partial)}



@router.post('/connect')
def connect(request: Request, db: DB):
    if request.headers.get('origin') != config.PUBLIC_ORIGIN:
        raise HTTPException(409, f'Для подключения Google откройте {config.PUBLIC_ORIGIN} и войдите в Импульс на этом адресе.')
    return {'url': begin(db, request)}


def callback(request: Request, db: DB, state: str = Query('', max_length=128),
             code: str = Query('', max_length=2048)):
    try:
        if not code:
            raise HTTPException(400, 'Google не вернул разрешение.')
        complete(db, request, state, code)
    except HTTPException as error:
        return RedirectResponse('/?google=error&reason=' + ('permissions' if error.status_code == 400 else 'connection'), 303)
    return RedirectResponse('/?google=connected', 303)


router.add_api_route(
    '/callback', callback, methods=['GET'], include_in_schema=False,
    route_class_override=GoogleCallbackRoute,
)


@router.post('/disconnect', status_code=204)
def disconnect(db: DB):
    # Remove the stored grant and any pending authorization for this account.
    for model in (GoogleState, GoogleConnection):
        row = db.scalar(select(model).with_for_update())
        if row is not None:
            db.delete(row)
    db.commit()


@router.post('/sync')
def synchronize(data: SyncRequest, db: DB):
    return sync(db, data.direction, data.kind)


class AutoSyncRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    enabled:bool

@router.post('/auto-sync')
def configure_auto_sync(data:AutoSyncRequest,db:DB):
    connection=db.scalar(select(GoogleConnection).with_for_update())
    if connection is None:raise HTTPException(409,'Сначала подключите аккаунт Google.')
    connection.sync_enabled=data.enabled
    connection.next_sync_at=datetime.now(timezone.utc) if data.enabled else None
    connection.sync_error=None
    db.commit()
    return status(db)

@router.post('/sync-now',status_code=202)
def schedule_sync(db:DB):
    connection=db.scalar(select(GoogleConnection).with_for_update())
    if connection is None or not connection.sync_enabled:
        raise HTTPException(409,'Сначала включите автоматическую синхронизацию.')
    connection.next_sync_at=datetime.now(timezone.utc)
    connection.sync_error=None
    db.commit()
    return {'note':'Обмен запланирован. Статус обновится автоматически.'}


class ResolveRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    local_id:UUID
    kind:Literal['event','todo']
    source:Literal['local','remote']

@router.get('/conflicts')
def list_conflicts(db:DB):
    return conflict_records(db)

@router.post('/resolve')
def resolve(data:ResolveRequest,db:DB):
    return resolve_conflict(db,data.kind,data.local_id,data.source)
