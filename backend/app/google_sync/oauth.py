import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core import config
from app.google_sync.models import GoogleConnection, GoogleState
from app.users.router import COOKIE, digest, throttle

SCOPES = ('openid', 'https://www.googleapis.com/auth/calendar.events.owned',
          'https://www.googleapis.com/auth/tasks')
TOKEN_URL = 'https://oauth2.googleapis.com/token'
USERINFO_URL = 'https://openidconnect.googleapis.com/v1/userinfo'


def cipher():
    if not (config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET and config.GOOGLE_TOKEN_KEY):
        raise HTTPException(503, 'Администратор ещё не настроил Google OAuth.')
    try:
        return Fernet(config.GOOGLE_TOKEN_KEY)
    except ValueError:
        raise HTTPException(503, 'Неверная конфигурация ключа Google OAuth.') from None


def callback_url():
    return config.PUBLIC_ORIGIN + '/api/google/callback'


def begin(db, request):
    cipher()
    owner = request.state.user_id
    throttle('google-connect', str(owner), 8, 900)
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    values = dict(owner_id=owner, state=digest(state), session_digest=digest(request.cookies[COOKIE]),
                  verifier=verifier, expires=datetime.now(timezone.utc) + timedelta(minutes=10))
    stmt = insert(GoogleState).values(**values)
    db.execute(stmt.on_conflict_do_update(index_elements=[GoogleState.owner_id],
                                         set_={k: v for k, v in values.items() if k != 'owner_id'}))
    db.commit()
    return 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
        'client_id': config.GOOGLE_CLIENT_ID, 'redirect_uri': callback_url(),
        'response_type': 'code', 'scope': ' '.join(SCOPES), 'state': state,
        'access_type': 'offline', 'prompt': 'consent select_account',
        'code_challenge': challenge, 'code_challenge_method': 'S256',
    })


def token(client, **fields):
    try:
        response = client.post(TOKEN_URL, data={
            'client_id': config.GOOGLE_CLIENT_ID, 'client_secret': config.GOOGLE_CLIENT_SECRET, **fields})
        response.raise_for_status()
        result = response.json()
        if not isinstance(result.get('access_token'), str):
            raise ValueError
        return result
    except (httpx.HTTPError, ValueError, AttributeError):
        raise HTTPException(502, 'Google отклонил подключение. Подключите аккаунт заново.') from None


def complete(db, request, state, code):
    encryption = cipher()
    pending = db.scalar(select(GoogleState).with_for_update())
    if (not pending or pending.expires <= datetime.now(timezone.utc)
            or not secrets.compare_digest(pending.state, digest(state))
            or not secrets.compare_digest(pending.session_digest, digest(request.cookies[COOKIE]))):
        raise HTTPException(400, 'Ссылка Google истекла. Начните подключение заново.')
    verifier = pending.verifier
    db.delete(pending)
    db.commit()
    with httpx.Client(timeout=8) as client:
        result = token(client, code=code, code_verifier=verifier, redirect_uri=callback_url(), grant_type='authorization_code')
        refresh = result.get('refresh_token')
        if not refresh or not set(SCOPES[1:]).issubset(result.get('scope', '').split()):
            raise HTTPException(400, 'Разрешите доступ к событиям и списку дел в Google.')
        try:
            info = client.get(USERINFO_URL, headers={'Authorization': 'Bearer ' + result['access_token']})
            info.raise_for_status()
            subject = info.json()['sub']
            if not isinstance(subject, str) or not 0 < len(subject) <= 255:
                raise ValueError
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise HTTPException(502, 'Не удалось проверить аккаунт Google.') from None
    stmt = insert(GoogleConnection).values(owner_id=request.state.user_id, subject=subject,
                                          refresh_token=encryption.encrypt(refresh.encode()).decode())
    db.execute(stmt.on_conflict_do_update(index_elements=[GoogleConnection.owner_id],
                                          set_={'subject': stmt.excluded.subject, 'refresh_token': stmt.excluded.refresh_token}))
    db.commit()


def refresh_access(client, connection):
    try:
        refresh = cipher().decrypt(connection.refresh_token.encode()).decode()
    except InvalidToken:
        raise HTTPException(503, 'Подключите аккаунт Google заново.') from None
    return token(client, refresh_token=refresh, grant_type='refresh_token')['access_token']
