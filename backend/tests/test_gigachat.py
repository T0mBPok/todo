import json
from time import time

import httpx
import pytest
from fastapi import HTTPException

from app.core import config, gigachat
from app.core.ai_client import ai_post
from app.plans.ai import model_status


def test_gigachat_schema_prompt_and_token_refresh(monkeypatch):
    monkeypatch.setattr(config, 'AI_PROVIDER', 'gigachat')
    monkeypatch.setattr(config, 'GIGACHAT_AUTH_KEY', 'Y2xpZW50OnNlY3JldA==')
    monkeypatch.setattr(gigachat, '_token', '')
    monkeypatch.setattr(gigachat, '_expires', 0)
    calls = []
    schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok']}

    def endpoint(request):
        calls.append(str(request.url))
        if str(request.url) == gigachat.TOKEN_URL:
            assert request.headers['Authorization'] == 'Basic Y2xpZW50OnNlY3JldA=='
            assert request.headers['RqUID']
            assert request.content == b'scope=GIGACHAT_API_PERS'
            token = str(calls.count(gigachat.TOKEN_URL))
            return httpx.Response(200, json={'access_token': token, 'expires_at': int((time() + 1800) * 1000)})
        assert str(request.url) == gigachat.CHAT_URL
        payload = json.loads(request.content)
        assert payload['model'] == config.GIGACHAT_MODEL
        assert json.loads(payload['messages'][0]['content'].splitlines()[0].split(': ', 1)[1]) == schema
        assert payload['messages'][0]['role'] == 'system'
        assert 'provider' not in payload and 'response_format' not in payload
        if request.headers['Authorization'] == 'Bearer 1':
            return httpx.Response(401)
        assert request.headers['Authorization'] == 'Bearer 2'
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}]})

    real_client = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(endpoint), **kwargs))
    assert model_status()
    assert not calls
    payload = {'format': schema, 'messages': [{'role': 'user', 'content': 'Test'}]}
    for _ in range(2):
        result = ai_post('unused', timeout=20, json=payload)
        assert result.json() == {'message': {'content': '{"ok":true}'}, 'done_reason': 'stop'}
    assert calls == [gigachat.TOKEN_URL, gigachat.CHAT_URL, gigachat.TOKEN_URL, gigachat.CHAT_URL, gigachat.CHAT_URL]


def test_gigachat_explains_uuid_is_not_authorization_key(monkeypatch):
    monkeypatch.setattr(config, 'GIGACHAT_AUTH_KEY', '12345678-1234-1234-1234-123456789abc')
    with pytest.raises(HTTPException, match='Authorization Key'):
        gigachat.authorization_key()


@pytest.mark.parametrize('reason, calls', [('stop', 2), ('blacklist', 1)])
def test_gigachat_retries_only_empty_completion(monkeypatch, reason, calls):
    monkeypatch.setattr(config, 'AI_PROVIDER', 'gigachat')
    monkeypatch.setattr(config, 'GIGACHAT_AUTH_KEY', 'Y2xpZW50OnNlY3JldA==')
    monkeypatch.setattr(gigachat, '_token', 'cached')
    monkeypatch.setattr(gigachat, '_expires', time() + 600)
    requests = []

    def endpoint(request):
        assert str(request.url) == gigachat.CHAT_URL
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, json={'choices': [{'message': {'content': ''}, 'finish_reason': reason}]})
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"description":"Milk\nBread"}'}}]})

    real_client = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(endpoint), **kwargs))
    payload = {'format': {}, 'messages': [{'role': 'user', 'content': 'Test'}]}
    if reason == 'blacklist':
        with pytest.raises(HTTPException) as error:
            ai_post('unused', timeout=15, json=payload)
        assert error.value.status_code == 422
    else:
        content = ai_post('unused', timeout=15, json=payload).json()['message']['content']
        assert json.loads(content) == {'description': 'Milk\nBread'}
    assert len(requests) == calls
