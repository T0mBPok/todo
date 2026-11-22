from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import pytest
from test_api import client
from app.todos.schemas import Action, Decision
from app.todos.scheduling import grounded_schedule
from app.todos import service

@pytest.mark.parametrize('zone',['Asia/Tomsk','Europe/Moscow','America/New_York'])
def test_todo_schedule_complete_reopen_edit_clear(client,zone):
    api,_=client
    start=datetime(2026,11,27,18,tzinfo=ZoneInfo(zone))
    payload={'title':'Сделать адаптив','scheduled_date':'2026-11-27','scheduled_at':start.isoformat(),'timezone':zone}
    result=api.post('/api/todos',json=payload)
    assert result.status_code==201,result.text
    task=result.json()
    assert datetime.fromisoformat(task['scheduled_at'])==start
    for completed in (True,True,False):
        changed=api.patch('/api/todos/'+task['id']+'/completion',json={'completed':completed})
        assert changed.status_code==200,changed.text
        assert changed.json()['completed']==completed
        assert changed.json()['scheduled_at']==task['scheduled_at']
    edited=api.put('/api/todos/'+task['id'],json={'title':'Адаптив готов'})
    assert edited.status_code==200,edited.text
    assert edited.json()['scheduled_date']=='2026-11-27'
    cleared=api.put('/api/todos/'+task['id'],json={'title':'Адаптив','scheduled_date':None,'scheduled_at':None})
    assert cleared.status_code==200 and cleared.json()['scheduled_at'] is None and cleared.json()['scheduled_date'] is None
    assert api.get('/api/tasks').json()==[]


def test_date_only_todo_does_not_gain_a_midnight_time(client):
    api,_=client
    result=api.post('/api/todos',json={'title':'Отчёт','scheduled_date':'2026-11-27'})
    assert result.status_code==201,result.text
    assert result.json()['scheduled_at'] is None
    assert result.json()['scheduled_date']=='2026-11-27'


@pytest.mark.parametrize('payload',[
 {'scheduled_at':'2026-11-27T18:00:00'},
 {'scheduled_date':'2026-11-28','scheduled_at':'2026-11-27T18:00:00+07:00'},
 {'timezone':'Bad/Zone'},
])
def test_invalid_schedule_is_rejected(client,payload):
    api,_=client
    assert api.post('/api/todos',json={'title':'Отчёт',**payload}).status_code==422


@pytest.mark.parametrize('zone',['Asia/Tomsk','Europe/Moscow','Europe/Lisbon'])
@pytest.mark.parametrize(('source','clock'),[
 ('Сделать адаптив 27-го числа в шесть вечера','18:00'),
 ('Сделать адаптив 27-го числа в 18:00','18:00'),
 ('Сделать адаптив 27-го числа в 08:00 вечера','20:00'),
 ('Сделать адаптив 27-го числа с 10:00 утра до 3 часов дня','10:00'),
])
def test_voice_schedule_corrects_model_utc_clock(source,clock,zone):
    wrong=Action(action='create',title='Сделать адаптив',scheduled_date='2026-11-27',scheduled_at='2026-11-27T18:00:00Z')
    schedule,review=grounded_schedule(wrong,source,zone)
    assert schedule['scheduled_at'].astimezone(ZoneInfo(zone)).strftime('%H:%M')==clock
    assert not review


def test_voice_task_with_date_executes_once_without_creating_event(client,monkeypatch):
    api,_=client
    text='Мне надо сделать адаптив для мобилки 27-го числа в шесть вечера'
    def interpret(value,context,history,zone):
        assert zone=='Asia/Tomsk'
        return Decision(note='Добавить адаптив',actions=[Action(action='create',title='Сделать адаптив для мобилки',scheduled_date='2026-11-27',scheduled_at='2026-11-27T18:00:00Z',schedule_text=text)])
    monkeypatch.setattr(service,'interpret',interpret)
    draft=api.post('/api/todos/commands/prepare',json={'text':text,'timezone':'Asia/Tomsk'})
    assert draft.status_code==200,draft.text
    assert not draft.json()['requires_confirmation']
    saved=api.post('/api/todos/commands/'+draft.json()['id']+'/execute')
    assert saved.status_code==200,saved.text
    assert api.post('/api/todos/commands/'+draft.json()['id']+'/execute').json()==saved.json()
    todo=saved.json()['tasks'][0]
    assert datetime.fromisoformat(todo['scheduled_at']).astimezone(ZoneInfo('Asia/Tomsk')).strftime('%H:%M')=='18:00'
    assert len(api.get('/api/todos').json())==1
    assert api.get('/api/tasks').json()==[]


def test_multiple_voice_tasks_keep_individual_days_and_unscheduled_task(client,monkeypatch):
    api,_=client
    fragments=['Завтра купить продукты','Послезавтра в 18:00 закончить отчёт','Позвонить маме']
    actions=[Action(action='create',title='Купить продукты',schedule_text=fragments[0]),Action(action='create',title='Закончить отчёт',schedule_text=fragments[1]),Action(action='create',title='Позвонить маме')]
    monkeypatch.setattr(service,'interpret',lambda *args:Decision(actions=actions,note='Три задачи'))
    draft=api.post('/api/todos/commands/prepare',json={'text':'. '.join(fragments),'timezone':'Asia/Tomsk'})
    assert draft.status_code==200,draft.text
    result=api.post('/api/todos/commands/'+draft.json()['id']+'/execute')
    assert result.status_code==200,result.text
    tasks=result.json()['tasks'];today=datetime.now(ZoneInfo('Asia/Tomsk')).date()
    assert tasks[0]['scheduled_date']==(today+timedelta(days=1)).isoformat() and tasks[0]['scheduled_at'] is None
    assert tasks[1]['scheduled_date']==(today+timedelta(days=2)).isoformat()
    assert tasks[2]['scheduled_date'] is None


