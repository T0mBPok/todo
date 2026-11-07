from datetime import datetime
from app.plans.dates import enforce_date_context, resolve_anchor
from app.tasks.schemas import TaskInput

NOW=datetime.fromisoformat('2026-10-16T21:00:00+07:00')
def task(title, start):
    return TaskInput(title=title,start=start,end=start.replace('11:00','12:00').replace('13:15','14:15').replace('12:30','13:30'))

def test_wrong_model_weekday_is_corrected_with_inherited_sunday():
    tasks=[task('Пара в университете','2026-10-17T13:15:00+07:00'),
           task('Волейбол','2026-10-19T11:00:00+07:00'),
           task('Баскетбол','2026-10-19T12:30:00+07:00')]
    enforce_date_context(tasks,'Завтра пара в 13:15. В воскресенье волейбол в 11. После него баскетбол в 12:30.','Asia/Tomsk',NOW)
    assert [t.start.day for t in tasks]==[17,18,18]
    assert [t.start.hour for t in tasks]==[13,11,12]

def test_nearest_weekday_and_year_boundary():
    assert resolve_anchor('воскресенье',NOW.date()).isoformat()=='2026-10-18'
    assert resolve_anchor('завтра',datetime(2026,12,31).date()).isoformat()=='2027-01-01'

def test_single_anchor_and_overnight_duration():
    t=TaskInput(title='Ночная работа',start='2026-10-19T23:00:00+07:00',end='2026-10-20T01:00:00+07:00')
    enforce_date_context([t],'В воскресенье ночью работа','Asia/Tomsk',NOW)
    assert t.start.day==18 and t.end.day==19


import pytest
from fastapi import HTTPException
from zoneinfo import ZoneInfo

@pytest.mark.parametrize('phrase', ['В среду 28-го стартап Сейсмон', 'В среду, 28 октября стартап Сейсмон', 'В среду 28 стартап Сейсмон'])
def test_explicit_day_beats_nearest_weekday(phrase):
    t=task('Стартап Сейсмон','2026-10-21T11:00:00+07:00')
    enforce_date_context([t],phrase,'Asia/Tomsk',datetime.fromisoformat('2026-10-20T22:00:00+07:00'))
    assert t.start.astimezone(ZoneInfo('Asia/Tomsk')).date().isoformat()=='2026-10-28'
    assert t.start.astimezone(ZoneInfo('Asia/Tomsk')).hour==11
    assert (t.end-t.start).total_seconds()==3600

def test_weekday_time_is_not_day_number():
    t=task('Встреча','2026-10-28T11:00:00+07:00')
    enforce_date_context([t],'В среду в 11:00 встреча','Asia/Tomsk',NOW)
    assert t.start.day==21

def test_conflicting_weekday_requires_clarification():
    t=task('Встреча','2026-10-21T11:00:00+07:00')
    with pytest.raises(HTTPException) as error:
        enforce_date_context([t],'В среду 29 октября встреча','Asia/Tomsk',NOW)
    assert error.value.status_code==422

def test_explicit_day_with_multiple_events():
    tasks=[task('Сейсмон','2026-10-21T11:00:00+07:00'),task('Волейбол','2026-10-25T11:00:00+07:00')]
    enforce_date_context(tasks,'В среду 28-го Сейсмон. В воскресенье волейбол.','Asia/Tomsk',NOW)
    assert [t.start.day for t in tasks]==[28,18]
