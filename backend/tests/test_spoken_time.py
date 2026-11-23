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


@pytest.mark.parametrize('transcript', [
    'В пятницу 27-го числа с 10:00 утра до 3 часов дня пары по ТСП.',
    'В пятницу 27-го числа, с 10:00 ут до 3 00 дня пары по ТСП.',
    'В пятницу 27-го числа, с 10 00 утра до 3 00 дня пары по ТСП.',
])
def test_declarative_new_event_bypasses_existing_event_selection(client, monkeypatch, transcript):
    api, _ = client
    monkeypatch.setattr(ai.config, 'AI_PROVIDER', 'gigachat')
    def reject_selection(*args):
        pytest.fail('New dated event must not select existing calendar refs')
    monkeypatch.setattr(grounded_ai, 'interpret_calendar', reject_selection)
    monkeypatch.setattr(ai.AIPlanner, 'normalize', lambda self, text: (text, ''))
    def model(url, **kwargs):
        content = ai.ExtractedPlan(tasks=[{'title': 'Пары по ТСП',
            'start': '2026-11-27T10:00:00Z', 'end': '2026-11-27T15:00:00Z'}],
            note='', needs_clarification=False).model_dump_json()
        return httpx.Response(200, request=httpx.Request('POST', url), json={'message': {'content': content}})
    monkeypatch.setattr(ai, 'ai_post', model)
    result = api.post('/api/commands', json={'text': transcript, 'timezone': 'Asia/Tomsk'})
    assert result.status_code == 200, result.text
    draft = result.json()['plan']
    assert len(draft['tasks']) == 1
    item = draft['tasks'][0]
    zone = ZoneInfo('Asia/Tomsk')
    assert datetime.fromisoformat(item['start']).astimezone(zone).isoformat() == '2026-11-27T10:00:00+07:00'
    assert datetime.fromisoformat(item['end']).astimezone(zone).isoformat() == '2026-11-27T15:00:00+07:00'
    confirmed = api.post(f"/api/plans/{draft['id']}/confirm", json={'tasks': draft['tasks']})
    assert confirmed.status_code == 200, confirmed.text


@pytest.mark.parametrize('text', [
    'В пятницу перенеси пары с 10 утра до 3 часов дня.',
    'В пятницу удали пары с 10 утра до 3 часов дня.',
    'В пятницу измени описание пары с 10 утра до 3 часов дня.',
    'В пятницу с 10 утра до 3 часов дня это событие.',
    'В пятницу с 10 утра до 3 часов дня пары?',
])
def test_management_and_questions_do_not_route_as_new_events(text):
    from app.commands.matching import declarative_calendar_add
    assert not declarative_calendar_add(text)


@pytest.mark.parametrize('zone_name',['Asia/Tomsk','Europe/Moscow','America/New_York'])
@pytest.mark.parametrize('source',[
 'В пятницу 27-го числа поставь работу с 08:00 до 09:00. Тренировку с 12:00ня до 13:00 дня и встречу с друзьями с 09:00 вечера до 11: вечера.',
 'В пятницу 27-го числа поставь работу с 08:00 до 09:00. Тренировку с 12:0ня до 13:00 дня и встречу с друзьями с 09:00вечера до 11:вечера.',
])
def test_three_events_with_corrupted_dayparts_keep_local_intervals(client,monkeypatch,zone_name,source):
    api,_=client
    monkeypatch.setattr(ai.config,'AI_PROVIDER','gigachat')
    monkeypatch.setattr(ai.AIPlanner,'normalize',lambda self,text:(text,''))
    monkeypatch.setattr(grounded_ai,'interpret_calendar',lambda *a:grounded_ai.Decision(intent='create',note=''))
    wrong=ai.ExtractedPlan(tasks=[
      {'title':'Встреча с друзьями','start':'2026-11-27T21:00:00Z','end':'2026-11-27T23:00:00Z'},
      {'title':'Работа','start':'2026-11-27T08:00:00Z','end':'2026-11-27T09:00:00Z'},
      {'title':'Тренировка','start':'2026-11-27T12:00:00Z','end':'2026-11-27T13:00:00Z'}],note='',needs_clarification=False)
    monkeypatch.setattr(ai,'ai_post',lambda url,**kw:httpx.Response(200,request=httpx.Request('POST',url),json={'message':{'content':wrong.model_dump_json()}}))
    response=api.post('/api/commands',json={'text':source,'timezone':zone_name})
    assert response.status_code==200,response.text
    draft=response.json()['plan']
    assert draft['review']==[]
    expected={'Работа':('08:00','09:00'),'Тренировка':('12:00','13:00'),'Встреча с друзьями':('21:00','23:00')}
    saved=api.post('/api/plans/'+draft['id']+'/confirm',json={'tasks':draft['tasks']})
    assert saved.status_code==200,saved.text
    for event in api.get('/api/tasks').json():
      local=[datetime.fromisoformat(event[key]).astimezone(ZoneInfo(zone_name)) for key in ('start','end')]
      assert tuple(t.strftime('%H:%M') for t in local)==expected[event['title']]
      assert all(t.date().isoformat()=='2026-11-27' for t in local)


