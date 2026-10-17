from test_api import client as base_client,task
from app.commands.schemas import Interpretation,Operation
import app.commands.service as service
def prepare(api,monkeypatch,**kwargs):
    op=Operation(operation='update',target='Встреча',date_reference='2098-11-12',**kwargs)
    monkeypatch.setattr(service,'interpret',lambda *a:Interpretation(intent='manage',operations=[op]))
    result=api.post('/api/commands',json={'text':'команда'})
    assert result.status_code==200,result.text
    return result.json()
def execute(api,command,scope=None):
    return api.post('/api/commands/'+command['id']+'/execute',json={'choices':[{'candidate':0,'scope':scope}]})
def test_description_and_move_idempotent(client,monkeypatch):
    api,_=client
    created=api.post('/api/tasks',json={**task(),'description':'Документы'}).json()
    cmd=prepare(api,monkeypatch,description='Взять паспорт',append_description=True,new_time='14:00')
    response=execute(api,cmd);assert response.status_code==200,response.text
    updated=response.json()['tasks'][0]
    assert updated['description']=='Документы\nВзять паспорт'
    assert updated['start'].endswith('07:00:00Z')
    assert execute(api,cmd).json()==response.json()
def test_ambiguous_and_stale(client,monkeypatch):
    api,_=client
    first=api.post('/api/tasks',json=task()).json()
    api.post('/api/tasks',json=task('12:00','13:00'))
    cmd=prepare(api,monkeypatch,new_title='Обсуждение')
    assert len(cmd['operations'][0]['candidates'])==2
    api.put('/api/tasks/'+first['id'],json={**task(),'title':'Уже изменено'})
    assert execute(api,cmd).status_code==409
def test_edit_single_recurring_and_delete_series(client,monkeypatch):
    api,_=client
    rule={'frequency':'weekly','timezone':'Asia/Tomsk'}
    created=api.post('/api/tasks',json={**task(), 'recurrence':rule}).json()
    cmd=prepare(api,monkeypatch,new_time='14:00',description='Форма')
    assert execute(api,cmd).status_code==422
    response=execute(api,cmd,'occurrence');assert response.status_code==200,response.text
    child=response.json()['tasks'][0]
    assert child['series_parent_id']==created['id']
    occurrences=api.get('/api/tasks',params={'start':'2098-11-12T00:00:00Z','end':'2098-11-27T00:00:00Z'}).json()
    assert len([t for t in occurrences if t['id']==created['id']])==2
    assert api.delete('/api/tasks/'+created['id'],params={'scope':'series'}).status_code==204
    assert api.delete('/api/tasks/'+child['id']).status_code==404
def test_series_edit(client):
    api,_=client
    data={**task(),'recurrence':{'frequency':'weekly','timezone':'Asia/Tomsk'}}
    created=api.post('/api/tasks',json=data).json()
    changed={**data, 'start':'2098-11-19T14:00:00+07:00','end':'2098-11-19T15:00:00+07:00','description':'Для всех'}
    response=api.put('/api/tasks/'+created['id'],params={'scope':'series','occurrence_start':'2098-11-19T10:00:00+07:00'},json=changed)
    assert response.status_code==200,response.text
    assert response.json()['start']=='2098-11-12T07:00:00Z'
    assert response.json()['description']=='Для всех'

def test_model_cannot_invent_source_filters(monkeypatch):
    import json,httpx
    from app.commands.ai import interpret
    from app.commands.schemas import CommandRequest
    def fake(url,**kwargs):
        assert kwargs['json']['format']['properties']['intent']['const']=='manage'
        op=Operation(operation='update',target='Тренировка',date_reference='завтра',time_reference='13:00',description='Взять воду')
        return httpx.Response(200,request=httpx.Request('POST',url),json={'message':{'content':Interpretation(intent='manage',operations=[op]).model_dump_json()}})
    monkeypatch.setattr(httpx,'post',fake)
    op=interpret(CommandRequest(text='Добавь в описание тренировки взять воду'),['Тренировка']).operations[0]
    assert op.date_reference is None and op.time_reference is None
def test_command_conflict_rolls_back(client,monkeypatch):
    api,_=client
    original=api.post('/api/tasks',json=task()).json()
    api.post('/api/tasks',json=task('12:00','13:00'))
    cmd=prepare(api,monkeypatch,new_time='12:30')
    assert execute(api,cmd).status_code==409
    remaining=api.get('/api/tasks').json()
    assert next(t for t in remaining if t['id']==original['id'])['start']==original['start']

# Historical parser tests exercise the retained compatibility implementation explicitly.
import pytest
@pytest.fixture
def client(base_client,monkeypatch):
    from app.commands.service import CommandService
    monkeypatch.setattr(CommandService,'prepare',CommandService.prepare_legacy)
    return base_client
