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


def mcp_configured():
    return bool(config.GOOGLE_TASKS_MCP_CLIENT_ID and config.GOOGLE_TASKS_MCP_CLIENT_SECRET)


def credentials(provider):
    if provider == 'tasks_mcp':
        if not mcp_configured():
            raise HTTPException(503, 'Администратор ещё не настроил Google Tasks MCP.')
        return config.GOOGLE_TASKS_MCP_CLIENT_ID, config.GOOGLE_TASKS_MCP_CLIENT_SECRET
    return config.GOOGLE_CLIENT_ID, config.GOOGLE_CLIENT_SECRET


def begin(db, request, provider='google'):
    cipher()
    client_id, _ = credentials(provider)
    if provider == 'tasks_mcp' and db.scalar(select(GoogleConnection)) is None:
        raise HTTPException(409, 'Сначала подключите основной аккаунт Google.')
    owner = request.state.user_id
    throttle('google-connect', str(owner), 8, 900)
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    values = dict(owner_id=owner, state=digest(state), session_digest=digest(request.cookies[COOKIE]),
                  verifier=verifier, provider=provider, expires=datetime.now(timezone.utc) + timedelta(minutes=10))
    stmt = insert(GoogleState).values(**values)
    db.execute(stmt.on_conflict_do_update(index_elements=[GoogleState.owner_id],
                                         set_={k: v for k, v in values.items() if k != 'owner_id'}))
    db.commit()
    return 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
        'client_id': client_id, 'redirect_uri': callback_url(),
        'response_type': 'code', 'scope': ' '.join(SCOPES if provider == 'google' else (SCOPES[0], SCOPES[2])), 'state': state,
        'access_type': 'offline', 'prompt': 'consent select_account',
        'code_challenge': challenge, 'code_challenge_method': 'S256',
    })


def token(client, provider='google', **fields):
    client_id, client_secret = credentials(provider)
    try:
        response = client.post(TOKEN_URL, data={
            'client_id': client_id, 'client_secret': client_secret, **fields})
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
    provider = pending.provider
    db.delete(pending)
    db.commit()
    with httpx.Client(timeout=8) as client:
        result = token(client, provider=provider, code=code, code_verifier=verifier, redirect_uri=callback_url(), grant_type='authorization_code')
        refresh = result.get('refresh_token')
        required = SCOPES[1:] if provider == 'google' else (SCOPES[2],)
        if not refresh or not set(required).issubset(result.get('scope', '').split()):
            raise HTTPException(400, 'Разрешите доступ к событиям и списку дел в Google.')
        try:
            info = client.get(USERINFO_URL, headers={'Authorization': 'Bearer ' + result['access_token']})
            info.raise_for_status()
            subject = info.json()['sub']
            if not isinstance(subject, str) or not 0 < len(subject) <= 255:
                raise ValueError
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise HTTPException(502, 'Не удалось проверить аккаунт Google.') from None
        connection = db.scalar(select(GoogleConnection).with_for_update())
        if provider == 'tasks_mcp':
            if connection is None or connection.subject != subject:
                raise HTTPException(400, 'Выберите тот же аккаунт Google, который подключён к Импульсу.')
            from app.google_sync.tasks_mcp import call
            client.headers['Authorization'] = 'Bearer ' + result['access_token']
            call(client, 'list_tasks', {'pageSize': 1, 'filter': {'state': 'ALL'}})
            connection.mcp_refresh_token = encryption.encrypt(refresh.encode()).decode()
            connection.next_sync_at = datetime.now(timezone.utc)
            connection.sync_error = None
            db.commit()
            return
        if connection is not None and connection.subject != subject:
            connection.mcp_refresh_token = None
            connection.mcp_migrated = False
    stmt = insert(GoogleConnection).values(owner_id=request.state.user_id, subject=subject,
                                          refresh_token=encryption.encrypt(refresh.encode()).decode(), sync_enabled=True, next_sync_at=datetime.now(timezone.utc))
    db.execute(stmt.on_conflict_do_update(index_elements=[GoogleConnection.owner_id],
                                          set_={'subject': stmt.excluded.subject, 'refresh_token': stmt.excluded.refresh_token, 'sync_enabled': True, 'next_sync_at': datetime.now(timezone.utc), 'sync_error': None}))
    db.commit()


def refresh_access(client, connection, provider='google'):
    try:
        stored = connection.mcp_refresh_token if provider == 'tasks_mcp' else connection.refresh_token
        if not stored:
            raise HTTPException(409, 'Подключите Google Tasks MCP.')
        refresh = cipher().decrypt(stored.encode()).decode()
    except InvalidToken:
        raise HTTPException(503, 'Подключите аккаунт Google заново.') from None
    return token(client, provider=provider, refresh_token=refresh, grant_type='refresh_token')['access_token']
