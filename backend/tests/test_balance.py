from datetime import datetime,timedelta
from test_api import client
from app.balance.schemas import Decision
from app.balance import service

DAY='2098-11-12'
def seed(api,title='Встреча с другом',start='16:00',end='17:00',category='not_important_not_urgent',recurrence=None):
    response=api.post('/api/tasks',json={'title':title,'description':'Обсудить отпуск','category':category,'start':DAY+'T'+start+':00+07:00','end':DAY+'T'+end+':00+07:00','recurrence':recurrence})
    assert response.status_code==201,response.text
    return response.json()
def busy(api):
    seed(api,'Работа','08:00','09:00','important_not_urgent')
    seed(api,'Зал','10:00','11:00','important_not_urgent')
    seed(api,'Стартап','13:00','15:00','important_not_urgent')

def model(monkeypatch,*,fixed=False,bad=False):
    captured={}
    def analyze(context):
        captured.update(context)
        event=next(e for e in context['source_events'] if 'другом' in e['title'])
        slots=[s for s in context['allowed_slots'] if s['event_ref']==event['ref']]
        slot=next((s for s in slots if 'T18:00' in s['start']),slots[0] if slots else {'ref':'missing'})
        return Decision.model_validate({'summary':'Сохраним учёбу и здоровье, встречу предложим завтра.','assessments':[{'event_ref':e['ref'],'flexibility':'fixed' if fixed or 'Пара' in e['title'] else 'coordinate','reason':'Нужно согласовать' if 'другом' in e['title'] else 'Фиксированное расписание'} for e in context['source_events']], 'moves':[{'event_ref':event['ref'],'slot_ref':'unknown' if bad else slot['ref'],'reason':'Разгрузить день для пары и разработки.'}]})
    monkeypatch.setattr(service,'analyze',analyze)
    return captured
def prepare(api,**kwargs):return api.post('/api/balance',json={'day':DAY,'timezone':'Asia/Tomsk','horizon_days':1,**kwargs})

def test_suggest_then_confirm_and_idempotence(client,monkeypatch):
    api,_=client;friend=seed(api);busy(api);seed(api,'Пара в университете','11:00','12:00','important_not_urgent')
    captured=model(monkeypatch);response=prepare(api);assert response.status_code==200,response.text
    plan=response.json();assert len(plan['proposals'])==1
    assert captured['load'][0]['count']==5 and captured['load'][1]['count']==0
    assert next(t for t in api.get('/api/tasks').json() if t['id']==friend['id'])['start']==friend['start']
    endpoint='/api/balance/'+plan['id']+'/apply'
    assert api.post(endpoint,json={'proposals':[0]}).status_code==422
    moved=api.post(endpoint,json={'proposals':[0],'coordination_confirmed':True});assert moved.status_code==200,moved.text
    task=moved.json()['tasks'][0];assert task['category']==friend['category'] and task['description']==friend['description']
    assert datetime.fromisoformat(task['end'])-datetime.fromisoformat(task['start'])==timedelta(hours=1)
    assert task['start'].startswith('2098-11-13')
    assert api.post(endpoint,json={'proposals':[0],'coordination_confirmed':True}).json()==moved.json()
    assert api.post('/api/commands/'+plan['id']+'/execute',json={'choices':[]}).status_code in (404,422)

def test_slot_occupied_after_analysis_is_not_overwritten(client,monkeypatch):
    api,_=client;friend=seed(api);busy(api);model(monkeypatch);plan=prepare(api).json();proposal=plan['proposals'][0]
    occupied=api.post('/api/tasks',json={'title':'Новое дело','category':'important_urgent','start':proposal['new_start'],'end':proposal['new_end']});assert occupied.status_code==201,occupied.text
    result=api.post('/api/balance/'+plan['id']+'/apply',json={'proposals':[0],'coordination_confirmed':True})
    assert result.status_code==409,result.text
    assert next(t for t in api.get('/api/tasks').json() if t['id']==friend['id'])['start']==friend['start']

def test_stale_event_is_not_overwritten(client,monkeypatch):
    api,_=client;friend=seed(api);busy(api);model(monkeypatch);plan=prepare(api).json()
    payload={k:friend[k] for k in ('title','description','category','start','end','recurrence')};payload['description']='Изменено'
    assert api.put('/api/tasks/'+friend['id'],json=payload).status_code==200
    assert api.post('/api/balance/'+plan['id']+'/apply',json={'proposals':[0],'coordination_confirmed':True}).status_code==409

def test_bad_model_and_fixed_events_cannot_move(client,monkeypatch):
    api,_=client;seed(api);busy(api);model(monkeypatch,bad=True);assert prepare(api).status_code==502
    model(monkeypatch,fixed=True);assert prepare(api).status_code==502

def test_pinned_and_urgent_events_cannot_move(client,monkeypatch):
    api,_=client;friend=seed(api,category='important_urgent');context=model(monkeypatch)
    assert prepare(api).json()['proposals']==[]
    assert context=={}

def test_recurring_move_changes_only_one_occurrence(client,monkeypatch):
    api,_=client;friend=seed(api,recurrence={'frequency':'weekly','timezone':'Asia/Tomsk'});busy(api);model(monkeypatch)
    plan=prepare(api).json();r=api.post('/api/balance/'+plan['id']+'/apply',json={'proposals':[0],'coordination_confirmed':True});assert r.status_code==200,r.text
    tasks=api.get('/api/tasks',params={'start':DAY+'T00:00:00+07:00','end':'2098-11-21T00:00:00+07:00'}).json()
    tasks=[t for t in tasks if t['title']=='Встреча с другом']
    assert len(tasks)==2
    assert sorted(datetime.fromisoformat(t['start']).astimezone(__import__('zoneinfo').ZoneInfo('Asia/Tomsk')).date().isoformat() for t in tasks)==['2098-11-13','2098-11-19']

