from datetime import datetime,timedelta,timezone
from test_api import client
from app.commands.grounded_ai import Decision,SelectedOperation
from app.tasks.schemas import TaskRead


def test_bulk_delete_expands_model_alternatives_and_keeps_excluded_item(client,monkeypatch):
    api,db=client
    events=[]
    for i in range(3):
        start=datetime(2098,11,12,10,tzinfo=timezone.utc)+timedelta(days=i)
        response=api.post('/api/tasks',json={'title':f'Event {i}','start':start.isoformat(),'end':(start+timedelta(hours=1)).isoformat()})
        assert response.status_code==201
        events.append(response.json())
    mapping={f'E{i}':TaskRead.model_validate(event) for i,event in enumerate(events)}
    monkeypatch.setattr('app.commands.context.calendar_context',lambda *args:({},mapping))
    monkeypatch.setattr('app.commands.grounded_ai.interpret_calendar',lambda *args:Decision(intent='manage',note='Удалить все',operations=[SelectedOperation(action='delete',refs=list(mapping),selection='one')]))
    prepared=api.post('/api/commands',json={'text':'Удали все события следующей недели','timezone':'UTC'})
    assert prepared.status_code==200,prepared.text
    command=prepared.json()
    assert len(command['operations'])==3
    result=api.post(f"/api/commands/{command['id']}/execute",json={'choices':[{'candidate':0},{'candidate':0,'skip':True},{'candidate':0}]})
    assert result.status_code==200,result.text
    assert [task['id'] for task in api.get('/api/tasks').json()]==[events[1]['id']]


def test_clear_calendar_keeps_excluded_series_and_event(client):
    from app.users.models import User
    from app.tasks.models import Task
    api,db=client
    user=User(email='exclude@example.com',password_hash='fixture')
    db.add(user);db.flush();db.info['owner_id']=user.id
    start=datetime(2098,11,12,10,tzinfo=timezone.utc)
    rows=[Task(owner_id=user.id,title=f'Item {i}',start=start+timedelta(days=i),end=start+timedelta(days=i,hours=1),recurrence={'frequency':'weekly','timezone':'UTC'} if i==2 else None) for i in range(3)]
    db.add_all(rows);db.commit()
    prepared=api.post('/api/commands',json={'text':'Удали все дела'})
    assert prepared.status_code==200,prepared.text
    draft=prepared.json()
    assert len(draft['items'])==3
    from app.commands.models import Command
    from uuid import UUID
    db.get(Command,UUID(draft['id'])).owner_id=user.id
    db.commit()
    result=api.post(f"/api/commands/{draft['id']}/clear-calendar",json={'choices':[{'series_id':str(rows[2].id),'scope':'series'}],'exclude_ids':[str(rows[1].id),str(rows[2].id)]})
    assert result.status_code==200,result.text
    assert result.json()['deleted']==1
    from sqlalchemy import select
    assert set(db.scalars(select(Task.id)))=={rows[1].id,rows[2].id}
