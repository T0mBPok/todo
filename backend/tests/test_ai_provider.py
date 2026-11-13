import httpx
import pytest
from fastapi import HTTPException
from app.core import config
from app.core.ai_client import ai_post

PAYLOAD={'model':'qwen-local','format':{'type':'object','properties':{'ok':{'type':'boolean'}}},'options':{'num_predict':200},'messages':[{'role':'user','content':'Тест'}]}

def test_local_provider_never_sends_cloud_key(monkeypatch):
    monkeypatch.setattr(config,'AI_PROVIDER','ollama');monkeypatch.setattr(config,'OPENROUTER_API_KEY','secret-test')
    captured={}
    response = httpx.Response(200)
    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return response
    monkeypatch.setattr(httpx,'post',post)
    assert ai_post('http://ollama:11434/api/chat',timeout=10,json=PAYLOAD) is response
    assert captured['url']=='http://ollama:11434/api/chat' and 'headers' not in captured and captured['json']==PAYLOAD

def remote(monkeypatch):
    monkeypatch.setattr(config,'AI_PROVIDER','openrouter');monkeypatch.setattr(config,'OPENROUTER_API_KEY','secret-test');monkeypatch.setattr(config,'OPENROUTER_MODEL','qwen/test:free');monkeypatch.setattr(config,'OPENROUTER_RESPONSE_FORMAT','json_object')

def test_remote_adapter_schema_and_length(monkeypatch):
    remote(monkeypatch);captured={}
    def post(url,**kwargs):
        captured.update(url=url,**kwargs)
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"ok":true}'},'finish_reason':'length'}]})
    monkeypatch.setattr(httpx,'post',post)
    result=ai_post('http://ollama/api/chat',timeout=10,json=PAYLOAD).json()
    assert result['message']['content']=='{"ok":true}' and result['done_reason']=='length'
    assert captured['url']=='https://openrouter.ai/api/v1/chat/completions'
    assert captured['headers']['Authorization']=='Bearer secret-test'
    assert captured['json']['model']=='qwen/test:free' and captured['json']['max_tokens']==200
    assert captured['json']['response_format']=={'type':'json_object'}
    assert 'JSON Schema' in captured['json']['messages'][0]['content']
    assert len(PAYLOAD['messages'])==1
    assert 'options' not in captured['json'] and 'keep_alive' not in captured['json']

@pytest.mark.parametrize('status,expected',[(401,503),(402,503),(429,429),(500,502)])
def test_remote_error_is_sanitized_without_retry(monkeypatch,status,expected):
    remote(monkeypatch);calls=[]
    def post(*args,**kwargs):calls.append(1);return httpx.Response(status,text='secret-test upstream private data')
    monkeypatch.setattr(httpx,'post',post)
    with pytest.raises(HTTPException) as error:ai_post('unused',timeout=10,json=PAYLOAD)
    assert error.value.status_code==expected and 'secret-test' not in error.value.detail
    assert len(calls)==1

def test_missing_key_does_not_call_any_provider(monkeypatch):
    remote(monkeypatch);monkeypatch.setattr(config,'OPENROUTER_API_KEY','')
    monkeypatch.setattr(httpx,'post',lambda *a,**k:pytest.fail('Unexpected network request'))
    with pytest.raises(HTTPException) as error:ai_post('unused',timeout=10,json=PAYLOAD)
    assert error.value.status_code==503

def test_strict_schema_is_opt_in(monkeypatch):
    remote(monkeypatch);monkeypatch.setattr(config,'OPENROUTER_RESPONSE_FORMAT','json_schema')
    def post(url,**kwargs):
        assert kwargs['json']['response_format']['json_schema']['schema']==PAYLOAD['format']
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"ok":true}'}}]})
    monkeypatch.setattr(httpx,'post',post)
    assert ai_post('unused',timeout=10,json=PAYLOAD).json()['done_reason']=='stop'

def test_remote_health_does_not_spend_quota(monkeypatch):
    remote(monkeypatch)
    monkeypatch.setattr(httpx,'get',lambda *a,**k:pytest.fail('Unexpected remote health request'))
    from app.plans.ai import model_status
    assert model_status() is True
