"""GigaChat authentication and HTTPS transport."""
from base64 import b64decode
from binascii import Error as Base64Error
import json
import ssl
from functools import lru_cache
from pathlib import Path
from threading import Lock
from time import monotonic, perf_counter, time
from uuid import uuid4

import httpx
from fastapi import HTTPException

from app.core import config
from app.core.request_logging import log_dependency

TOKEN_URL = 'https://ngw.devices.sberbank.ru:9443/api/v2/oauth'
CHAT_URL = 'https://api.giga.chat/v1/chat/completions'
CA_BUNDLE = Path(__file__).with_name('gigachat_root_ca.pem')
_token_lock = Lock()
_token = ''
_expires = 0.0


@lru_cache(maxsize=1)
def tls_context():
    return ssl.create_default_context(cafile=str(CA_BUNDLE))


def authorization_key():
    key = config.GIGACHAT_AUTH_KEY
    try:
        decoded = b64decode(key, validate=True)
        client_id, separator, secret = decoded.partition(b':')
        if client_id and separator and secret:
            return key
    except (Base64Error, ValueError):
        pass
    raise HTTPException(503, 'В GIGACHAT_AUTH_KEY нужен Authorization Key из настроек API GigaChat (Base64 от Client ID:Client Secret).')


def access_token(client, rejected_token=None):
    global _token, _expires
    with _token_lock:
        if _token and _token != rejected_token and time() + 30 < _expires:
            return _token
        started = perf_counter()
        response = client.post(
            TOKEN_URL,
            headers={'Authorization': 'Basic ' + authorization_key(), 'RqUID': str(uuid4())},
            data={'scope': 'GIGACHAT_API_PERS'},
            timeout=httpx.Timeout(8, connect=4),
        )
        log_dependency('gigachat', 'oauth', started, response.status_code,
                       'http_error' if response.is_error else 'ok')
        if response.status_code in (400, 401, 403):
            raise HTTPException(503, 'GigaChat отклонил ключ авторизации. Проверьте GIGACHAT_AUTH_KEY.')
        if response.status_code == 429:
            raise HTTPException(429, 'Достигнут лимит авторизации GigaChat. Попробуйте позже.')
        if response.is_error:
            raise HTTPException(502, 'Не удалось получить токен GigaChat. Попробуйте позже.')
        data = response.json()
        token = data['access_token']
        expires = float(data['expires_at'])
        # The API can express the expiration as Unix seconds or milliseconds.
        if expires > 10**11:
            expires /= 1000
        if not isinstance(token, str) or not token or not time() < expires <= time() + 3600:
            raise ValueError('Invalid GigaChat token response')
        _token, _expires = token, expires
        return token


def retryable_completion(response):
    if not response.is_success:
        return False
    choices = response.json().get('choices')
    if not choices:
        return True
    choice = choices[0]
    content = choice.get('message', {}).get('content')
    if choice.get('finish_reason', 'stop') != 'stop':
        return False
    if not isinstance(content, str) or not content.strip():
        return True
    try:
        json.loads(content, strict=False)
    except json.JSONDecodeError:
        return True
    return False


def post(payload, timeout):
    with httpx.Client(verify=tls_context(), trust_env=False, timeout=timeout) as client:
        token = access_token(client)
        started = monotonic()
        response = client.post(CHAT_URL, headers={'Authorization': 'Bearer ' + token}, json=payload)
        if response.status_code == 401:
            token = access_token(client, rejected_token=token)
            started = monotonic()
            response = client.post(CHAT_URL, headers={'Authorization': 'Bearer ' + token}, json=payload)
        remaining = timeout.read - (monotonic() - started)
        if remaining > 1 and retryable_completion(response):
            log_dependency('gigachat', 'completion_retry', started, response.status_code, 'invalid_completion')
            response = client.post(
                CHAT_URL, headers={'Authorization': 'Bearer ' + token}, json=payload,
                timeout=httpx.Timeout(remaining, connect=min(remaining, timeout.connect)),
            )
        return response