def test_unparseable_explicit_clock_is_flagged_even_when_other_event_is_valid():
    from app.plans.dates import enforce_spoken_time
    from app.tasks.schemas import TaskInput
    tasks=[TaskInput(title='Работа',start='2026-11-27T08:00:00+07:00',end='2026-11-27T09:00:00+07:00'),
      TaskInput(title='Тренировка',start='2026-11-27T19:00:00+07:00',end='2026-11-27T20:00:00+07:00')]
    unresolved=enforce_spoken_time(tasks,'Работа с 08:00 до 09:00. Тренировка с 12:непонятно до 13:непонятно.','Asia/Tomsk')
    assert unresolved=={1}


@pytest.mark.parametrize('bad_field',['start','end'])
def test_malformed_model_datetime_recovers_only_from_explicit_spoken_interval(bad_field):
    content={'tasks':[{'title':'Тренировка','start':'2026-11-27T12:00:00Z','end':'2026-11-27T13:00:00Z'}], 'note':'','needs_clarification':False}
    content['tasks'][0][bad_field]='model returned broken time'
    parsed=ai.parse_plan(json.dumps(content),'В пятницу 27-го числа тренировка с 12:00 до 13:00.','Asia/Tomsk')
    task=parsed.tasks[0]
    assert task.start.astimezone(ZoneInfo('Asia/Tomsk')).strftime('%H:%M')=='12:00'
    assert task.end.astimezone(ZoneInfo('Asia/Tomsk')).strftime('%H:%M')=='13:00'
    assert task.start.astimezone(ZoneInfo('Asia/Tomsk')).date().isoformat()=='2026-11-27'


def test_malformed_model_time_cannot_be_recovered_without_spoken_time():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ai.parse_plan(json.dumps({'tasks':[{'title':'Тренировка','start':'broken','end':'broken'}],'note':'','needs_clarification':False}), 'В пятницу тренировка.', 'Asia/Tomsk')


def test_explicit_multi_create_ignores_selected_event_context(client,monkeypatch):
    api,_=client
    source='На пятницу 27-го поставь работу с 08:00 утра до 09:00 утра. Пары с 12:00 00 до 13:00 0ня и встречу с друзьями с 06:00 вечера до 7 вечера.'
    existing=api.post('/api/tasks',json={'title':'Работа','start':'2026-11-26T08:00:00+07:00','end':'2026-11-26T09:00:00+07:00'}).json()
    monkeypatch.setattr(ai.config,'AI_PROVIDER','gigachat')
    monkeypatch.setattr(ai.AIPlanner,'normalize',lambda self,text:(text,''))
    def must_not_manage(*args):
        raise AssertionError('Explicit creation entered existing-event interpreter')
    monkeypatch.setattr(grounded_ai,'interpret_calendar',must_not_manage)
    result=ai.ExtractedPlan(tasks=[
      {'title':title,'start':f'2026-11-27T{start}:00:00Z','end':f'2026-11-27T{end}:00:00Z'}
      for title,start,end in [('Работа','08','09'),('Пары','12','13'),('Встреча с друзьями','18','19')]],note='',needs_clarification=False)
    monkeypatch.setattr(ai,'ai_post',lambda *a,**kw:httpx.Response(200,request=httpx.Request('POST','http://test'),json={'message':{'content':result.model_dump_json()}}))
    r=api.post('/api/commands',json={'text':source,'timezone':'Asia/Tomsk','context_task_id':existing['id']})
    assert r.status_code==200,r.text
    assert r.json()['kind']=='plan'
    plan=r.json()['plan']
    assert not plan['review'],plan
    assert [datetime.fromisoformat(t['start']).astimezone(ZoneInfo('Asia/Tomsk')).strftime('%H:%M') for t in plan['tasks']]==['08:00','12:00','18:00']
    assert len(api.get('/api/tasks').json())==1

