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
                from test_grounded_calendar import seed
                tasks=seed(api)
                phrase='Э-э, короче, родной, смотри, мне надо, чтобы ты в субботу убрал все задачи, кроме пары в университете.'
                response=api.post('/api/commands',json={'text':phrase,'timezone':'Asia/Tomsk'})
                print('GROUNDED DELETE',response.status_code,response.text,flush=True)
                assert response.status_code==200,response.text
                command=response.json();assert command['kind']=='command'
                chosen={task['id'] for op in command['operations'] for task in op['candidates']}
                assert chosen=={tasks[1]['id'],tasks[2]['id']},chosen
                assert all(op['requires_confirmation'] for op in command['operations'])
                # Choose a named event from the same real calendar context.
                response=api.post('/api/commands',json={'text':'Перенеси пару в универе в субботу на 16:00','timezone':'Asia/Tomsk'})
                print('GROUNDED UPDATE',response.status_code,response.text,flush=True)
                assert response.status_code==200,response.text
                command=response.json()
                assert command['operations'][0]['candidates'][0]['id']==tasks[0]['id']
                result=api.post('/api/commands/'+command['id']+'/execute',json={'choices':[{'candidate':0,'scope':'occurrence'}]})
                assert result.status_code==200,result.text
                task=result.json()['tasks'][0]
                assert datetime.fromisoformat(task['start']).astimezone(ZoneInfo('Asia/Tomsk')).hour==16,task
                response=api.post('/api/commands',json={'text':'Сделай существующую пару в университете повторяющейся каждую субботу','timezone':'Asia/Tomsk'})
                print('GROUNDED RECURRENCE',response.status_code,response.text,flush=True)
                assert response.status_code==200 and response.json()['kind']=='command',response.text
                command=response.json()
                assert command['operations'][0]['candidates'][0]['id']==tasks[0]['id']
                assert command['operations'][0]['instruction']['new_recurrence']=='weekly'
                response=api.post('/api/commands',json={'text':'Добавь завтра в девять утра встречу с врачом. В описании: взять анализы.','timezone':'Asia/Tomsk'})
                print('GROUNDED CREATE',response.status_code,response.text,flush=True)
                assert response.status_code==200 and response.json()['kind']=='plan',response.text
                assert 'анализ' in response.json()['plan']['tasks'][0]['description'].lower()
                print('LIVE MODEL + CALENDAR REFERENCES + BACKEND: PASS',flush=True)
    finally:
        app.dependency_overrides.clear();transaction.rollback()
        print('All synthetic data rolled back.',flush=True)