def test_invented_schedule_needs_confirmation():
    action=Action(action='create',title='Купить продукты',scheduled_date='2026-11-27')
    assert grounded_schedule(action,'Купить продукты','Asia/Tomsk')[1]


def test_multi_task_missing_model_fragments_are_grounded_from_their_titles(client,monkeypatch):
    api,_=client
    monkeypatch.setattr(service,'interpret',lambda *a:Decision(note='',actions=[
        Action(action='create',title='Купить продукты',scheduled_date='2026-11-23'),
        Action(action='create',title='Закончить отчёт',scheduled_at='2026-11-24T18:00'),
        Action(action='create',title='Позвонить маме')]))
    draft=api.post('/api/todos/commands/prepare',json={'text':'Завтра купить продукты. Послезавтра в 18:00 закончить отчёт. Позвонить маме, без даты.','timezone':'Asia/Tomsk'})
    assert draft.status_code==200,draft.text
    assert not draft.json()['requires_confirmation']
    saved=api.post('/api/todos/commands/'+draft.json()['id']+'/execute')
    assert saved.status_code==200,saved.text
    assert saved.json()['tasks'][2]['scheduled_date'] is None
    assert datetime.fromisoformat(saved.json()['tasks'][1]['scheduled_at']).astimezone(ZoneInfo('Asia/Tomsk')).strftime('%H:%M')=='18:00'


def test_voice_rescheduling_preserves_time_and_can_remove_time(client,monkeypatch):
    api,_=client
    todo=api.post('/api/todos',json={'title':'Отчёт','scheduled_at':'2026-11-27T18:00:00+07:00','timezone':'Asia/Tomsk'}).json()
    def prepare(action,text):
        monkeypatch.setattr(service,'interpret',lambda *a:Decision(note='',actions=[action]))
        response=api.post('/api/todos/commands/prepare',json={'text':text,'timezone':'Asia/Tomsk'})
        assert response.status_code==200,response.text
        response=api.post('/api/todos/commands/'+response.json()['id']+'/execute')
        assert response.status_code==200,response.text
        return response.json()['tasks'][0]
    moved=prepare(Action(action='update',ref='T1',scheduled_date='2026-11-28'),'Перенеси отчёт на 28-е число')
    assert datetime.fromisoformat(moved['scheduled_at']).astimezone(ZoneInfo('Asia/Tomsk')).strftime('%H:%M')=='18:00'
    date_only=prepare(Action(action='update',ref='T1',clear_time=True),'Убери время у отчёта')
    assert date_only['scheduled_at'] is None and date_only['scheduled_date']==moved['scheduled_date']
    cleared=prepare(Action(action='update',ref='T1',clear_schedule=True),'Убери дату отчёта')
    assert cleared['scheduled_date'] is None


def test_model_cannot_turn_date_only_task_into_midnight_event():
    action=Action(action='create',title='Отчёт',scheduled_date='2026-11-27',scheduled_at='2026-11-27T00:00:00Z')
    schedule,review=grounded_schedule(action,'Отчёт 27-го числа','Asia/Tomsk')
    assert schedule['scheduled_at'] is None
    assert not review


@pytest.mark.parametrize('bad_time',['18:00','6 часов вечера','2026-11-27 18:00 Asia/Tomsk','2026-11-27T18:00:00+7:00',''])
def test_malformed_model_clock_is_recovered_from_original_speech(client,monkeypatch,bad_time):
    import json
    from app.todos.ai import parse_decision
    api,_=client
    text='На 27-е число, на 6 часов вечера, поставь задачу сделать адаптив для мобилки.'
    decision=parse_decision(json.dumps({'actions':[{'action':'create','title':'Сделать адаптив для мобилки','scheduled_date':'2026-11-27','scheduled_at':bad_time,'schedule_text':'27 ноября 18:00'}],'note':'Добавить адаптив'}))
    monkeypatch.setattr(service,'interpret',lambda *a:decision)
    draft=api.post('/api/todos/commands/prepare',json={'text':text,'timezone':'Asia/Tomsk'})
    assert draft.status_code==200,draft.text
    assert not draft.json()['requires_confirmation']
    saved=api.post('/api/todos/commands/'+draft.json()['id']+'/execute')
    assert saved.status_code==200,saved.text
    task=saved.json()['tasks'][0]
    assert task['scheduled_date']=='2026-11-27'
    assert datetime.fromisoformat(task['scheduled_at']).astimezone(ZoneInfo('Asia/Tomsk')).strftime('%H:%M')=='18:00'


def test_unrecoverable_model_time_is_not_silently_auto_saved():
    from app.todos.ai import parse_decision
    value=parse_decision('{"actions":[{"action":"create","title":"Отчёт","scheduled_at":"bad clock"}],"note":""}')
    assert grounded_schedule(value.actions[0],'Сделать отчёт','Asia/Tomsk')[1]


def test_broken_schedule_does_not_relax_action_or_title_validation():
    from app.todos.ai import parse_decision
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        parse_decision('{"actions":[{"action":"invented","scheduled_at":"bad clock"}],"note":""}')
