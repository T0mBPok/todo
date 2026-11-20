from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from app.tasks.schemas import TaskInput
from app.plans.dates import enforce_date_context
from app.recurrences.speech import apply_spoken_recurrence

NOW = datetime.fromisoformat('2026-11-20T12:00:00+07:00')
ZONE = ZoneInfo('Asia/Tomsk')


def events():
    return [
        TaskInput(title='Военная кафедра',start='2026-11-26T08:00:00+07:00',end='2026-11-26T17:30:00+07:00'),
        TaskInput(title='Волейбол',start='2026-11-22T11:00:00+07:00',end='2026-11-22T12:00:00+07:00'),
    ]


@pytest.mark.parametrize('text',[
    'В четверг у меня военная кафедра с 08:00 до 17:30, а каждое воскресенье волейбол с 11:00 до 12:00.',
    'В четверг военная кафедра с 08:00 до 17:30. Каждое воскресенье волейбол с 11:00 до 12:00.',
    'Каждое воскресенье волейбол с 11:00 до 12:00, а в четверг военная кафедра с 08:00 до 17:30.',
    'Каждое воскресенье волейбол с 11:00 до 12:00. В четверг военная кафедра с 08:00 до 17:30.',
    'В четверг военная кафедра с 08:00 до 17:30 и волейбол по воскресеньям с 11:00 до 12:00.',
    'Волейбол по воскресеньям с 11:00 до 12:00 и военная кафедра в четверг с 08:00 до 17:30.',
])
def test_sunday_series_cannot_move_thursday_event(text):
    tasks=events()
    enforce_date_context(tasks,text,ZONE.key,NOW)
    result=apply_spoken_recurrence(tasks,text,ZONE.key,NOW)
    by_title={task.title:task for task in result}
    military=by_title['Военная кафедра']
    assert military.start.astimezone(ZONE).date().isoformat()=='2026-11-26'
    assert military.start.astimezone(ZONE).strftime('%H:%M')=='08:00'
    assert military.recurrence is None
    volleyball=by_title['Волейбол']
    assert volleyball.start.astimezone(ZONE).date().isoformat()=='2026-11-22'
    assert volleyball.recurrence.frequency=='weekly'


def test_one_series_can_still_cover_two_named_activities():
    tasks=events()
    tasks[0].title='Баскетбол'
    result=apply_spoken_recurrence(tasks,'Каждое воскресенье волейбол и баскетбол.',ZONE.key,NOW)
    assert all(task.start.astimezone(ZONE).weekday()==6 and task.recurrence for task in result)


def test_only_returned_task_cannot_inherit_another_events_recurrence():
    result=apply_spoken_recurrence(events()[:1],
        'В четверг военная кафедра. Каждое воскресенье волейбол.',ZONE.key,NOW)
    assert result[0].start.astimezone(ZONE).weekday()==3
    assert result[0].recurrence is None


from test_api import client
from app.plans import ai
from app.commands import grounded_ai
import httpx
import json
from datetime import timedelta


@pytest.mark.parametrize('recurring_thursday',[False,True])
def test_weekday_scope_survives_model_error_and_calendar_confirmation(client, monkeypatch, recurring_thursday):
    api,_=client
    today=datetime.now(ZONE).date()
    distance=(3-today.weekday())%7
    thursday=today+timedelta(days=(distance or 7) if recurring_thursday else distance)
    sunday=today+timedelta(days=(6-today.weekday())%7 or 7)
    prefix='Каждый четверг' if recurring_thursday else 'В четверг'
    text=prefix+' у меня военная кафедра с 08:00 до 17:30, а каждое воскресенье волейбол с 11:00 до 12:00.'
    monkeypatch.setattr(ai.config,'AI_PROVIDER','gigachat')
    monkeypatch.setattr(grounded_ai,'interpret_calendar',lambda *args:grounded_ai.Decision(intent='create',note='',create_text=text))
    wrong=ai.ExtractedPlan(tasks=[
        {'title':'Военная кафедра','start':f'{sunday}T08:00:00+07:00','end':f'{sunday}T17:30:00+07:00'},
        {'title':'Волейбол','start':f'{sunday}T11:00:00+07:00','end':f'{sunday}T12:00:00+07:00'},
    ],note='',needs_clarification=False)
    def model(url,**kwargs):
        payload=kwargs['json']
        content=json.dumps({'text':text,'note':''}) if 'text' in payload['format'].get('properties',{}) else wrong.model_dump_json()
        return httpx.Response(200,request=httpx.Request('POST',url),json={'message':{'content':content}})
    monkeypatch.setattr(ai,'ai_post',model)
    response=api.post('/api/commands',json={'text':text,'timezone':ZONE.key})
    assert response.status_code==200,response.text
    draft=response.json()['plan']
    response=api.post(f"/api/plans/{draft['id']}/confirm",json={'tasks':draft['tasks']})
    assert response.status_code==200,response.text
    for values in (draft['tasks'],api.get('/api/tasks').json()):
        military=next(task for task in values if task['title']=='Военная кафедра')
        assert datetime.fromisoformat(military['start']).astimezone(ZONE).date()==thursday
        assert bool(military['recurrence']) is recurring_thursday
        volleyball=next(task for task in values if task['title']=='Волейбол')
        assert datetime.fromisoformat(volleyball['start']).astimezone(ZONE).date()==sunday
        assert volleyball['recurrence']['frequency']=='weekly'
