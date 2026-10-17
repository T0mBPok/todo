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
