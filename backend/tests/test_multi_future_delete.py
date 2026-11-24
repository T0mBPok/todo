from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest
from test_api import client
from app.tasks.models import Task
from app.tasks.service import TaskService
from app.commands.models import Command
from app.commands.schemas import Operation

ZONE = ZoneInfo('Asia/Tomsk')
def local(day, hour=13):
    return datetime(2026, 11, day, hour, 15, tzinfo=ZONE)

def seed(session, frequency):
    roots=[]
    for hour in [10, 13]:
        rule={'frequency':frequency, 'timezone':'Asia/Tomsk'}
        if frequency=='google':
            rule['rules']=['RRULE:FREQ=WEEKLY;COUNT=8', 'RDATE:20261230T061500Z']
        root=Task(title='1С',start=local(4,hour),end=local(4,hour)+timedelta(hours=1),recurrence=rule)
        session.add(root);roots.append(root)
    session.commit()
    return roots

def command(session, roots, day=25, create=False):
    events=TaskService(session).list(local(day,0).replace(minute=0),local(day,23))
    candidates=[event.model_dump(mode='json') for event in events if event.id in {root.id for root in roots}]
    operations=[{'instruction':Operation(operation='delete',target='1С').model_dump(),
                 'timezone':'Asia/Tomsk','candidates':candidates,'requires_confirmation':True}]
    if create:
        from uuid import uuid4
        from app.tasks.schemas import TaskRead
        event=TaskRead(id=uuid4(),title='ПО',start=local(day),end=local(day)+timedelta(hours=1))
        operations.append({'instruction':Operation(operation='create',target='ПО').model_dump(),
                           'timezone':'Asia/Tomsk','candidates':[event.model_dump(mode='json')]})
    row=Command(text='Удалить обе пары с выбранного дня',operations=operations,note='Проверить')
    session.add(row);session.commit()
    return row

@pytest.mark.parametrize('frequency',['daily','weekly','google'])
@pytest.mark.parametrize('browser_payload',[False,True])
def test_both_series_end_at_selected_day_and_keep_history(client,frequency,browser_payload):
    api,session=client
    roots=seed(session,frequency)
    row=command(session,roots,create=True)
    choices=[{'candidates':[0,1],'scope':'future'},{'candidate':0}]
    if browser_payload:choices[0]['candidate']=None
    result=api.post(f'/api/commands/{row.id}/execute',json={'choices':choices})
    assert result.status_code==200,result.text
    tasks=TaskService(session).list(local(1,0),local(30,23)+timedelta(days=45))
    history=[task for task in tasks if task.title=='1С']
    assert history and all(task.start<local(25,0).replace(minute=0) for task in history)
    expected=42 if frequency=='daily' else 6
    assert len(history)==expected
    assert len([task for task in tasks if task.title=='ПО'])==1
    assert api.post(f'/api/commands/{row.id}/execute',json={'choices':choices}).json()==result.json()

@pytest.mark.parametrize('scope',['occurrence','series'])
def test_both_candidates_support_existing_scopes(client,scope):
    api,session=client
    roots=seed(session,'weekly')
    row=command(session,roots)
    result=api.post(f'/api/commands/{row.id}/execute',json={'choices':[{'candidates':[0,1],'scope':scope}]})
    assert result.status_code==200,result.text
    tasks=TaskService(session).list(local(1,0),local(30,23))
    if scope=='series':assert tasks==[]
    else:
        assert len(tasks)==6
        assert all(task.start.astimezone(ZONE).day!=25 for task in tasks)

@pytest.mark.parametrize('indices',[[0,0],[-1],[99],[]])
def test_invalid_multiple_selection_never_changes_calendar(client,indices):
    api,session=client
    roots=seed(session,'weekly')
    row=command(session,roots)
    result=api.post(f'/api/commands/{row.id}/execute',json={'choices':[{'candidates':indices,'scope':'future'}]})
    assert result.status_code==422,result.text
    assert len(TaskService(session).list(local(1,0),local(30,23)))==8

