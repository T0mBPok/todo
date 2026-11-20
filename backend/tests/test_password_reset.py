from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core import config
from app.core.database import SessionLocal
from app.main import app
from app.users.models import EmailChallenge, User
from app.users.router import digest
from email_helpers import capture_mail, register_verified


def test_password_reset_code_is_one_time_and_revokes_sessions(monkeypatch):
    inbox = capture_mail(monkeypatch)
    email = f'{uuid4().hex}@example.com'
    password = 'original-account-password'
    replacement = 'replacement-account-password'
    options = {'base_url': config.PUBLIC_ORIGIN, 'headers': {'Origin': config.PUBLIC_ORIGIN}}
    try:
        with TestClient(app, **options) as logged_in, TestClient(app, **options) as recovery:
            assert register_verified(logged_in, email, password, inbox).status_code == 200
            pending = recovery.post('/api/auth/request-password-reset', json={'email': email.upper()})
            assert pending.status_code == 202, pending.text
            challenge = {'challenge': pending.json()['challenge']}
            code = inbox[email]
            assert recovery.post('/api/auth/verify-email', json={**challenge, 'code': code}).status_code == 410
            assert recovery.post('/api/auth/resend-email', json=challenge).status_code == 410
            assert recovery.post('/api/auth/resend-password-reset', json=challenge).status_code == 429

            wrong = '00000000' if code != '00000000' else '11111111'
            for _ in range(5):
                assert recovery.post('/api/auth/reset-password', json={
                    **challenge, 'code': wrong, 'password': replacement,
                }).status_code == 422
            assert recovery.post('/api/auth/reset-password', json={
                **challenge, 'code': code, 'password': replacement,
            }).status_code == 422

            with SessionLocal.begin() as db:
                row = db.get(EmailChallenge, digest(challenge['challenge']))
                assert row.purpose == 'password_reset' and row.attempts_left == 0
                row.resend_after = datetime.now(timezone.utc) - timedelta(seconds=1)
            assert recovery.post('/api/auth/resend-password-reset', json=challenge).status_code == 204
            payload = {**challenge, 'code': inbox[email], 'password': replacement}
            assert recovery.post('/api/auth/reset-password', json=payload).status_code == 204
            assert recovery.get('/api/auth/me').status_code == 401
            assert logged_in.get('/api/auth/me').status_code == 401
            assert recovery.post('/api/auth/reset-password', json=payload).status_code == 410
            assert recovery.post('/api/auth/login', json={'email': email, 'password': password}).status_code == 401
            assert recovery.post('/api/auth/login', json={'email': email, 'password': replacement}).status_code == 200
    finally:
        with SessionLocal.begin() as db:
            db.execute(delete(EmailChallenge).where(EmailChallenge.email == email))
            db.execute(delete(User).where(User.email == email))


def test_registration_code_cannot_reset_password_and_unknown_email_is_generic(monkeypatch):
    inbox = capture_mail(monkeypatch)
    email = f'{uuid4().hex}@example.com'
    options = {'base_url': config.PUBLIC_ORIGIN, 'headers': {'Origin': config.PUBLIC_ORIGIN}}
    unknown = f'{uuid4().hex}@example.com'
    try:
        with TestClient(app, **options) as api:
            registration = api.post('/api/auth/register', json={'email': email, 'password': 'new-account-password'}).json()
            assert api.post('/api/auth/reset-password', json={
                'challenge': registration['challenge'], 'code': inbox[email], 'password': 'replacement-password',
            }).status_code == 410
            assert api.post('/api/auth/verify-email', json={
                'challenge': registration['challenge'], 'code': inbox[email],
            }).status_code == 200
            pending = api.post('/api/auth/request-password-reset', json={'email': email}).json()
            with SessionLocal.begin() as db:
                db.get(EmailChallenge, digest(pending['challenge'])).code_expires = datetime.now(timezone.utc) - timedelta(seconds=1)
            assert api.post('/api/auth/reset-password', json={
                'challenge': pending['challenge'], 'code': inbox[email], 'password': 'replacement-password',
            }).status_code == 422

            result = api.post('/api/auth/request-password-reset', json={'email': unknown})
            assert result.status_code == 202
            assert set(result.json()) == {'email', 'challenge'}
            assert len(result.json()['challenge']) == len(pending['challenge'])
            assert unknown not in inbox
            assert api.post('/api/auth/resend-password-reset', json={'challenge': result.json()['challenge']}).status_code == 429
            assert api.post('/api/auth/verify-email', json={'challenge': result.json()['challenge'], 'code': '00000000'}).status_code == 410
    finally:
        with SessionLocal.begin() as db:
            db.execute(delete(EmailChallenge).where(EmailChallenge.email.in_([email, unknown])))
            db.execute(delete(User).where(User.email == email))
