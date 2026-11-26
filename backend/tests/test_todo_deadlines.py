from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import pytest
from test_api import client
from app.todos.schemas import Action,Decision

def test_deadline_and_planned_day_are_independent_and_survive_edits(client):
    api,_=client
    result=api.post('/api/todos',json={'title':'Отчёт','scheduled_date':'2098-11-25',
        'deadline_date':'2098-11-27','deadline_at':'2098-11-27T18:00:00+07:00'})
    assert result.status_code==201,result.text
    todo=result.json()
    assert todo['scheduled_date']=='2098-11-25'
    assert todo['deadline_at']=='2098-11-27T11:00:00Z'
    changed=api.put('/api/todos/'+todo['id'],json={'title':'Годовой отчёт'})
    assert changed.status_code==200,changed.text
    assert changed.json()['deadline_at']==todo['deadline_at']
    api.patch('/api/todos/'+todo['id']+'/completion',json={'completed':True})
    assert api.get('/api/todos').json()[0]['deadline_date']=='2098-11-27'
    cleared=api.put('/api/todos/'+todo['id'],json={'title':'Годовой отчёт','deadline_date':None,'deadline_at':None})
    assert cleared.status_code==200 and cleared.json()['deadline_date'] is None
    assert cleared.json()['scheduled_date']=='2098-11-25'

def test_deadline_without_schedule_does_not_add_task_to_calendar(client):
    api,_=client
    result=api.post('/api/todos',json={'title':'Сдать работу','deadline_date':'2098-11-27'})
    assert result.status_code==201,result.text
    assert result.json()['scheduled_date'] is None and result.json()['scheduled_at'] is None
    assert result.json()['deadline_at'] is None

@pytest.mark.parametrize('values',[
    {'deadline_date':'2098-11-27','deadline_at':'2098-11-28T18:00:00+07:00'},
    {'deadline_at':'2098-11-27T18:00:00'}])
def test_invalid_deadline_rejected(client,values):
    assert client[0].post('/api/todos',json={'title':'Отчёт',**values}).status_code==422

@pytest.mark.parametrize('planned',[False,True])
def test_voice_deadline_is_grounded_separately_from_work_schedule(client,monkeypatch,planned):
    api,_=client
    today=datetime.now(ZoneInfo('Asia/Tomsk')).date()
    source='Сделать отчёт'+(' завтра' if planned else '')+', дедлайн послезавтра в 18:00.'
    # A model may accidentally copy a deadline into the work schedule.
    proposal=Action(action='create',title='Сделать отчёт',scheduled_date=today+timedelta(days=2),
                    deadline_date=today+timedelta(days=5))
    monkeypatch.setattr('app.todos.service.interpret',lambda *args:Decision(actions=[proposal],note=''))
    prepared=api.post('/api/todos/commands/prepare',json={'text':source})
    assert prepared.status_code==200,prepared.text
    command=prepared.json()
    saved=api.post('/api/todos/commands/'+command['id']+'/execute')
    assert saved.status_code==200,saved.text
    todo=saved.json()['tasks'][0]
    assert todo['scheduled_date']==((today+timedelta(days=1)).isoformat() if planned else None)
    assert todo['scheduled_at'] is None
    assert todo['deadline_date']==(today+timedelta(days=2)).isoformat()
    assert datetime.fromisoformat(todo['deadline_at']).astimezone(ZoneInfo('Asia/Tomsk')).hour==18

def test_voice_clear_deadline_keeps_work_date(client,monkeypatch):
    api,_=client
    todo=api.post('/api/todos',json={'title':'Отчёт','scheduled_date':'2098-11-25','deadline_date':'2098-11-27'}).json()
    monkeypatch.setattr('app.todos.service.interpret',lambda *args:Decision(actions=[
        Action(action='update',ref='T1',clear_deadline=True)],note=''))
    result=api.post('/api/todos/commands/prepare',json={'text':'Убери дедлайн у отчёта'})
    assert result.status_code==200,result.text
    saved=api.post('/api/todos/commands/'+result.json()['id']+'/execute')
    assert saved.status_code==200,saved.text
    assert saved.json()['tasks'][0]['deadline_date'] is None
    assert saved.json()['tasks'][0]['scheduled_date']==todo['scheduled_date']

def test_deadline_before_date_is_not_mistaken_for_planned_day(client,monkeypatch):
    api,_=client
    today=datetime.now(ZoneInfo('Asia/Tomsk')).date()
    monkeypatch.setattr('app.todos.service.interpret',lambda *args:Decision(actions=[
        Action(action='create',title='Сдать отчёт')],note=''))
    result=api.post('/api/todos/commands/prepare',json={'text':'Сдать отчёт до послезавтра'})
    assert result.status_code==200,result.text
    saved=api.post('/api/todos/commands/'+result.json()['id']+'/execute').json()['tasks'][0]
    assert saved['deadline_date']==(today+timedelta(days=2)).isoformat()
    assert saved['scheduled_date'] is None
