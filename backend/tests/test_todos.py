from test_api import client
from app.todos.schemas import Decision,Action
import app.todos.service as service
def test_plain_task_needs_no_date_and_can_be_completed(client):
    api,_=client
    response=api.post('/api/todos',json={'title':'Купить продукты','description':'Молоко и хлеб'})
    assert response.status_code==201,response.text
    task=response.json();assert 'start' not in task and not task['completed']
    changed=api.put('/api/todos/'+task['id'],json={'title':task['title'],'description':task['description'],'completed':True})
    assert changed.status_code==200 and changed.json()['completed']
    assert api.delete('/api/todos/'+task['id']).status_code==204
    assert api.get('/api/todos').json()==[]

def test_voice_multiple_tasks_idempotent_and_separate_from_calendar(client,monkeypatch):
    api,_=client
    monkeypatch.setattr(service,'interpret',lambda *a:Decision(note='Две задачи',actions=[Action(action='create',title='Купить продукты'),Action(action='create',title='Закончить отчёт',description='Проверить расчёты')]))
    command=api.post('/api/todos/commands/prepare',json={'text':'Надо купить продукты и закончить отчёт, проверить расчёты'}).json()
    assert len(command['operations'])==2 and not command['requires_confirmation']
    response=api.post('/api/todos/commands/'+command['id']+'/execute')
    assert response.status_code==200,response.text
    assert api.post('/api/todos/commands/'+command['id']+'/execute').json()==response.json()
    assert len(api.get('/api/todos').json())==2
    assert api.get('/api/tasks').json()==[]

def test_voice_targets_existing_todo_and_delete_requires_confirmation(client,monkeypatch):
    api,_=client
    task=api.post('/api/todos',json={'title':'Отчёт'}).json()
    def interpret(text,context,history=None):
        assert context[0]['title']=='Отчёт'
        return Decision(note='Завершить отчёт',actions=[Action(action='complete',ref=context[0]['ref'])])
    monkeypatch.setattr(service,'interpret',interpret)
    command=api.post('/api/todos/commands/prepare',json={'text':'Отчёт сделал'}).json()
    assert api.post('/api/todos/commands/'+command['id']+'/execute').status_code==200
    assert api.get('/api/todos').json()[0]['completed']
    monkeypatch.setattr(service,'interpret',lambda *a:Decision(note='Удалить отчёт',actions=[Action(action='delete',ref='T1')]))
    command=api.post('/api/todos/commands/prepare',json={'text':'Удали отчёт'}).json()
    assert command['requires_confirmation']
    assert len(api.get('/api/todos').json())==1
    assert api.post('/api/todos/commands/'+command['id']+'/execute').status_code==200
    assert api.get('/api/todos').json()==[]

def test_unknown_target_and_stale_snapshot_rejected(client,monkeypatch):
    api,_=client
    monkeypatch.setattr(service,'interpret',lambda *a:Decision(note='Удалить',actions=[Action(action='delete',ref='FAKE')]))
    assert api.post('/api/todos/commands/prepare',json={'text':'Удали'}).status_code==502
    task=api.post('/api/todos',json={'title':'Отчёт'}).json()
    monkeypatch.setattr(service,'interpret',lambda *a:Decision(note='Удалить',actions=[Action(action='delete',ref='T1')]))
    command=api.post('/api/todos/commands/prepare',json={'text':'Удали отчёт'}).json()
    api.put('/api/todos/'+task['id'],json={'title':'Другой отчёт'})
    assert api.post('/api/todos/commands/'+command['id']+'/execute').status_code==409
    assert api.get('/api/todos').json()[0]['title']=='Другой отчёт'
