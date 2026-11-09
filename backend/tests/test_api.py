from datetime import datetime
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text as sql_text
from sqlalchemy.orm import Session
from app.main import app
from app.core.database import engine, get_session, Base
from app.core import config
from app.users.router import require_user
from app.plans.ai import AIPlanner
from app.plans.models import Plan
from app.plans.schemas import PlanOutput, PlanRequest
from app.tasks.models import Task

@pytest.fixture
def client():
    # Every test gets a real PostgreSQL transaction, always rolled back.
    with engine.connect() as connection:
        transaction = connection.begin()
        # Isolate tests from the user's infinite recurring series as well as writes.
        schema='api_test_'+uuid4().hex
        connection.execute(sql_text(f'CREATE SCHEMA {schema}'))
        connection.execute(sql_text(f'SET LOCAL search_path TO {schema}'))
        Base.metadata.create_all(connection)
        connection.execute(sql_text("ALTER TABLE tasks ADD CONSTRAINT tasks_no_overlap EXCLUDE USING gist (tstzrange(start, \"end\", '[)') WITH &&) WHERE (recurrence IS NULL)"))
        with Session(bind=connection, join_transaction_mode='create_savepoint', expire_on_commit=False) as session:
            app.dependency_overrides[get_session] = lambda: session
            app.dependency_overrides[require_user] = lambda: None
            with TestClient(app, headers={'Origin': config.PUBLIC_ORIGIN}) as client:
                yield client, session
            app.dependency_overrides.clear()
        transaction.rollback()

def task(start='10:00', end='11:00'):
    return {'title': 'Встреча', 'start': f'2098-11-12T{start}:00+07:00', 'end': f'2098-11-12T{end}:00+07:00'}

def test_task_crud_and_timezone(client):
    api, _ = client
    created = api.post('/api/tasks', json=task())
    assert created.status_code == 201
    data = created.json()
    assert datetime.fromisoformat(data['start']).hour == 3
    assert any(t['id'] == data['id'] for t in api.get('/api/tasks').json())
    assert api.put('/api/tasks/' + data['id'], json=task('12:00', '13:00')).status_code == 200
    assert api.delete('/api/tasks/' + data['id']).status_code == 204
    assert api.delete('/api/tasks/' + data['id']).status_code == 404

def test_database_conflicts_and_adjacent_tasks(client):
    api, _ = client
    assert api.post('/api/tasks', json=task()).status_code == 201
    assert api.post('/api/tasks', json=task('10:30', '11:30')).status_code == 409
    assert api.post('/api/tasks', json=task('11:00', '12:00')).status_code == 201

@pytest.mark.parametrize('data', [task('11:00','10:00'), {**task(), 'title':' '}, {**task(), 'start':'2098-11-12T10:00:00'}])
def test_validation(client, data):
    assert client[0].post('/api/tasks', json=data).status_code == 422

def test_timezone_validation(client):
    assert client[0].post('/api/plans', json={'text':'Встреча', 'timezone':'bad/zone'}).status_code == 422

def test_plan_preview_confirm_idempotency(client, monkeypatch):
    api, session = client
    monkeypatch.setattr(AIPlanner, 'generate', lambda self, request, existing: PlanOutput(tasks=[task()], note='Длительность час'))
    before = session.scalar(select(func.count()).select_from(Task))
    plan = api.post('/api/plans', json={'text':'Завтра встреча'}).json()
    assert plan['status'] == 'draft'
    assert session.scalar(select(func.count()).select_from(Task)) == before
    result = api.post('/api/plans/' + plan['id'] + '/confirm', json={'tasks':plan['tasks']})
    assert result.status_code == 200
    again = api.post('/api/plans/' + plan['id'] + '/confirm', json={'tasks':plan['tasks']})
    assert again.json() == result.json()
    assert session.scalar(select(func.count()).select_from(Task)) == before + 1
    assert api.get('/api/plans/' + plan['id']).json()['status'] == 'confirmed'

def test_confirm_rolls_back_entire_batch(client):
    api, session = client
    plan = Plan(id=uuid4(), text='test', timezone='Asia/Tomsk', tasks=[task()], note='', status='draft')
    session.add(plan); session.commit()
    before = session.scalar(select(func.count()).select_from(Task))
    result = api.post(f'/api/plans/{plan.id}/confirm', json={'tasks':[task(), task('10:30','12:00')]})
    assert result.status_code == 409
    assert session.scalar(select(func.count()).select_from(Task)) == before
    assert api.get(f'/api/plans/{plan.id}').json()['status'] == 'draft'

