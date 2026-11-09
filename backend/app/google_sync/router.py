from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import config
from app.core.database import get_session
from app.google_sync.models import GoogleConnection, GoogleState
from app.google_sync.oauth import begin, cipher, complete
from app.google_sync.service import sync

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
    return {'configured': configured, 'connected': db.scalar(select(GoogleConnection.owner_id)) is not None}


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
