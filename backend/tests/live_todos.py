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
                request={'text':'Надо купить продукты и закончить отчёт. В описание отчёта добавь: проверить расчёты.'}
                response=api.post('/api/todos/commands/prepare',json=request)
                print('TODO CREATE',response.status_code,response.text,flush=True)
                assert response.status_code==200,response.text
                command=response.json();assert len(command['operations'])==2,command
                result=api.post('/api/todos/commands/'+command['id']+'/execute')
                assert result.status_code==200,result.text
                tasks=api.get('/api/todos').json();assert len(tasks)==2,tasks
                assert all('start' not in t for t in tasks)
                report=next(t for t in tasks if 'отч' in t['title'].lower())
                assert 'расч' in report['description'].lower(),report
                response=api.post('/api/todos/commands/prepare',json={'text':'Отчёт я уже закончил, отметь выполненным'})
                print('TODO COMPLETE',response.status_code,response.text,flush=True)
                assert response.status_code==200,response.text
                command=response.json()
                assert command['operations'][0]['snapshot']['id']==report['id']
                assert command['operations'][0]['action']['action']=='complete'
                assert api.post('/api/todos/commands/'+command['id']+'/execute').status_code==200
                assert next(t for t in api.get('/api/todos').json() if t['id']==report['id'])['completed']
                print('LIVE LOCAL VOICE TEXT -> TODO LIST: PASS',flush=True)
    finally:
        app.dependency_overrides.clear();transaction.rollback()
        print('All synthetic data rolled back.',flush=True)
