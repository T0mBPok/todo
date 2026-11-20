import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime,timedelta,timezone
from sqlalchemy import or_,select,update
from app.core import config
from app.core.database import SessionLocal,AccountSessionLocal
from app.google_sync.models import GoogleConnection
from app.google_sync.service import automatic_sync
log=logging.getLogger('uvicorn.error')

def run_due_syncs():
    now=datetime.now(timezone.utc)
    with SessionLocal.begin() as db:
        rows=db.scalars(select(GoogleConnection).where(
            GoogleConnection.sync_enabled.is_(True),
            or_(GoogleConnection.next_sync_at.is_(None),GoogleConnection.next_sync_at<=now)
        ).order_by(GoogleConnection.next_sync_at.asc().nullsfirst()).limit(10).with_for_update(skip_locked=True)).all()
        owners=[row.owner_id for row in rows]
        for row in rows:row.next_sync_at=now+timedelta(minutes=5)
    for owner in owners:
        try:
            with AccountSessionLocal(info={'owner_id':owner}) as db:
                result=automatic_sync(db)
            if result is None:
                with SessionLocal.begin() as db:
                    db.execute(update(GoogleConnection).where(GoogleConnection.owner_id==owner).values(
                        next_sync_at=datetime.now(timezone.utc)+timedelta(seconds=20)))
            else:
                log.info('google_sync outcome=ok changed=%s conflicts=%s partial=%s',
                         result['changed'],result['conflicts'],result['partial'])
        except Exception as error:
            # OAuth grants, addresses, external payloads and raw exception text stay out of logs/UI.
            log.warning('google_sync outcome=failed exception=%s',type(error).__name__)
            with SessionLocal.begin() as db:
                db.execute(update(GoogleConnection).where(GoogleConnection.owner_id==owner).values(
                    sync_error='Не удалось связаться с Google. Повторим обмен автоматически. Если ошибка повторяется, подключите Google заново.',
                    next_sync_at=datetime.now(timezone.utc)+timedelta(minutes=2)))

async def sync_loop():
    while True:
        try:
            await asyncio.to_thread(run_due_syncs)
        except Exception as error:
            log.warning('google_sync_scheduler outcome=failed exception=%s',type(error).__name__)
        await asyncio.sleep(10)

@asynccontextmanager
async def lifespan(app):
    task=None
    if config.GOOGLE_SYNC_WORKER and config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET and config.GOOGLE_TOKEN_KEY:
        task=asyncio.create_task(sync_loop())
    try:
        yield
    finally:
        if task:
            task.cancel()
            try:await task
            except asyncio.CancelledError:pass
