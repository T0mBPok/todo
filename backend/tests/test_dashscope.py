import httpx
import pytest
from fastapi import HTTPException
from app.core import config
from app.core.ai_client import ai_post


@pytest.fixture
def official(monkeypatch):
    for key, value in {
        'AI_PROVIDER': 'dashscope', 'DASHSCOPE_API_KEY': 'test-official-key',
        'DASHSCOPE_MODEL': 'qwen-plus',
        'DASHSCOPE_BASE_URL': 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1',
        'OPENROUTER_API_KEY': 'test-other-key',
    }.items():
        monkeypatch.setattr(config, key, value)


def test_official_qwen_uses_dashscope_and_preserves_response_contract(official, monkeypatch):
    def post(url, **kwargs):
        assert url == 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions'
        assert kwargs['headers']['Authorization'] == 'Bearer test-official-key'
        body = kwargs['json']
        assert body['model'] == 'qwen-plus'
        assert body['response_format'] == {'type': 'json_object'}
        assert 'JSON Schema' in body['messages'][0]['content']
        assert body['enable_thinking'] is False and 'provider' not in body
        return httpx.Response(200, json={'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}]})
    monkeypatch.setattr(httpx, 'post', post)
    result = ai_post('unused', timeout=2, json={'messages': [{'role': 'user', 'content': 'Тест'}]}).json()
    assert result == {'message': {'content': '{}'}, 'done_reason': 'stop'}
    assert config.ai_model() == 'qwen-plus'


def test_official_key_cannot_be_sent_to_other_host(official, monkeypatch):
    monkeypatch.setattr(config, 'DASHSCOPE_BASE_URL', 'https://unrelated.example/compatible-mode/v1')
    monkeypatch.setattr(httpx, 'post', lambda *a, **k: pytest.fail('Unexpected network request'))
    with pytest.raises(HTTPException) as error:
        ai_post('unused', timeout=2, json={'messages': []})
    assert error.value.status_code == 503


def test_exhausted_free_quota_has_clear_error_and_no_retry(official, monkeypatch):
    calls = []
    def post(*args, **kwargs):
        calls.append(1)
        return httpx.Response(403, json={'error': {'code': 'AllocationQuota.FreeTierOnly'}})
    monkeypatch.setattr(httpx, 'post', post)
    with pytest.raises(HTTPException, match='Бесплатная квота'):
        ai_post('unused', timeout=2, json={'messages': []})
    assert calls == [1]
