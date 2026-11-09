from uuid import uuid4

from app.core import config
from app.users import email_verification, router


def capture_mail(monkeypatch):
    inbox = {}
    monkeypatch.setattr(config, 'EMAIL_CODE_KEY', 'a' * 64)
    monkeypatch.setattr(email_verification, 'send_code', lambda address, code: inbox.update({address: code}))
    test_ip = str(uuid4())
    monkeypatch.setattr(router, 'client_ip', lambda _: test_ip)
    return inbox


def register_verified(client, email, password, inbox):
    pending = client.post('/api/auth/register', json={'email': email, 'password': password})
    assert pending.status_code == 202, pending.text
    return client.post('/api/auth/verify-email', json={'challenge': pending.json()['challenge'], 'code': inbox[email]})
