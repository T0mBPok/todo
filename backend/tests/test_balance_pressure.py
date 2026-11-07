from datetime import datetime
from zoneinfo import ZoneInfo
from app.tasks.schemas import TaskInput
from app.balance.schemas import BalanceRequest
from app.balance.slots import move_benefit,day_pressure
from test_api import client

def event(day,start,end,title='Дело'):
    return TaskInput(title=title,start=f'2098-11-{day:02}T{start}:00+07:00',end=f'2098-11-{day:02}T{end}:00+07:00')
def benefit(moving,start,end,events):
    return move_benefit(moving,datetime.fromisoformat(start+'+07:00'),datetime.fromisoformat(end+'+07:00'),events,BalanceRequest(day='2098-11-12'))

def test_morning_meeting_evening_training_is_not_overload():
    meeting=event(12,'10:00','11:00');events=[meeting,event(12,'18:00','19:00'),event(13,'17:00','18:00')]
    assert benefit(meeting,'2098-11-13T09:00:00','2098-11-13T10:00:00',events) is None
    assert not day_pressure(events,datetime(2098,11,12).date(),BalanceRequest(day='2098-11-12'))['busy']

def test_exchanging_equal_burdens_is_not_improvement_even_in_busy_days():
    moving=event(12,'09:00','10:00')
    events=[moving,event(12,'11:00','16:00'),event(13,'11:00','16:00')]
    assert benefit(moving,'2098-11-13T09:00:00','2098-11-13T10:00:00',events) is None

def test_busy_day_to_empty_day_reduces_pressure():
    moving=event(12,'16:00','17:00')
    events=[event(12,'09:00','10:00'),event(12,'11:00','12:00'),event(12,'13:00','15:00'),moving]
    result=benefit(moving,'2098-11-13T16:00:00','2098-11-13T17:00:00',events)
    assert result and result['source_after']['minutes']==240 and result['target_after']['minutes']==60

def test_same_hours_but_dense_chain_can_improve():
    moving=event(12,'10:00','11:00')
    events=[event(12,'09:00','10:00'),moving,event(12,'11:00','12:00'),event(13,'17:00','19:00')]
    result=benefit(moving,'2098-11-13T09:00:00','2098-11-13T10:00:00',events)
    assert result and result['source_after']['short_break_minutes']<result['source_before']['short_break_minutes']

def test_no_ai_call_for_screenshot_scenario(client,monkeypatch):
    from app.balance import service
    api,_=client
    for value in [event(12,'10:00','11:00'),event(12,'18:00','19:00'),event(13,'17:00','18:00')]:
        assert api.post('/api/tasks',json=value.model_dump(mode='json')).status_code==201
    monkeypatch.setattr(service,'analyze',lambda _: (_ for _ in ()).throw(AssertionError('Not overloaded')))
    result=api.post('/api/balance',json={'day':'2098-11-12','horizon_days':1})
    assert result.status_code==200 and result.json()['proposals']==[]
