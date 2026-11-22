import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.commands import grounded_ai
from app.plans import ai
from test_api import client


def test_spoken_tomsk_range_survives_utc_model_error_and_auto_save(client, monkeypatch):
    api, _ = client
    zone = ZoneInfo('Asia/Tomsk')
    day = (datetime.now(zone).date() + timedelta(days=1)).isoformat()
    # Reproduce both failure modes: the first model call loses the explicit
    # interval, then the planner mistakes spoken wall time for UTC.
    def interpret(request, _context):
        assert request.text == 'Завтра тренировка с 18:00 до 19:00'
        return grounded_ai.Decision(intent='create', note='', create_text='Завтра тренировка')

    monkeypatch.setattr(grounded_ai, 'interpret_calendar', interpret)
    monkeypatch.setattr(ai.config, 'AI_PROVIDER', 'gigachat')
    model_plan = ai.ExtractedPlan(
        tasks=[{'title': 'Тренировка', 'start': day + 'T18:00:00Z', 'end': day + 'T19:00:00Z'}],
        note='', needs_clarification=False,
    )
    calls = []
    def model(url, **kwargs):
        payload = kwargs['json']
        calls.append(payload)
        if 'text' in payload['format'].get('properties', {}):
            assert '18:00 до 19:00' in payload['messages'][1]['content']
            content = '{"text":"Завтра тренировка с 18:00 до 19:00","note":""}'
        else:
            assert payload['messages'][1]['content'].startswith('Завтра тренировка с 18:00 до 19:00')
            content = model_plan.model_dump_json()
        return httpx.Response(200, request=httpx.Request('POST', url), json={'message': {'content': content}})

    monkeypatch.setattr(ai, 'ai_post', model)

    response = api.post('/api/commands', json={
        'text': 'Пожалуйста, поставь мне тонировку на завтра с 18:0 до 19:0.', 'timezone': 'Asia/Tomsk',
    })
    assert response.status_code == 200, response.text
    assert len(calls) == 2
    draft = response.json()['plan']
    saved = api.post(f"/api/plans/{draft['id']}/confirm", json={'tasks': draft['tasks']})
    assert saved.status_code == 200, saved.text
    events = api.get('/api/tasks').json()
    assert len(events) == 1
    assert datetime.fromisoformat(events[0]['start']).astimezone(zone).isoformat() == day + 'T18:00:00+07:00'
    assert datetime.fromisoformat(events[0]['end']).astimezone(zone).isoformat() == day + 'T19:00:00+07:00'


@pytest.mark.parametrize('transcript', [
    'Поставь мне на завтра с 18:00 до 1900 тренировку, а на пятницу на 08:00 утра созвон.',
    'Поставь тренировку завтра с 18:00 до 1900 и созвон в пятницу на 08:00 утра.',
])
def test_multi_event_voice_command_preserves_each_local_time(client, monkeypatch, transcript):
    api, _ = client
    zone = ZoneInfo('Asia/Tomsk')
    today = datetime.now(zone).date()
    tomorrow = today + timedelta(days=1)
    friday = today + timedelta(days=(4 - today.weekday()) % 7)
    normalized = transcript.replace('1900', '19:00')
    monkeypatch.setattr(ai.config, 'AI_PROVIDER', 'gigachat')

    def interpret(request, _context):
        assert request.text == normalized
        return grounded_ai.Decision(intent='create', note='', create_text='Добавь тренировку и созвон.')

    monkeypatch.setattr(grounded_ai, 'interpret_calendar', interpret)
    wrong_plan = ai.ExtractedPlan(
        # GigaChat returned local clock readings marked as UTC, in reverse order.
        tasks=[
            {'title': 'Созвон', 'start': f'{friday}T08:00:00Z', 'end': f'{friday}T09:00:00Z'},
            {'title': 'Тренировка', 'start': f'{tomorrow}T18:00:00Z', 'end': f'{tomorrow}T19:00:00Z'},
        ],
        note='', needs_clarification=False,
    )

    def model(url, **kwargs):
        payload = kwargs['json']
        if 'text' in payload['format'].get('properties', {}):
            assert payload['messages'][1]['content'] == normalized
            content = json.dumps({'text': normalized, 'note': ''})
        else:
            content = wrong_plan.model_dump_json()
        return httpx.Response(200, request=httpx.Request('POST', url), json={'message': {'content': content}})

    monkeypatch.setattr(ai, 'ai_post', model)
    response = api.post('/api/commands', json={'text': transcript, 'timezone': zone.key})
    assert response.status_code == 200, response.text
    draft = response.json()['plan']
    saved = api.post(f"/api/plans/{draft['id']}/confirm", json={'tasks': draft['tasks']})
    assert saved.status_code == 200, saved.text

    expected = {
        'Тренировка': (f'{tomorrow}T18:00:00+07:00', f'{tomorrow}T19:00:00+07:00'),
        'Созвон': (f'{friday}T08:00:00+07:00', f'{friday}T09:00:00+07:00'),
    }
    for events in (draft['tasks'], api.get('/api/tasks').json()):
        actual = {event['title']: tuple(datetime.fromisoformat(event[key]).astimezone(zone).isoformat()
                                       for key in ('start', 'end')) for event in events}
        assert actual == expected


