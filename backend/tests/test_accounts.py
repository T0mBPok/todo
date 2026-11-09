from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core import config
from app.core.database import SessionLocal
from app.main import app
from app.users.models import User


from email_helpers import capture_mail, register_verified


def test_sessions_and_cross_account_access(monkeypatch):
    inbox = capture_mail(monkeypatch)
    emails = [f'{uuid4().hex}@example.com' for _ in range(2)]
    password = 'long-account-test-password'
    headers = {'Origin': config.PUBLIC_ORIGIN}
    try:
        with TestClient(app, base_url=config.PUBLIC_ORIGIN, headers=headers) as alice, TestClient(
                app, base_url=config.PUBLIC_ORIGIN, headers=headers) as bob:
            assert alice.get('/api/tasks').status_code == 401
            assert alice.get('/api/todos').status_code == 401
            assert alice.get('/api/google/status').status_code == 401
            assert alice.post('/api/auth/register', headers={'Origin': 'https://unrelated.example'},
                              json={'email': emails[0], 'password': password}).status_code == 403
            for client, email in zip((alice, bob), emails):
                registration = register_verified(client, email, password, inbox)
                assert registration.status_code == 200, registration.text
                assert 'HttpOnly' in registration.headers['set-cookie']
                assert client.get('/api/auth/me').json() == {'email': email}
            payload = {'title': 'private event', 'start': '2098-11-12T10:00:00+07:00',
                       'end': '2098-11-12T11:00:00+07:00'}
            event = alice.post('/api/tasks', json=payload)
            assert event.status_code == 201, event.text
            assert bob.post('/api/tasks', json=payload).status_code == 201
            todo = alice.post('/api/todos', json={'title': 'private todo'})
            assert todo.status_code == 201, todo.text
            assert bob.get('/api/todos').json() == []
            assert bob.delete('/api/todos/' + todo.json()['id']).status_code == 404
            assert bob.delete('/api/tasks/' + event.json()['id']).status_code == 404
            assert all(item['id'] != event.json()['id'] for item in bob.get('/api/tasks').json())
            old_cookie = dict(alice.cookies.items())
            assert alice.post('/api/auth/logout').status_code == 204
            alice.cookies.update(old_cookie)
            assert alice.get('/api/tasks').status_code == 401
            assert alice.post('/api/auth/login', json={'email': emails[0], 'password': password}).status_code == 200
            assert alice.get('/api/todos').json()[0]['id'] == todo.json()['id']
    finally:
        with SessionLocal.begin() as db:
            db.execute(delete(User).where(User.email.in_(emails)))
