import json
from datetime import timedelta
import httpx
import pytest
from pydantic import ValidationError
from test_api import client
from app.plans.ai import parse_plan
from test_mixed_numeric_calendar import seed_numeric

SOURCE='Удали с среды повторяющееся событие 1С. Добавь на завтра, 25-го, на 13:15 ТПО.'
pytestmark=pytest.mark.usefixtures('november24_clock')

def model_plan(end):
    task={'title':'ТПО','start':'2026-11-25T13:15:00+07:00'}
    if end is not None:task['end']=end
    return {'tasks':[task],'note':'','needs_clarification':False}

@pytest.mark.parametrize('end',[None,'2026-11-25T13:15:00+07:00',
                                '2026-11-25T12:15:00+07:00','broken',
                                '2026-11-25T13:15:00', '2026-11-26T13:15:00+07:00'])
def test_default_end_is_applied_before_interval_validation(end):
    plan=parse_plan(json.dumps(model_plan(end)), 'Добавь на завтра, 25-го, на 13:15 ТПО.', 'Asia/Tomsk')
    assert plan.tasks[0].end-plan.tasks[0].start==timedelta(hours=1)

@pytest.mark.parametrize('source',['Добавь завтра ТПО на два часа.',
                                 'Добавь завтра ТПО с 13:15 до 14:15.',
                                 'Добавь завтра ТПО на полчаса.'])
def test_explicit_duration_does_not_silently_use_default(source):
    with pytest.raises(ValidationError):
        parse_plan(json.dumps(model_plan('2026-11-25T13:15:00+07:00')),source,'Asia/Tomsk')

def test_original_duration_is_kept_even_if_normalized_text_omits_it():
    with pytest.raises(ValidationError):
        parse_plan(json.dumps(model_plan(None)),'Добавь завтра ТПО в 13:15.','Asia/Tomsk',
                   duration_source='Добавь завтра ТПО в 13:15 на два часа.')

@pytest.mark.parametrize('start',[None,'broken','2026-11-25T13:15:00'])
def test_spoken_date_clock_and_timezone_repair_missing_model_timestamp(start):
    content=model_plan(None)
    content['tasks'][0]['start']=start
    plan=parse_plan(json.dumps(content),'Добавь на завтра, 25-го, на 13:15 ТПО.','Asia/Tomsk')
    assert plan.tasks[0].start.isoformat()=='2026-11-25T06:15:00+00:00'
    assert plan.tasks[0].end.isoformat()=='2026-11-25T07:15:00+00:00'

@pytest.mark.parametrize('end',[None,'2026-11-25T13:15:00+07:00','2026-11-25T12:15:00+07:00'])
def test_exact_screenshot_prepares_and_executes_with_both_selected(client,monkeypatch,end):
    api,session=client
    from app.core import config
    monkeypatch.setattr(config,'AI_PROVIDER','gigachat')
    seed_numeric(api)
    monkeypatch.setattr('app.plans.ai.AIPlanner.normalize',lambda self,text:(text,''))
    def manage(url,**kwargs):
        payload=json.loads(kwargs['json']['messages'][1]['content'])
        assert payload['request']=='Удали с среды повторяющееся событие 1С'
        refs=[event['ref'] for event in payload['calendar']['events']]
        value={'intent':'manage','note':'','operations':[{'action':'delete','refs':refs}]}
        return httpx.Response(200,request=httpx.Request('POST',url),json={'message':{'content':json.dumps(value)}})
    def create(url,**kwargs):
        assert 'Добавь на завтра, 25-го, на 13:15 ТПО.' in kwargs['json']['messages'][1]['content']
        return httpx.Response(200,request=httpx.Request('POST',url),json={'message':{'content':json.dumps(model_plan(end))}})
    monkeypatch.setattr('app.commands.grounded_ai.ai_post',manage)
    monkeypatch.setattr('app.plans.ai.ai_post',create)
    result=api.post('/api/commands',json={'text':SOURCE,'timezone':'Asia/Tomsk'})
    assert result.status_code==200,result.text
    command=result.json()
    assert len(command['operations'])==2
    assert len(command['operations'][0]['candidates'])==2
    added=command['operations'][1]['candidates'][0]
    assert added['title']=='ТПО' and added['start']=='2026-11-25T06:15:00Z'
    assert added['end']=='2026-11-25T07:15:00Z'
    result=api.post('/api/commands/'+command['id']+'/execute',json={'choices':[
        {'candidate':None,'candidates':[0,1],'scope':'future'},{'candidate':0}]})
    assert result.status_code==200,result.text
    assert result.json()['tasks'][0]['title']=='ТПО'
