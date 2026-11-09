from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core import config
from app.core.database import SessionLocal
from app.main import app
from app.users.models import EmailChallenge, LoginSession, User
from app.users.router import COOKIE, digest, passwords
from email_helpers import capture_mail


def test_registration_requires_one_time_code(monkeypatch):
    inbox = capture_mail(monkeypatch)
    email = f'{uuid4().hex}@example.com'
    options = {'base_url': config.PUBLIC_ORIGIN, 'headers': {'Origin': config.PUBLIC_ORIGIN}}
    try:
        with TestClient(app, **options) as client:
            pending = client.post('/api/auth/register', json={'email': email, 'password': 'long-test-password'}).json()
            challenge = {'challenge': pending['challenge']}
            assert COOKIE not in client.cookies
            assert client.get('/api/tasks').status_code == 401
            assert client.post('/api/auth/resend-email', json=challenge).status_code == 429
            code = inbox[email]
            wrong = '00000000' if code != '00000000' else '11111111'
            for _ in range(5):
                response = client.post('/api/auth/verify-email', json={**challenge, 'code': wrong})
                assert response.status_code == 422
            assert client.post('/api/auth/verify-email', json={**challenge, 'code': code}).status_code == 422
            with SessionLocal.begin() as db:
                row = db.get(EmailChallenge, digest(challenge['challenge']))
                assert row.attempts_left == 0
                assert row.code_hash != code
                assert db.scalar(select(User).where(User.email == email)) is None
                row.resend_after = datetime.now(timezone.utc) - timedelta(seconds=1)
            assert client.post('/api/auth/resend-email', json=challenge).status_code == 204
            latest = {**challenge, 'code': inbox[email]}
            assert client.post('/api/auth/verify-email', json=latest).status_code == 200
            assert client.get('/api/tasks').status_code == 200
            assert client.post('/api/auth/verify-email', json=latest).status_code == 410
    finally:
        with SessionLocal.begin() as db:
            db.execute(delete(EmailChallenge).where(EmailChallenge.email == email))
            db.execute(delete(User).where(User.email == email))


def test_existing_account_reauthenticates_without_reviving_old_cookies(monkeypatch):
    inbox = capture_mail(monkeypatch)
    email = f'{uuid4().hex}@example.com'
    password = 'legacy-test-password'
    old_token = 'A' * 43
    with SessionLocal.begin() as db:
        user = User(email=email, password_hash=passwords.hash(password))
        db.add(user)
        db.flush()
        db.add(LoginSession(digest=digest(old_token), user_id=user.id,
                            expires=datetime.now(timezone.utc) + timedelta(days=1)))
    options = {'base_url': config.PUBLIC_ORIGIN, 'headers': {'Origin': config.PUBLIC_ORIGIN}}
    try:
        with TestClient(app, **options) as client, TestClient(app, **options) as old:
            old.cookies.set(COOKIE, old_token)
            assert old.get('/api/tasks').status_code == 401
            pending = client.post('/api/auth/login', json={'email': email, 'password': password}).json()
            assert client.post('/api/auth/verify-email', json={'challenge': pending['challenge'], 'code': inbox[email]}).status_code == 200
            assert client.get('/api/tasks').status_code == 200
            assert old.get('/api/tasks').status_code == 401
    finally:
        with SessionLocal.begin() as db:
            db.execute(delete(User).where(User.email == email))