@pytest.mark.parametrize('zone_name', ['Asia/Tomsk', 'Europe/Moscow'])
@pytest.mark.parametrize(('clock', 'expected'), [
    ('08:00 утра', '08:00'), ('08:00 вечера', '20:00'),
    ('12:00 дня', '12:00'), ('12:00 ночи', '00:00'),
    ('11:30 ночи', '23:30'), ('18:00', '18:00'),
])
def test_time_validation_preserves_daypart_instead_of_overriding_it(zone_name, clock, expected):
    from app.tasks.schemas import TaskInput
    from app.plans.dates import enforce_spoken_time
    task = TaskInput(title='Созвон', start='2026-11-23T08:00:00Z', end='2026-11-23T09:00:00Z')
    zone = ZoneInfo(zone_name)
    enforce_spoken_time([task], f'Созвон в {clock}.', zone_name)
    assert task.start.astimezone(zone).strftime('%H:%M') == expected
    assert task.end - task.start == timedelta(hours=1)


@pytest.mark.parametrize('zone_name', ['Asia/Tomsk', 'Europe/Moscow'])
def test_explicit_evening_range_survives_model_utc_error_through_save(client, monkeypatch, zone_name):
    api, _ = client
    zone = ZoneInfo(zone_name)
    day = (datetime.now(zone).date() + timedelta(days=1)).isoformat()
    text = 'Пожалуйста, завтра организуй созвон в 08:00 вечера.'
    monkeypatch.setattr(ai.config, 'AI_PROVIDER', 'gigachat')
    monkeypatch.setattr(grounded_ai, 'interpret_calendar', lambda *args: grounded_ai.Decision(
        intent='create', note='', create_text='Завтра созвон'))
    wrong = ai.ExtractedPlan(tasks=[{'title':'Созвон','start':day+'T20:00:00Z',
        'end':day+'T21:00:00Z'}],note='',needs_clarification=False)
    def model(url, **kwargs):
        payload=kwargs['json']
        content = json.dumps({'text':text,'note':''}) if 'text' in payload['format'].get('properties',{}) else wrong.model_dump_json()
        return httpx.Response(200,request=httpx.Request('POST',url),json={'message':{'content':content}})
    monkeypatch.setattr(ai,'ai_post',model)
    response=api.post('/api/commands',json={'text':text,'timezone':zone_name})
    assert response.status_code==200,response.text
    draft=response.json()['plan']
    response=api.post(f"/api/plans/{draft['id']}/confirm",json={'tasks':draft['tasks']})
    assert response.status_code==200,response.text
    event=api.get('/api/tasks').json()[0]
    assert datetime.fromisoformat(event['start']).astimezone(zone).isoformat() == f'{day}T20:00:00{datetime.now(zone).strftime("%z")[:3]}:00'
    assert datetime.fromisoformat(event['end']).astimezone(zone).strftime('%H:%M')=='21:00'


