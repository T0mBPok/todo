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
                tomorrow=datetime.now(ZoneInfo('Asia/Tomsk'))+timedelta(days=1)
                start=tomorrow.replace(hour=18,minute=0,second=0,microsecond=0)
                created=api.post('/api/tasks',json={'title':'Тренировка','description':'Форма','start':start.isoformat(),'end':(start+timedelta(hours=1)).isoformat()})
                assert created.status_code==201,created.text
                for sentence,expected in [('Перенеси завтра тренировку на семь вечера','update'),('Добавь в описание тренировки: взять бутылку воды','update'),('Удали завтра тренировку','delete')]:
                    response=api.post('/api/commands',json={'text':sentence,'timezone':'Asia/Tomsk'})
                    print(sentence,response.status_code,response.text,flush=True)
                    assert response.status_code==200 and response.json()['kind']=='command',response.text
                    cmd=response.json();assert cmd['operations'][0]['instruction']['operation']==expected
                    result=api.post('/api/commands/'+cmd['id']+'/execute',json={'choices':[{'candidate':0}]})
                    assert result.status_code==200,result.text
                    if expected=='update':
                        task=result.json()['tasks'][0]
                        if 'Перенеси' in sentence: assert datetime.fromisoformat(task['start']).astimezone(ZoneInfo('Asia/Tomsk')).hour==19,task
                        else: assert 'вод' in task['description'].lower() and 'Форма' in task['description'],task
                plan=api.post('/api/commands',json={'text':'Завтра в десять утра встреча с коллегами. В описании: обсудить бюджет и взять ноутбук.','timezone':'Asia/Tomsk'})
                print('CREATE WITH DESCRIPTION',plan.status_code,plan.text,flush=True)
                assert plan.status_code==200 and plan.json()['kind']=='plan',plan.text
                assert 'бюджет' in plan.json()['plan']['tasks'][0]['description'].lower(),plan.text
                print('LIVE LOCAL COMMANDS: PASS',flush=True)
    finally:
        app.dependency_overrides.clear();transaction.rollback()
        print('All synthetic data rolled back.',flush=True)
