from test_api import client as base_client
from app.commands.matching import score_name,deletion_request
from app.commands.schemas import CommandRequest
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import pytest

@pytest.mark.parametrize('name',['пару в университете','пары в универе','пара университет','паре в университете'])
def test_inflections_and_aliases(name):
    assert score_name(name,'Пара в университете')==1
    assert score_name(name,'Тренировка в зале')==0

def test_correction_preserves_day_and_excludes_object():
    parsed=deletion_request(CommandRequest(text='Убери в субботу пару в университете. Ой, всё, кроме пары в университете.'))
    op=parsed.operations[0]
    assert op.all_matches and op.date_reference=='субботу'
    assert op.exclude_target=='пары в университете'
    assert op.target=='' and op.scope=='occurrence'

def add(api,title,day,hour,repeat=False):
    start=f'{day}T{hour:02}:00:00+07:00'
    response=api.post('/api/tasks',json={'title':title,'start':start,'end':f'{day}T{hour+1:02}:00:00+07:00','recurrence':{'frequency':'weekly','timezone':'Asia/Tomsk'} if repeat else None})
    assert response.status_code==201,response.text
    return response.json()

def test_delete_all_except_keeps_protected_task_other_day_and_future_repetitions(client):
    api,_=client
    kept=add(api,'Пара в университете','2197-10-14',13)
    removed=add(api,'Волейбол','2197-10-14',11,True)
    other=add(api,'Другое событие','2197-10-15',14)
    response=api.post('/api/commands',json={'text':'Убери 2197-10-14 пару в университете. Ой, всё, кроме пары в университете.'})
    assert response.status_code==200,response.text
    command=response.json();assert command['kind']=='command'
    assert len(command['operations'])==1
    op=command['operations'][0]
    assert op['requires_confirmation'] and op['candidates'][0]['id']==removed['id']
    result=api.post('/api/commands/'+command['id']+'/execute',json={'choices':[{'candidate':0}]})
    assert result.status_code==200,result.text
    items=api.get('/api/tasks',params={'start':'2197-10-14T00:00:00Z','end':'2197-10-30T00:00:00Z'}).json()
    assert any(t['id']==kept['id'] for t in items)
    assert any(t['id']==other['id'] for t in items)
    repeats=[t for t in items if t['id']==removed['id']]
    assert len(repeats)==2

def test_simple_deletion_finds_inflected_title_on_right_day(client):
    api,_=client
    first=add(api,'Пара в университете','2197-10-14',13)
    add(api,'Пара в университете','2197-10-15',13)
    response=api.post('/api/commands',json={'text':'Убери 2197-10-14 пару в университете'})
    assert response.status_code==200,response.text
    candidates=response.json()['operations'][0]['candidates']
    assert len(candidates)==1 and candidates[0]['id']==first['id']

def test_missing_exception_and_unbounded_bulk_cannot_delete(client):
    api,_=client
    add(api,'Тренировка','2197-10-14',18)
    response=api.post('/api/commands',json={'text':'Убери 2197-10-14 всё кроме пары в университете'})
    assert response.status_code==422 and 'Ничего не удалено' in response.json()['detail']
    response=api.post('/api/commands',json={'text':'Удали всё кроме тренировки'})
    assert response.status_code==422 and 'назовите день' in response.json()['detail']

@pytest.mark.parametrize('verb',['убрал','убрала','убрали','убирал','убирай','удалил','удалили','удалял','удали'])
def test_conversational_delete_forms_bypass_model(verb):
    request=CommandRequest(text=f'Э-э, короче, родной, смотри, мне надо, чтобы ты в субботу {verb} все задачи, кроме пары в университете.')
    parsed=deletion_request(request)
    assert parsed is not None
    op=parsed.operations[0]
    assert op.all_matches and op.date_reference=='субботу'
    assert score_name(op.exclude_target,'Пара в университете')==1
    assert 'волейбол' not in op.target

def test_exact_screenshot_phrase_does_not_call_model(client,monkeypatch):
    api,_=client
    zone=ZoneInfo('Asia/Tomsk');now=datetime.now(zone)
    saturday=(now+timedelta(days=(5-now.weekday())%7)).date().isoformat()
    kept=add(api,'Пара в университете',saturday,13)
    removed=add(api,'Валибол',saturday,11)
    def unexpected(*args):raise AssertionError('Deterministic deletion must not ask the model to invent targets')
    monkeypatch.setattr('app.commands.service.interpret',unexpected)
    response=api.post('/api/commands',json={'text':'Э-э, короче, родной, смотри, мне надо, чтобы ты в субботу убрал все задачи, кроме пары в университете.'})
    assert response.status_code==200,response.text
    command=response.json()
    assert len(command['operations'])==1
    assert command['operations'][0]['candidates'][0]['id']==removed['id']
    assert command['operations'][0]['requires_confirmation']
    assert kept['id'] not in [t['id'] for op in command['operations'] for t in op['candidates']]

@pytest.mark.parametrize('text',[
 'Убрал все задачи в субботу, кроме пары в университете. В субботу убери все задачи, кроме пары по пары в университете, всё остальное убери. Вот в эту субботу убери всё, кроме пары пары в университете. Всё, кроме пары в университете, надо убрать.',
 'В субботу убери всё кроме тренировки. Нет, кроме пары в университете.',
 'В субботу убери всё, кроме пары пары в университете, всё остальное убери.',
 'В субботу убери всё кроме пары в университете надо убрать',
])
def test_restatements_and_trailing_actions_do_not_become_exception_title(text):
    op=deletion_request(CommandRequest(text=text)).operations[0]
    assert op.date_reference=='субботу'
    assert score_name(op.exclude_target,'Пара в университете')==1
    assert len(op.exclude_target)<45

def test_repeated_screenshot_transcript_prepares_same_deletion_once(client):
    api,_=client
    kept=add(api,'Пара в университете','2197-10-14',13)
    removed=add(api,'Волейбол','2197-10-14',11)
    text='2197-10-14 убери все задачи, кроме пары в университете. Убери всё, кроме пары по пары в университете, всё остальное убери. Всё, кроме пары в университете, надо убрать.'
    response=api.post('/api/commands',json={'text':text})
    assert response.status_code==200,response.text
    operations=response.json()['operations']
    assert len(operations)==1
    assert operations[0]['candidates'][0]['id']==removed['id']
    assert operations[0]['requires_confirmation']

# Historical parser tests exercise the retained compatibility implementation explicitly.
import pytest
@pytest.fixture
def client(base_client,monkeypatch):
    from app.commands.service import CommandService
    monkeypatch.setattr(CommandService,'prepare',CommandService.prepare_legacy)
    return base_client