def test_ai_structured_response_contract(monkeypatch):
    import httpx
    import json
    def fake_post(url, **kwargs):
        assert url.endswith('/api/chat')
        assert kwargs['json']['model'] == config.OLLAMA_MODEL
        assert kwargs['json']['stream'] is False
        assert kwargs['json']['think'] is False
        assert kwargs['json']['format']['type'] == 'object'
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'message': {'content': json.dumps({'tasks': [task()], 'note': 'Час', 'needs_clarification': False})},
            'done_reason': 'stop'})
    monkeypatch.setattr(httpx, 'post', fake_post)
    result = AIPlanner().generate(PlanRequest(text='Встреча'), [])
    assert len(result.tasks) == 1

def test_ai_asks_for_clarification(client, monkeypatch):
    import httpx
    import json
    monkeypatch.setattr(httpx, 'post', lambda url, **kwargs: httpx.Response(200,
        request=httpx.Request('POST', url), json={'message': {'content': json.dumps({
            'tasks': [], 'note': 'В какой день встретиться?', 'needs_clarification': True})}}))
    response = client[0].post('/api/plans', json={'text': 'На днях встреться с Сашей'})
    assert response.status_code == 422
    assert response.json()['detail'] == 'В какой день встретиться?'

def test_ollama_unavailable(client, monkeypatch):
    import httpx
    def unavailable(*args, **kwargs):
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(httpx, 'post', unavailable)
    assert client[0].post('/api/plans', json={'text': 'Завтра встреча'}).status_code == 503

def test_invalid_model_output(client, monkeypatch):
    import httpx
    import json
    monkeypatch.setattr(httpx, 'post', lambda url, **kwargs: httpx.Response(200,
        request=httpx.Request('POST', url), json={'message': {'content': json.dumps({
            'tasks': [task('11:00','10:00')], 'note': '', 'needs_clarification': False})}}))
    assert client[0].post('/api/plans', json={'text': 'Завтра встреча'}).status_code == 502

def test_voice_transcript_route(client, monkeypatch):
    monkeypatch.setattr('app.voice.router.transcribe_audio', lambda audio: {'text': 'Завтра встреча'})
    response = client[0].post('/api/voice/transcribe', content=b'audio', headers={'content-type':'audio/webm;codecs=opus'})
    assert response.status_code == 200
    assert response.json()['text'] == 'Завтра встреча'

def test_voice_empty_and_wrong_content_type(client):
    assert client[0].post('/api/voice/transcribe', content=b'', headers={'content-type':'audio/webm'}).status_code == 422
    assert client[0].post('/api/voice/transcribe', json={'text':'not audio'}).status_code == 415

def test_voice_upload_limit(client, monkeypatch):
    monkeypatch.setattr('app.voice.router.MAX_AUDIO_BYTES', 16)
    assert client[0].post('/api/voice/transcribe', content=b'x' * 17, headers={'content-type':'audio/webm'}).status_code == 413

def test_voice_invalid_audio(client):
    response = client[0].post('/api/voice/transcribe', content=b'broken audio', headers={'content-type':'audio/webm'})
    assert response.status_code == 422

def test_gigaam_response_metadata(monkeypatch):
    import httpx
    from app.voice.service import transcribe_audio
    monkeypatch.setattr(httpx,'post', lambda *args,**kwargs: httpx.Response(200, request=httpx.Request('POST','http://speech/transcribe'),json={'text':'Встреча','engine':'GigaAM v3','seconds':0.5,'warning':''}))
    assert transcribe_audio(b'audio')['engine']=='GigaAM v3'

def test_gigaam_failure_uses_local_fallback(monkeypatch):
    import httpx
    from app.voice.service import transcribe_audio
    def offline(*args,**kwargs):
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(httpx,'post',offline)
    monkeypatch.setattr('app.voice.service.whisper_transcribe',lambda data:{'text':'Встреча','engine':'Whisper Small','warning':'Запасной движок'})
    assert transcribe_audio(b'audio')['engine']=='Whisper Small'