@pytest.mark.parametrize('zone_name', ['Asia/Tomsk','Asia/Novosibirsk','Europe/Moscow','Europe/Lisbon'])
@pytest.mark.parametrize('copies', [1,2,4])
def test_friday_series_keeps_eight_am_when_model_expands_utc_repetitions(client,monkeypatch,zone_name,copies):
    api,_=client
    zone=ZoneInfo(zone_name)
    today=datetime.now(zone).date()
    friday=today+timedelta(days=(4-today.weekday())%7 or 7)
    text='А-а каждую пятницу с 08:00 до 09:00 у меня тренировка в зале.'
    monkeypatch.setattr(ai.config,'AI_PROVIDER','gigachat')
    monkeypatch.setattr(grounded_ai,'interpret_calendar',lambda *args:grounded_ai.Decision(intent='create',note='',create_text=text))
    wrong=ai.ExtractedPlan(tasks=[{'title':'Тренировка в зале',
        'start':f'{friday+timedelta(days=i*7)}T08:00:00Z',
        'end':f'{friday+timedelta(days=i*7)}T09:00:00Z'} for i in range(copies)],note='',needs_clarification=False)
    def model(url,**kwargs):
        payload=kwargs['json']
        content=json.dumps({'text':text,'note':''}) if 'text' in payload['format'].get('properties',{}) else wrong.model_dump_json()
        return httpx.Response(200,request=httpx.Request('POST',url),json={'message':{'content':content}})
    monkeypatch.setattr(ai,'ai_post',model)
    response=api.post('/api/commands',json={'text':text,'timezone':zone_name})
    assert response.status_code==200,response.text
    draft=response.json()['plan']
    assert len(draft['tasks'])==1
    assert draft['review']==[]
    event=draft['tasks'][0]
    assert datetime.fromisoformat(event['start']).astimezone(zone).strftime('%H:%M')=='08:00'
    assert datetime.fromisoformat(event['end']).astimezone(zone).strftime('%H:%M')=='09:00'
    assert datetime.fromisoformat(event['start']).astimezone(zone).weekday()==4
    assert event['recurrence']['timezone']==zone_name
    saved=api.post(f"/api/plans/{draft['id']}/confirm",json={'tasks':draft['tasks']})
    assert saved.status_code==200,saved.text
    start=datetime.combine(friday,datetime.min.time(),zone)
    events=api.get('/api/tasks',params={'start':start.isoformat(),'end':(start+timedelta(days=21)).isoformat()}).json()
    assert len(events)==3
    for event in events:
        local=datetime.fromisoformat(event['start']).astimezone(zone)
        assert local.weekday()==4 and local.strftime('%H:%M')=='08:00'


def test_same_time_applies_to_every_explicit_weekday_after_recurrence_expansion(monkeypatch):
    from app.plans.schemas import PlanRequest
    zone=ZoneInfo('Asia/Tomsk')
    text='Каждую пятницу и воскресенье с 08:00 до 09:00 тренировка в зале.'
    monkeypatch.setattr(ai.AIPlanner,'normalize',lambda *args:(text,''))
    wrong=ai.ExtractedPlan(tasks=[{'title':'Тренировка в зале','start':'2026-11-27T08:00:00Z','end':'2026-11-27T09:00:00Z'}],note='',needs_clarification=False)
    monkeypatch.setattr(ai,'ai_post',lambda url,**kwargs:httpx.Response(200,request=httpx.Request('POST',url),json={'message':{'content':wrong.model_dump_json()}}))
    result=ai.AIPlanner().generate(PlanRequest(text=text,timezone=zone.key),[])
    assert len(result.tasks)==2
    assert {t.start.astimezone(zone).weekday() for t in result.tasks}=={4,6}
    assert all(t.start.astimezone(zone).strftime('%H:%M')=='08:00' for t in result.tasks)
    assert all(t.end.astimezone(zone).strftime('%H:%M')=='09:00' for t in result.tasks)
