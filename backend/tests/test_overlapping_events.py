from datetime import datetime, timedelta
from uuid import uuid4

from app.plans.models import Plan
from app.tasks.models import Task
from test_api import client


def event(title, start, end, **extra):
    return {'title':title,'start':'2026-11-26T'+start+':00+07:00',
            'end':'2026-11-26T'+end+':00+07:00',**extra}


def test_manual_events_keep_both_requested_times_when_they_overlap(client):
    api,_=client
    first=api.post('/api/tasks',json=event('До полшестого','16:00','17:30'))
    second=api.post('/api/tasks',json=event('С пяти','17:00','18:00'))
    assert first.status_code==201 and second.status_code==201
    rows=api.get('/api/tasks',params={'start':'2026-11-26T00:00:00+07:00','end':'2026-11-27T00:00:00+07:00'}).json()
    assert len(rows)==2
    assert first.json()['end']=='2026-11-26T10:30:00Z'
    assert second.json()['start']=='2026-11-26T10:00:00Z'
    moved=api.put('/api/tasks/'+second.json()['id'],json=event('Перенесённое','16:30','17:00'))
    assert moved.status_code==200
    assert next(row for row in api.get('/api/tasks').json() if row['id']==first.json()['id'])['end']==first.json()['end']


def test_overlap_does_not_add_review_or_block_voice_plan_confirmation(client,monkeypatch):
    from app.plans.ai import AIPlanner
    from app.plans.schemas import PlanOutput
    api,_=client
    assert api.post('/api/tasks',json=event('Первое','16:00','17:30')).status_code==201
    monkeypatch.setattr(AIPlanner,'generate',lambda *args:PlanOutput(tasks=[event('Второе','17:00','18:00')],note=''))
    response=api.post('/api/plans',json={'text':'На четверг в пять встреча','timezone':'Asia/Tomsk'})
    assert response.status_code==201
    draft=response.json()
    assert draft['review']==[]
    saved=api.post('/api/plans/'+draft['id']+'/confirm',json={'tasks':draft['tasks']})
    assert saved.status_code==200 and len(saved.json())==1
    assert len(api.get('/api/tasks').json())==2


def test_recurring_event_and_changed_occurrence_can_overlap_another_series(client):
    api,_=client
    recurrence={'frequency':'weekly','timezone':'Asia/Tomsk'}
    first=api.post('/api/tasks',json=event('Первая серия','16:00','17:30',recurrence=recurrence))
    second=api.post('/api/tasks',json=event('Вторая серия','17:00','18:00',recurrence=recurrence))
    assert first.status_code==201 and second.status_code==201
    result=api.put('/api/tasks/'+second.json()['id'],
        params={'scope':'occurrence','occurrence_start':second.json()['start']},
        json=event('Одно повторение','16:30','17:15'))
    assert result.status_code==200
    assert result.json()['series_parent_id']==second.json()['id']
    assert next(row for row in api.get('/api/tasks').json() if row['id']==first.json()['id'])['end']==first.json()['end']
