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



def test_validation_diagnostics_report_fields_without_rejected_input(caplog):
    from app.core.request_logging import log_result_rejection,request_id
    from app.commands.grounded_ai import Decision
    from pydantic import ValidationError
    secret='sk-private-secret@example.com'
    token=request_id.set('diagnostic-test')
    try:
        with caplog.at_level('WARNING',logger='uvicorn.error'):
            try:
                Decision.model_validate({'intent':'manage','operations':[{'action':secret,'refs':['E1']}],
                    'new_events':[{'title':secret,'start':secret,'end':secret}], 'note':secret})
            except ValidationError as error:
                log_result_rejection('calendar_command','invalid_schema',error)
        assert 'operations[0].action' in caplog.text
        assert 'literal_error' in caplog.text
        assert 'new_events[0].start' in caplog.text
        assert 'schema_validation' in caplog.text
        assert 'diagnostic-test' in caplog.text
        assert secret not in caplog.text
    finally:request_id.reset(token)


def test_json_and_key_errors_never_log_private_body_or_key(caplog):
    import json
    from app.core.request_logging import log_result_rejection
    secret='private-calendar@example.com'
    with caplog.at_level('WARNING',logger='uvicorn.error'):
        try:json.loads('{"note":"'+secret+'",}')
        except json.JSONDecodeError as error:log_result_rejection('calendar_plan','invalid_schema',error)
        log_result_rejection('calendar_command','invalid_schema',KeyError(secret))
    assert 'json_decode' in caplog.text
    assert 'position' in caplog.text and 'response_chars' in caplog.text
    assert 'response_envelope' in caplog.text
    assert '<unknown_field>' in caplog.text
    assert secret not in caplog.text


def test_custom_validator_messages_and_unknown_field_names_are_hidden(caplog):
    from pydantic import BaseModel,ValidationError,model_validator
    from app.core.request_logging import log_result_rejection
    secret='private-api-key'
    class Payload(BaseModel):
        value: str
        @model_validator(mode='after')
        def validate(self):raise ValueError(self.value)
    try:Payload(value=secret)
    except ValidationError as error:
        with caplog.at_level('WARNING',logger='uvicorn.error'):
            log_result_rejection('calendar_plan','invalid_schema',error)
    assert 'value_error' in caplog.text
    assert secret not in caplog.text


def test_http_diagnostics_only_record_status(caplog):
    from app.core.request_logging import log_result_rejection
    secret='private-password'
    response=httpx.Response(500,request=httpx.Request('POST','https://example.com/'+secret),text=secret)
    try:response.raise_for_status()
    except httpx.HTTPStatusError as error:
        with caplog.at_level('WARNING',logger='uvicorn.error'):log_result_rejection('calendar_plan','invalid_schema',error)
    assert 'provider_http' in caplog.text and '500' in caplog.text
    assert secret not in caplog.text



def test_actual_command_rejection_logs_validation_path(monkeypatch,caplog):
    import json,pytest
    from fastapi import HTTPException
    from app.commands import grounded_ai
    from app.commands.schemas import CommandRequest
    secret='private-response-and-user-text'
    bad={'intent':'manage','note':secret,'operations':[{'action':secret,'refs':['E1']}],'new_events':[]}
    monkeypatch.setattr(grounded_ai,'ai_post',lambda url,**kwargs:httpx.Response(200,request=httpx.Request('POST',url),json={'message':{'content':json.dumps(bad)}}))
    with caplog.at_level('WARNING',logger='uvicorn.error'):
        with pytest.raises(HTTPException) as error:
            grounded_ai.interpret_calendar(CommandRequest(text=secret),{'events':[{'ref':'E1'}]})
    assert error.value.status_code==502
    assert 'operation=calendar_command' in caplog.text
    assert 'operations[0].action' in caplog.text
    assert 'literal_error' in caplog.text
    assert 'expected' in caplog.text and 'delete' in caplog.text
    assert secret not in caplog.text
