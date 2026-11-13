import re

import httpx

from app.core import config, gigachat
from test_api import client


def test_request_id_matches_safe_provider_diagnostics(client, monkeypatch, caplog):
    api, _ = client
    monkeypatch.setattr(config, 'AI_PROVIDER', 'gigachat')
    monkeypatch.setattr(config, 'GIGACHAT_AUTH_KEY', 'example-secret')
    monkeypatch.setattr(gigachat, 'post', lambda *args: httpx.Response(429, text='upstream-private-data'))
    with caplog.at_level('INFO', logger='uvicorn.error'):
        response = api.post('/api/commands?diagnostic=private-query', json={
            'text': 'Поставь на пятницу созвон по закрытому проекту в 8 утра',
            'timezone': 'Asia/Tomsk',
        })
    assert response.status_code == 429
    identifier = response.headers['x-request-id']
    assert re.fullmatch('[a-f0-9]{32}', identifier)
    assert f'dependency request_id={identifier} service=gigachat operation=transcript_normalization status=429' in caplog.text
    assert f'request request_id={identifier} method=POST route=/api/commands status=429' in caplog.text
    assert not any(secret in caplog.text for secret in (
        'example-secret', 'upstream-private-data', 'private-query', 'закрытому проекту',
    ))