def test_future_delete_removes_detached_future_occurrences_and_preserves_earlier_ones(client):
    api,session=client
    roots=seed(session,'weekly')
    root=roots[0]
    from app.recurrences.dao import RecurrenceDAO
    for original, moved in [(local(11,10),local(12,18)),(local(25,10),local(26,18))]:
        RecurrenceDAO(session).exclude(root.id,original)
        session.add(Task(title='Перенесённая',start=moved,end=moved+timedelta(hours=1),
                         series_parent_id=root.id,series_original_start=original))
    session.commit()
    result=api.delete(f'/api/tasks/{root.id}',params={'scope':'future','occurrence_start':local(18,10).isoformat()})
    assert result.status_code==204,result.text
    children=list(session.query(Task).filter(Task.series_parent_id==root.id))
    assert len(children)==1 and children[0].series_original_start==local(11,10)

def test_truncation_keeps_google_count_and_exdates():
    from app.recurrences.service import truncate_rules
    from dateutil.rrule import rrulestr
    lines=['RRULE:FREQ=WEEKLY;COUNT=2','EXDATE:20261111T061500Z']
    truncated=truncate_rules(lines,local(4),local(25,0),ZONE)
    schedule=rrulestr('\n'.join(truncated),dtstart=local(4),forceset=True)
    assert list(schedule)==[local(4)]

def test_future_scope_starts_at_first_selected_day_even_when_indices_reversed(client):
    api,session=client
    roots=seed(session,'weekly')[:1]
    events=[event for event in TaskService(session).list(local(11,0),local(25,23)) if event.id==roots[0].id]
    row=Command(text='С выбранного дня',note='',operations=[{
        'instruction':Operation(operation='delete',target='1С').model_dump(),
        'timezone':'Asia/Tomsk','candidates':[event.model_dump(mode='json') for event in events]}])
    session.add(row);session.commit()
    result=api.post(f'/api/commands/{row.id}/execute',json={'choices':[{'candidates':[2,0],'scope':'future'}]})
    assert result.status_code==200,result.text
    remaining=[event for event in TaskService(session).list(local(1,0),local(30,23)) if event.id==roots[0].id]
    assert len(remaining)==1 and remaining[0].start==local(4,10)

def test_future_deletion_rolls_back_both_series_when_replacement_conflicts(client):
    api,session=client
    roots=seed(session,'weekly')
    occupied=Task(title='Занято',start=local(25),end=local(25)+timedelta(hours=1))
    session.add(occupied);session.commit()
    row=command(session,roots,create=True)
    result=api.post(f'/api/commands/{row.id}/execute',json={'choices':[
        {'candidates':[0,1],'scope':'future'},{'candidate':0}]})
    assert result.status_code==409,result.text
    remaining=[event for event in TaskService(session).list(local(1,0),local(30,23)) if event.id in {root.id for root in roots}]
    assert len(remaining)==8

@pytest.mark.parametrize('zone_name',['America/New_York','Europe/Berlin'])
def test_cutoff_preserves_wall_clock_history_across_dst(zone_name):
    from app.recurrences.service import truncate_rules, instances
    from types import SimpleNamespace
    zone=ZoneInfo(zone_name)
    start=datetime(2026,10,4,13,tzinfo=zone)
    cutoff=datetime(2026,11,8,0,tzinfo=zone)
    lines=truncate_rules(['RRULE:FREQ=WEEKLY'],start,cutoff,zone)
    row=SimpleNamespace(start=start,end=start+timedelta(hours=1),is_all_day=False,
                        recurrence={'frequency':'google','timezone':zone_name,'rules':lines})
    values=list(instances(row,start,cutoff+timedelta(days=70)))
    assert len(values)==5
    assert all(begin<cutoff and begin.astimezone(zone).hour==13 for begin,_ in values)

def test_future_scope_at_first_occurrence_removes_whole_empty_series(client):
    api,session=client
    root=seed(session,'weekly')[0]
    result=api.delete(f'/api/tasks/{root.id}',params={'scope':'future','occurrence_start':local(4,10).isoformat()})
    assert result.status_code==204,result.text
    assert session.get(Task,root.id) is None

def test_null_single_selection_without_multiple_choice_is_rejected(client):
    api,session=client
    row=command(session,seed(session,'weekly'))
    result=api.post(f'/api/commands/{row.id}/execute',json={'choices':[{'candidate':None,'scope':'future'}]})
    assert result.status_code==422
    assert len(TaskService(session).list(local(1,0),local(30,23)))==8
