from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from test_api import client
from app.commands.grounded_ai import Decision,SelectedOperation
from app.tasks.schemas import TaskInput

def seed(api):
    zone=ZoneInfo('Asia/Tomsk');now=datetime.now(zone);day=(now+timedelta(days=(2-now.weekday())%7)).date()
    values=[]
    for title,date,start,end in [('Пара в университете',day-timedelta(days=2),10,11),('Пара в университете',day,10,11),('Доработка прототипа',day,14,16)]:
        value=TaskInput(title=title,category='important_not_urgent',is_fixed=True,start=datetime.combine(date,datetime.min.time(),zone)+timedelta(hours=start),end=datetime.combine(date,datetime.min.time(),zone)+timedelta(hours=end))
        response=api.post('/api/tasks',json=value.model_dump(mode='json'));assert response.status_code==201,response.text
        values.append(response.json())
    phrase=f'В среду {day.isoformat()} убери пару в университете и доработку прототипа. Вместо них в среду в 14:00 разработка по хакатону, а в 19:00 тренировка по баскетболу.'
    return day,values,phrase

def fake(monkeypatch,day,conflict=False):
    def interpret(request,context):
        assert len(context['events'])==2
        assert all(e['start'].startswith(day.isoformat()) for e in context['events'])
        additions=[]
        for title,hour in [('Разработка по хакатону',14),('Тренировка по баскетболу',19)]:
            start=datetime.combine(day,datetime.min.time(),ZoneInfo('Asia/Tomsk'))+timedelta(hours=hour)
            additions.append(TaskInput(title=title,start=start,end=start+timedelta(hours=1)))
        return Decision(intent='manage',note='Удалить два события и добавить два новых.',operations=[SelectedOperation(action='delete',refs=[e['ref'] for e in context['events']],selection='all',scope='occurrence')],new_events=additions)
    monkeypatch.setattr('app.commands.grounded_ai.interpret_calendar',interpret)

def test_selected_other_day_is_excluded_and_replacement_is_atomic(client,monkeypatch):
    api,_=client;day,values,phrase=seed(api);fake(monkeypatch,day)
    response=api.post('/api/commands',json={'text':phrase,'context_task_id':values[0]['id']});assert response.status_code==200,response.text
    plan=response.json();assert [o['instruction']['operation'] for o in plan['operations']]==['delete','delete','create','create']
    assert all(o['requires_confirmation'] for o in plan['operations'])
    assert len(api.get('/api/tasks').json())==3
    executed=api.post('/api/commands/'+plan['id']+'/execute',json={'choices':[{'candidate':0}]*4});assert executed.status_code==200,executed.text
    tasks=api.get('/api/tasks').json();assert len(tasks)==3
    assert any(t['id']==values[0]['id'] for t in tasks)
    assert {t['title'] for t in tasks if t['id']!=values[0]['id']}=={'Разработка по хакатону','Тренировка по баскетболу'}
    times=[datetime.fromisoformat(t['start']).astimezone(ZoneInfo('Asia/Tomsk')).hour for t in executed.json()['tasks']];assert times==[14,19]
    assert api.post('/api/commands/'+plan['id']+'/execute',json={'choices':[{'candidate':0}]*4}).json()==executed.json()

def test_new_event_conflict_rolls_back_deletions_and_other_additions(client,monkeypatch):
    api,_=client;day,values,phrase=seed(api);fake(monkeypatch,day)
    plan=api.post('/api/commands',json={'text':phrase}).json()
    blocked=TaskInput(title='Новое занятое время',start=day.isoformat()+'T19:00:00+07:00',end=day.isoformat()+'T20:00:00+07:00')
    assert api.post('/api/tasks',json=blocked.model_dump(mode='json')).status_code==201
    response=api.post('/api/commands/'+plan['id']+'/execute',json={'choices':[{'candidate':0}]*4})
    assert response.status_code==409,response.text
    tasks=api.get('/api/tasks').json()
    assert len(tasks)==4 and all(any(t['id']==old['id'] for t in tasks) for old in values)
    assert not any(t['title']=='Разработка по хакатону' for t in tasks)

def test_replacement_schema_does_not_rename_deleted_events(monkeypatch):
    import httpx,json
    from app.commands.grounded_ai import interpret_calendar
    from app.commands.schemas import CommandRequest
    def post(url,**kwargs):
        schema=kwargs['json']['format']
        assert schema['$defs']['SelectedOperation']['properties']['action']['enum']==['delete']
        assert schema['properties']['new_events']['minItems']==1
        return httpx.Response(200,request=httpx.Request('POST',url),json={'message':{'content':json.dumps({'intent':'clarify','operations':[],'new_events':[],'note':'Уточните время'})}})
    monkeypatch.setattr(httpx,'post',post)
    result=interpret_calendar(CommandRequest(text='Убери пару, вместо неё добавь тренировку'),{'events':[]})
    assert result.intent=='clarify'
