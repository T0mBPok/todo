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
                cases=[
                    ('Внеси задачу, мне нужно будет вот сегодня сходить за продуктами, наверное купить типа морковку, свеклу, там, картошку.',1,['морков','св','картош']),
                    ('Надо написать отчёт, там проверить расчёты, вставить графики и отправить начальнику до пятницы.',1,['расч','график','пятниц']),
                    ('Купить продукты: молоко и хлеб. Ещё отдельно оплатить интернет.',2,['молок','хлеб']),
                    ('Купить молоко.',1,[]),
                ]
                for phrase,count,details in cases:
                    response=api.post('/api/todos/commands/prepare',json={'text':phrase})
                    print('MEANING',phrase,response.status_code,response.text,flush=True)
                    assert response.status_code==200,response.text
                    command=response.json();ops=command['operations']
                    assert len(ops)==count and all(op['action']['action']=='create' for op in ops),ops
                    descriptions=' '.join(op['action']['description'] or '' for op in ops).lower().replace('ё','е')
                    for stem in details:assert stem in descriptions,(stem,ops)
                    assert all(len(op['action']['title'].split())<=7 for op in ops),ops
                    if phrase=='Купить молоко.':assert not ops[0]['action']['description'],ops
                    # Verify persistence, then clear only our isolated-schema test records.
                    result=api.post('/api/todos/commands/'+command['id']+'/execute')
                    assert result.status_code==200,result.text
                    for task in result.json()['tasks']:
                        assert api.delete('/api/todos/'+task['id']).status_code==204
                print('TITLE / DESCRIPTION / INDEPENDENT GOALS: PASS',flush=True)
    finally:
        app.dependency_overrides.clear();transaction.rollback()
        print('All synthetic data rolled back.',flush=True)
