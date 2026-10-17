from test_api import client as base_client
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from app.tasks.schemas import TaskInput
from app.recurrences.speech import apply_spoken_recurrence
import app.commands.recurrence as conversion
import pytest

def test_spoken_multiple_weekdays():
    now=datetime.fromisoformat('2026-10-16T10:00:00+07:00')
    task=TaskInput(title='Тренировка',start='2026-10-20T18:00:00+07:00',end='2026-10-20T19:00:00+07:00')
    result=apply_spoken_recurrence([task],'Каждый вторник, четверг и субботу тренировка в 18','Asia/Tomsk',now)
    assert sorted(t.start.weekday() for t in result)==[1,3,5]
    assert all(t.recurrence.frequency=='weekly' for t in result)
    assert all(t.start.astimezone(ZoneInfo('Asia/Tomsk')).hour==18 for t in result)
    result=apply_spoken_recurrence([task],'По пятницам и воскресеньям тренировка в 18','Asia/Tomsk',now)
    assert sorted(t.start.weekday() for t in result)==[4,6]

def test_model_duplicates_are_deduplicated_after_expanding_days():
    tasks=[TaskInput(title='Тренировка',start=f'2026-10-{day}T18:00:00+07:00',end=f'2026-10-{day}T19:00:00+07:00') for day in (20,22,24)]
    result=apply_spoken_recurrence(tasks,'Каждый вторник, четверг и субботу тренировка в 18','Asia/Tomsk',datetime.fromisoformat('2026-10-16T10:00:00+07:00'))
    assert len(result)==3

def seed(api):
    zone=ZoneInfo('Asia/Tomsk');now=datetime.now(zone);result=[]
    for weekday,title,hour in [(1,'Тренировка в зале',18),(3,'Тренировка в зале',18),(5,'Тренировка в зале',18),(6,'Тренировка по волейболу',11),(6,'Тренировка по баскетболу',12)]:
        # Use a distant empty window while the converter clock is pinned to it.
        first=now.replace(year=2097,month=10,day=16,hour=hour,minute=0,second=0,microsecond=0)
        first+=timedelta(days=(weekday-first.weekday())%7 or 7)
        response=api.post('/api/tasks',json={'title':title,'description':'Сохранить детали','start':first.isoformat(),'end':(first+timedelta(hours=1)).isoformat()})
        assert response.status_code==201,response.text
        result.append(response.json())
    return result

def test_existing_events_become_series_without_duplicate_or_time_shift(client,monkeypatch):
    api,session=client
    created=seed(api)
    real=conversion.existing_recurrence
    fixed=datetime.fromisoformat('2097-10-16T00:00:00+07:00')
    monkeypatch.setattr('app.commands.service.existing_recurrence',lambda request,tasks:real(request,tasks,now=fixed))
    speech='На следующей неделе есть тренировки во вторник, четверг и субботу вечером. Нужно сделать, чтобы они были повторяющиеся, каждый вторник, четверг и субботу. Плюс тренировки в воскресенье в 11 волейбол и 12 баскетбол тоже нужно сделать повторяющимися каждое воскресенье.'
    response=api.post('/api/commands',json={'text':speech,'timezone':'Asia/Tomsk'})
    assert response.status_code==200,response.text
    command=response.json();assert command['kind']=='command'
    assert len(command['operations'])==5
    assert all(o['instruction']['new_recurrence']=='weekly' for o in command['operations'])
    choices={'choices':[{'candidate':0,'scope':'series'} for o in command['operations']]}
    response=api.post('/api/commands/'+command['id']+'/execute',json=choices)
    assert response.status_code==200,response.text
    updated=response.json()['tasks'];assert {t['id'] for t in updated}=={t['id'] for t in created}
    for task in updated:
        before=next(t for t in created if t['id']==task['id'])
        assert task['start']==before['start'] and task['end']==before['end']
        assert task['description']==before['description']
        assert task['recurrence']['frequency']=='weekly'
    assert api.post('/api/commands/'+command['id']+'/execute',json=choices).json()==response.json()

def test_missing_weekday_does_not_partially_convert(client,monkeypatch):
    api,_=client;created=seed(api);real=conversion.existing_recurrence
    monkeypatch.setattr('app.commands.service.existing_recurrence',lambda request,tasks:real(request,tasks,now=datetime.fromisoformat('2097-10-16T00:00:00+07:00')))
    response=api.post('/api/commands',json={'text':'Нужно сделать тренировки в пятницу и воскресенье повторяющимися'})
    assert response.status_code==422,response.text
    assert 'пятница' in response.json()['detail']
    items=api.get('/api/tasks').json()
    assert all(not t['recurrence'] for t in items if t['id'] in {c['id'] for c in created})

def test_list_without_each_word():
    tasks=[TaskInput(title='Тренировка',start=f'2026-10-{day}T18:00:00+07:00',end=f'2026-10-{day}T19:00:00+07:00') for day in (20,22,24)]
    result=apply_spoken_recurrence(tasks,'Повторяющиеся тренировки во вторник, четверг и субботу в 18','Asia/Tomsk',datetime.fromisoformat('2026-10-16T10:00:00+07:00'))
    assert len(result)==3 and all(t.recurrence for t in result)
    assert {t.start.weekday() for t in result}=={1,3,5}

def test_planner_receives_series_once_instead_of_expanded_months(client,monkeypatch):
    from app.plans.ai import AIPlanner
    from app.plans.schemas import PlanOutput
    api,_=client
    response=api.post('/api/tasks',json={'title':'Проверка контекста серии','start':'2197-10-16T18:00:00+07:00','end':'2197-10-16T19:00:00+07:00','recurrence':{'frequency':'daily','timezone':'Asia/Tomsk'}})
    assert response.status_code==201,response.text
    task_id=response.json()['id'];captured=[]
    def generate(self,request,existing):
        captured.extend(existing)
        return PlanOutput(tasks=[TaskInput(title='Новый план',start='2198-10-16T10:00:00+07:00',end='2198-10-16T11:00:00+07:00')],note='Проверка')
    monkeypatch.setattr(AIPlanner,'generate',generate)
    response=api.post('/api/plans',json={'text':'Новая задача'})
    assert response.status_code==201,response.text
    assert len([t for t in captured if t['id']==task_id])==1
    assert next(t for t in captured if t['id']==task_id)['recurrence']['frequency']=='daily'

# Historical parser tests exercise the retained compatibility implementation explicitly.
import pytest
@pytest.fixture
def client(base_client,monkeypatch):
    from app.commands.service import CommandService
    monkeypatch.setattr(CommandService,'prepare',CommandService.prepare_legacy)
    return base_client
