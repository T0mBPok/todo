from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import text
from uuid import uuid4
from app.main import app
from app.core.database import engine,get_session,Base
with engine.connect() as connection:
    transaction=connection.begin();schema='commands_test_'+uuid4().hex
    connection.execute(text(f'CREATE SCHEMA {schema}'));connection.execute(text(f'SET LOCAL search_path TO {schema}'))
    Base.metadata.create_all(connection)
    try:
        with Session(bind=connection,join_transaction_mode='create_savepoint',expire_on_commit=False) as session:
            app.dependency_overrides[get_session]=lambda:session
            with TestClient(app) as api:
                for sentence,days in [('Добавь новые тренировки каждый вторник, четверг и субботу в 18:00', {1,3,5}),('Добавь новые занятия йогой по пятницам и воскресеньям в 09:00',{4,6})]:
                    response=api.post('/api/commands',json={'text':sentence,'timezone':'Asia/Tomsk'})
                    print(sentence,response.status_code,response.text,flush=True)
                    assert response.status_code==200 and response.json()['kind']=='plan',response.text
                    plan=response.json()['plan'];tasks=plan['tasks']
                    assert {datetime.fromisoformat(t['start']).astimezone(ZoneInfo('Asia/Tomsk')).weekday() for t in tasks}==days,tasks
                    assert len(tasks)==len(days) and all(t['recurrence']['frequency']=='weekly' for t in tasks),tasks
                    result=api.post('/api/plans/'+plan['id']+'/confirm',json={'tasks':tasks})
                    assert result.status_code==200,result.text
                print('LIVE MULTI-DAY RECURRENCES: PASS',flush=True)
    finally:
        app.dependency_overrides.clear();transaction.rollback()
        print('All synthetic data rolled back.',flush=True)