@pytest.mark.parametrize('source',[
 'В пятницу поставь этой задаче время на 10:00.',
 'В пятницу перенеси работу на 10:00 и добавь встречу в 12:00.',
 'Можешь в пятницу поставить созвон на 10:00?',
 'Добавь в описание в пятницу в 10:00.',
])
def test_explicit_create_does_not_steal_management_or_questions(source):
    from app.commands.matching import explicit_scheduled_creation
    assert not explicit_scheduled_creation(source)


# Exact server-side text of the failed request, not only its cleaned UI version.
PROD_TIME_FIRST='На пятницу 27-го числа, с 08:00 до 09:00 работа, с 12:00 дня до 13:00:0 — пары, с 06:00 в00 до 07:00 вечера встреча с друзьями.'

@pytest.mark.parametrize('source',[
 PROD_TIME_FIRST,
 'На пятницу 27-го числа работа с 08:00 до 09:00, пары с 12:00 дня до 13:00:0, встреча с друзьями с 06:00 в00 до 07:00 вечера.',
 'На пятницу 27-го числа: с 08:00 до 09:00 — работа; с 12:00 дня до 13:00:00 — пары; с 06:00 до 07:00 вечера — встреча с друзьями.',
])
@pytest.mark.parametrize('zone',['Asia/Tomsk','Europe/Moscow','America/New_York'])
def test_real_production_time_first_request_survives_full_prepare_save_read(client,monkeypatch,source,zone):
    api,_=client
    monkeypatch.setattr(ai.config,'AI_PROVIDER','gigachat')
    # The fallback must work even if transcript cleanup changes nothing.
    monkeypatch.setattr(ai.AIPlanner,'normalize',lambda self,text:(text,''))
    wrong=ai.ExtractedPlan(tasks=[
      {'title':'Работа','start':'2026-11-27T08:00:00+07:00','end':'2026-11-27T09:00:00+07:00'},
      {'title':'Пары','start':'2026-11-27T19:00:00+07:00','end':'2026-11-27T20:00:00+07:00'},
      {'title':'Встреча с друзьями','start':'2026-11-27T01:00:00+07:00','end':'2026-11-27T02:00:00+07:00'}],note='',needs_clarification=False)
    monkeypatch.setattr(ai,'ai_post',lambda url,**kw:httpx.Response(200,request=httpx.Request('POST',url),json={'message':{'content':wrong.model_dump_json()}}))
    prepared=api.post('/api/commands',json={'text':source,'timezone':zone})
    assert prepared.status_code==200,prepared.text
    draft=prepared.json()['plan']
    assert draft['review']==[],draft
    saved=api.post('/api/plans/'+draft['id']+'/confirm',json={'tasks':draft['tasks']})
    assert saved.status_code==200,saved.text
    expected={'Работа':('08:00','09:00'),'Пары':('12:00','13:00'),'Встреча с друзьями':('18:00','19:00')}
    for event in api.get('/api/tasks').json():
        times=[datetime.fromisoformat(event[k]).astimezone(ZoneInfo(zone)) for k in ('start','end')]
        assert tuple(t.strftime('%H:%M') for t in times)==expected[event['title']]
        assert all(t.date().isoformat()=='2026-11-27' for t in times)



def test_one_invalid_interval_does_not_flag_other_events_in_same_sentence():
    from app.plans.dates import enforce_spoken_time
    from app.tasks.schemas import TaskInput
    tasks=[TaskInput(title='Работа',start='2026-11-27T08:00:00+07:00',end='2026-11-27T09:00:00+07:00'),
           TaskInput(title='Пары',start='2026-11-27T19:00:00+07:00',end='2026-11-27T20:00:00+07:00')]
    assert enforce_spoken_time(tasks,'с 08:00 до 09:00 работа, с 12:77 до 13:00 пары.','Asia/Tomsk')=={1}
