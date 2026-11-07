import pytest
from test_api import client
from app.todos.schemas import Decision,Action
import app.todos.service as service

@pytest.mark.parametrize('category',['important_urgent','important_not_urgent','not_important_urgent','not_important_not_urgent'])
def test_category_persists_and_completion_keeps_it(client,category):
    api,_=client
    created=api.post('/api/todos',json={'title':'Дело','category':category})
    assert created.status_code==201
    task=created.json()
    changed=api.put('/api/todos/'+task['id'],json={'title':'Дело','completed':True})
    assert changed.json()['category']==category
    assert api.get('/api/todos').json()[0]['category']==category

def test_voice_category_update_and_stale_snapshot(client,monkeypatch):
    api,_=client
    task=api.post('/api/todos',json={'title':'Отчёт','category':'important_not_urgent'}).json()
    monkeypatch.setattr(service,'interpret',lambda *a:Decision(note='Срочно',actions=[Action(action='update',ref='T1',category='important_urgent')]))
    command=api.post('/api/todos/commands/prepare',json={'text':'Отчёт теперь срочный'}).json()
    assert api.post('/api/todos/commands/'+command['id']+'/execute').status_code==200
    assert api.get('/api/todos').json()[0]['category']=='important_urgent'
    command=api.post('/api/todos/commands/prepare',json={'text':'Отчёт срочный'}).json()
    api.put('/api/todos/'+task['id'],json={'title':'Отчёт','category':'not_important_not_urgent'})
    assert api.post('/api/todos/commands/'+command['id']+'/execute').status_code==409

def test_invalid_category_rejected(client):
    api,_=client
    assert api.post('/api/todos',json={'title':'Дело','category':'random'}).status_code==422


def test_missing_model_category_is_classified_separately(monkeypatch):
    import json,httpx
    from app.todos.ai import interpret
    calls=[]
    def post(url,**kwargs):
        calls.append(kwargs['json'])
        body=({'actions':[{'action':'create','title':'Отчёт','description':'Дедлайн сегодня'}],'note':'Добавить отчёт'} if len(calls)==1 else {'category':'important_urgent'})
        return httpx.Response(200,request=httpx.Request('POST',url),json={'message':{'content':json.dumps(body)}})
    monkeypatch.setattr(httpx,'post',post)
    result=interpret('Сдать рабочий отчёт сегодня',[])
    assert result.actions[0].category=='important_urgent'
    assert len(calls)==2
