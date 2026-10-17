from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select,func
from test_api import client
from app.recurrences.models import RecurrenceException
from app.recurrences.service import instances
from app.recurrences.speech import apply_spoken_recurrence
from app.tasks.schemas import TaskInput

def series():
    return {'title':'Повторяющаяся тренировка','start':'2098-11-12T18:00:00+07:00',
            'end':'2098-11-12T19:00:00+07:00',
            'recurrence':{'frequency':'weekly','timezone':'Asia/Tomsk'}}

def window(api,start='2098-11-12T00:00:00Z',end='2098-12-05T00:00:00Z'):
    response=api.get('/api/tasks',params={'start':start,'end':end})
    assert response.status_code==200,response.text
    return response.json()

def test_infinite_series_is_one_record_and_visible_far_in_future(client):
    api,session=client
    response=api.post('/api/tasks',json=series())
    assert response.status_code==201,response.text
    data=response.json()
    items=[task for task in window(api) if task['id']==data['id']]
    assert len(items)==4
    assert len({item['occurrence_id'] for item in items})==4
    assert len({item['id'] for item in items})==1
    future=window(api,'2198-11-01T00:00:00Z','2198-12-01T00:00:00Z')
    assert any(item['id']==data['id'] for item in future)

def test_delete_one_then_entire_series(client):
    api,session=client
    data=api.post('/api/tasks',json=series()).json()
    items=[t for t in window(api) if t['id']==data['id']]
    selected=items[1]
    assert api.delete('/api/tasks/'+data['id']).status_code==422
    assert api.delete('/api/tasks/'+data['id'],params={'scope':'occurrence','occurrence_start':selected['start']}).status_code==204
    remaining=[t for t in window(api) if t['id']==data['id']]
    assert len(remaining)==3
    assert selected['occurrence_start'] not in [t['occurrence_start'] for t in remaining]
    assert api.delete('/api/tasks/'+data['id'],params={'scope':'series'}).status_code==204
    assert not [t for t in window(api) if t['id']==data['id']]
    assert session.scalar(select(func.count()).select_from(RecurrenceException).where(RecurrenceException.task_id==data['id']))==0

def test_deleted_occurrence_frees_its_slot_but_not_next_week(client):
    api,_=client
    data=api.post('/api/tasks',json=series()).json()
    items=[t for t in window(api) if t['id']==data['id']]
    first,second=items[:2]
    assert api.delete('/api/tasks/'+data['id'],params={'scope':'occurrence','occurrence_start':first['start']}).status_code==204
    assert api.post('/api/tasks',json={'title':'Разовое событие','start':first['start'],'end':first['end']}).status_code==201
    assert api.post('/api/tasks',json={'title':'Конфликт','start':second['start'],'end':second['end']}).status_code==409
    assert api.delete('/api/tasks/'+data['id'],params={'scope':'occurrence','occurrence_start':'2098-11-13T18:00:00+07:00'}).status_code==422

def test_recurring_series_conflicts_with_future_one_off(client):
    api,_=client
    data=series(); start=datetime.fromisoformat(data['start'])+timedelta(days=28)
    assert api.post('/api/tasks',json={'title':'Занято','start':start.isoformat(),'end':(start+timedelta(hours=1)).isoformat()}).status_code==201
    assert api.post('/api/tasks',json=data).status_code==409

def test_recurring_series_conflict_each_other(client):
    api,_=client
    assert api.post('/api/tasks',json=series()).status_code==201
    other=series();other['start']='2098-11-19T18:30:00+07:00';other['end']='2098-11-19T19:30:00+07:00'
    assert api.post('/api/tasks',json=other).status_code==409

def test_dst_preserves_local_time():
    task=TaskInput(title='Тренировка',start='2026-03-22T18:00:00+01:00',end='2026-03-22T19:00:00+01:00',recurrence={'frequency':'weekly','timezone':'Europe/Berlin'})
    values=list(instances(task,datetime(2026,3,20,tzinfo=timezone.utc),datetime(2026,4,6,tzinfo=timezone.utc)))
    assert len(values)==3
    assert [start.astimezone(ZoneInfo('Europe/Berlin')).hour for start,_ in values]==[18,18,18]
    assert [start.hour for start,_ in values]==[17,16,16]

def test_spoken_tuesday_starts_next_weekday_even_when_today_is_tuesday():
    for now,expected in [('2026-10-16T21:00:00+07:00',20),('2026-10-20T10:00:00+07:00',27)]:
        task=TaskInput(title='Тренировка',start='2026-10-19T18:00:00+07:00',end='2026-10-19T19:00:00+07:00')
        result=apply_spoken_recurrence([task],'Каждый вторник в шесть вечера ходить на тренировку','Asia/Tomsk',datetime.fromisoformat(now))
        assert result[0].start.day==expected
        assert result[0].start.hour==18
        assert result[0].recurrence.frequency=='weekly'

def test_daily_recurrence_and_non_recurring_text():
    task=TaskInput(title='Зарядка',start='2026-10-19T08:00:00+07:00',end='2026-10-19T08:20:00+07:00')
    result=apply_spoken_recurrence([task],'Каждый день зарядка в 8 утра','Asia/Tomsk',datetime.fromisoformat('2026-10-16T21:00:00+07:00'))
    assert result[0].start.day==17
    assert result[0].recurrence.frequency=='daily'
    assert len(list(instances(task,datetime(2026,10,17,tzinfo=timezone.utc),datetime(2026,10,20,tzinfo=timezone.utc))))==3
    apply_spoken_recurrence([task],'Завтра зарядка','Asia/Tomsk')
    assert task.recurrence is None