def test_empty_day_never_calls_model(client,monkeypatch):
    api,_=client;monkeypatch.setattr(service,'analyze',lambda _: (_ for _ in ()).throw(AssertionError('Unexpected AI call')))
    response=prepare(api);assert response.status_code==200 and response.json()['id'] is None

def test_slots_respect_timezone_duration_breaks_and_working_hours():
    from zoneinfo import ZoneInfo
    from app.tasks.schemas import TaskInput
    from app.balance.schemas import BalanceRequest
    from app.balance.slots import free_slots
    zone=ZoneInfo('Asia/Tomsk')
    event=TaskInput(title='Работа',start='2098-11-12T18:00:00+07:00',end='2098-11-12T20:00:00+07:00')
    occupied=TaskInput(title='Занято',start='2098-11-13T17:00:00+07:00',end='2098-11-13T19:00:00+07:00')
    request=BalanceRequest(day=DAY,horizon_days=1)
    slots=free_slots(event,[occupied],request,datetime(2098,11,12,tzinfo=zone))
    assert slots
    for start,end in slots:
        assert start.date().isoformat()=='2098-11-13' and start.hour>=9 and end.hour<=21
        assert end-start==timedelta(hours=2)
        assert end<=occupied.start-timedelta(minutes=30) or start>=occupied.end+timedelta(minutes=30)

def test_model_schema_requires_an_assessment_for_every_event(monkeypatch):
    import httpx,json
    from app.balance.ai import analyze
    captured={}
    def post(url,**kwargs):
        captured.update(kwargs['json'])
        return httpx.Response(200,request=httpx.Request('POST',url),json={'message':{'content':json.dumps({'summary':'Всё хорошо','assessments':{'E1':{'flexibility':'fixed','reason':'Пара'},'E2':{'flexibility':'flexible','reason':'Личная работа'}},'moves':[]})}})
    monkeypatch.setattr(httpx,'post',post)
    result=analyze({'source_events':[{'ref':'E1'},{'ref':'E2'}],'allowed_slots':[]})
    assert [a.event_ref for a in result.assessments]==['E1','E2']
    assert captured['format']['properties']['assessments']['required']==['E1','E2']
    assert captured['format']['required']==['summary','assessments','moves']

def test_scan_includes_later_busy_day_and_pins_university(client,monkeypatch):
    from app.balance.schemas import BalanceRequest
    api,session=client
    seed(api,'Пара в университете','11:00','12:00','not_important_not_urgent')
    seed(api);busy(api)
    captured=model(monkeypatch)
    # The busy day is three days after the start, not the day selected by a user.
    result=service.BalanceService(session).prepare(BalanceRequest(day='2098-11-09',scan_days=7,horizon_days=7))
    assert len(result['load'])==14
    assert len(captured['source_events'])==5
    university=next(e for e in captured['source_events'] if 'Пара' in e['title'])
    assert university['pinned']
    assert all(slot['event_ref']!=university['ref'] for slot in captured['allowed_slots'])
    assert result['proposals'][0]['new_start'].startswith('2098-11-13')

def test_scan_does_not_offer_a_busier_target_day(client,monkeypatch):
    api,_=client;seed(api)
    response=api.post('/api/tasks',json={'title':'Рабочий день','category':'important_not_urgent','start':'2098-11-13T09:00:00+07:00','end':'2098-11-13T18:00:00+07:00'})
    assert response.status_code==201
    def analyze(context):
        assert not context['allowed_slots']
        return Decision.model_validate({'summary':'Свободный день не найден','assessments':[{'event_ref':'E1','flexibility':'coordinate','reason':'Встреча'}],'moves':[]})
    monkeypatch.setattr(service,'analyze',analyze)
    assert prepare(api).json()['proposals']==[]

def test_fixed_event_is_persisted_and_excluded_from_ai_slots(client,monkeypatch):
    api,_=client;friend=seed(api);busy(api)
    payload={k:friend[k] for k in ('title','description','category','start','end','recurrence')}
    payload['is_fixed']=True
    assert api.put('/api/tasks/'+friend['id'],json=payload).json()['is_fixed']
    captured={}
    def analyze(context):
        captured.update(context)
        return Decision.model_validate({'summary':'Закреплённое событие сохраняется','assessments':[{'event_ref':e['ref'],'flexibility':'fixed','reason':'Сохраняем'} for e in context['source_events']],'moves':[]})
    monkeypatch.setattr(service,'analyze',analyze)
    assert prepare(api).status_code==200
    if captured:
        ref=next(e['ref'] for e in captured['source_events'] if 'другом' in e['title'])
        assert next(e for e in captured['source_events'] if e['ref']==ref)['pinned']
        assert not any(s['event_ref']==ref for s in captured['allowed_slots'])
    payload.pop('is_fixed');payload['description']='Другие правки'
    assert api.put('/api/tasks/'+friend['id'],json=payload).json()['is_fixed']

def test_pinning_event_invalidates_old_proposal(client,monkeypatch):
    api,_=client;friend=seed(api);busy(api);model(monkeypatch);plan=prepare(api).json()
    payload={k:friend[k] for k in ('title','description','category','start','end','recurrence')};payload['is_fixed']=True
    assert api.put('/api/tasks/'+friend['id'],json=payload).status_code==200
    assert api.post('/api/balance/'+plan['id']+'/apply',json={'proposals':[0],'coordination_confirmed':True}).status_code==409
