import json
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import delete,select
from app.core import config
from app.core.database import SessionLocal,AccountSessionLocal
from app.google_sync.models import GoogleConnection,GoogleLink
from app.google_sync.service import automatic_sync
from app.main import app
from app.users.models import User
from app.tasks.models import Task
from app.todos.models import Todo
from app.recurrences.dao import RecurrenceDAO
from email_helpers import capture_mail,register_verified

class Google:
    def __init__(self):
        self.records={'event':{},'todo':{}}
        self.writes=[]
        self.serial=0
    def add(self,kind,key,**fields):
        self.serial+=1
        item={'id':key,'etag':'"v'+str(self.serial)+'"',**fields}
        self.records[kind][key]=item
        return item
    def __call__(self,request):
        if request.url.host=='oauth2.googleapis.com':
            return httpx.Response(200,json={'access_token':'mock-access'})
        assert request.headers['Authorization']=='Bearer mock-access'
        kind='event' if '/events' in request.url.path else 'todo'
        collection=self.records[kind]
        key=request.url.path.rsplit('/',1)[-1]
        listing=key in {'events','tasks'}
        if request.method=='GET':
            if listing:return httpx.Response(200,json={'items':deepcopy(list(collection.values())),'timeZone':'Asia/Tomsk'})
            return httpx.Response(200,json=deepcopy(collection[key])) if key in collection else httpx.Response(404)
        self.writes.append((request.method,kind,key))
        if request.method=='POST':
            value=json.loads(request.content)
            key=value.get('id') or 'todo'+str(self.serial+1)
            if key in collection:return httpx.Response(409)
            return httpx.Response(200,json=self.add(kind,key,**{name:value for name,value in value.items() if name!='id'}))
        if key not in collection:return httpx.Response(404)
        if request.headers.get('If-Match')!=collection[key]['etag']:return httpx.Response(412)
        if request.method=='DELETE':
            self.add(kind,key,**({'status':'cancelled'} if kind=='event' else {'deleted':True}))
            return httpx.Response(204)
        assert request.method=='PATCH'
        value={**collection[key],**json.loads(request.content)}
        value.pop('id');value.pop('etag')
        return httpx.Response(200,json=self.add(kind,key,**value))

@pytest.fixture
def exchange(monkeypatch):
    inbox=capture_mail(monkeypatch)
    monkeypatch.setattr(config,'GOOGLE_CLIENT_ID','test')
    monkeypatch.setattr(config,'GOOGLE_CLIENT_SECRET','test')
    key=Fernet.generate_key()
    monkeypatch.setattr(config,'GOOGLE_TOKEN_KEY',key.decode())
    google=Google()
    real=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(google),**kw))
    options={'base_url':config.PUBLIC_ORIGIN,'headers':{'Origin':config.PUBLIC_ORIGIN}}
    emails=[uuid4().hex+'@example.com' for _ in range(2)]
    try:
        with TestClient(app,**options) as alice,TestClient(app,**options) as bob:
            for client,email in zip((alice,bob),emails):
                assert register_verified(client,email,'local-google-test-password',inbox).status_code==200
            with SessionLocal.begin() as db:
                owner=db.scalar(select(User.id).where(User.email==emails[0]))
                db.add(GoogleConnection(owner_id=owner,subject='mock-google',refresh_token=Fernet(key).encrypt(b'mock-refresh').decode(),sync_enabled=True))
            def run():
                with AccountSessionLocal(info={'owner_id':owner}) as db:return automatic_sync(db)
            yield alice,bob,google,owner,run
    finally:
        with SessionLocal.begin() as db:db.execute(delete(User).where(User.email.in_(emails)))

def local_event(client,title='Встреча',day=1,recurrence=None):
    payload={'title':title,'start':f'2098-12-{day:02}T10:00:00+07:00','end':f'2098-12-{day:02}T11:00:00+07:00','category':'important_not_urgent','recurrence':recurrence}
    response=client.post('/api/tasks',json=payload)
    assert response.status_code==201,response.text
    return response.json()

def test_automatic_exchange_updates_both_sides_without_duplicates_and_propagates_deletions(exchange):
    alice,bob,google,owner,run=exchange
    google.add('event','remote',summary='Из Google',start={'dateTime':'2098-12-02T10:00:00+07:00'},end={'dateTime':'2098-12-02T11:00:00+07:00'})
    google.add('todo','remote-todo',title='Дело из Google',status='needsAction')
    local=local_event(alice)
    todo=alice.post('/api/todos',json={'title':'Локальное дело','category':'important_not_urgent'}).json()
    result=run()
    assert result['changed']==4 and result['conflicts']==0
    assert len(alice.get('/api/tasks').json())==2
    assert len(alice.get('/api/todos').json())==2
    assert bob.get('/api/tasks').json()==[]
    assert not bob.get('/api/google/status').json()['connected']
    assert run()['changed']==0
    assert len(google.writes)==2
    remote=google.records['event']['remote']
    google.add('event','remote',**{**{k:v for k,v in remote.items() if k not in {'id','etag'}},'summary':'Изменено в Google'})
    assert run()['changed']==1
    imported=next(row for row in alice.get('/api/tasks').json() if row['title']=='Изменено в Google')
    assert alice.delete('/api/tasks/'+local['id']).status_code==204
    assert alice.delete('/api/todos/'+todo['id']).status_code==204
    assert run()['changed']==2
    google.add('event','remote',status='cancelled')
    google.add('todo','remote-todo',deleted=True)
    assert run()['changed']==2
    assert alice.get('/api/tasks').json()==[]
    assert alice.get('/api/todos').json()==[]
    assert run()['changed']==0
    assert alice.get('/api/google/status').json()['last_synced_at']

def test_simultaneous_edits_require_an_explicit_version_choice_and_are_account_scoped(exchange):
    alice,bob,google,owner,run=exchange
    item=local_event(alice)
    assert run()['changed']==1
    remote_id=item['id'].replace('-','')
    remote=google.records['event'][remote_id]
    google.add('event',remote_id,**{**{k:v for k,v in remote.items() if k not in {'id','etag'}},'summary':'Версия Google'})
    assert alice.put('/api/tasks/'+item['id'],json={**{k:item[k] for k in ('start','end','category')},'title':'Версия Импульса'}).status_code==200
    assert run()['conflicts']==1
    assert alice.get('/api/tasks').json()[0]['title']=='Версия Импульса'
    assert google.records['event'][remote_id]['summary']=='Версия Google'
    conflicts=alice.get('/api/google/conflicts').json()
    assert len(conflicts)==1
    assert bob.get('/api/google/conflicts').json()==[]
    payload={'local_id':item['id'],'kind':'event','source':'local'}
    assert bob.post('/api/google/resolve',json=payload).status_code==409
    assert alice.post('/api/google/resolve',json=payload).status_code==200
    assert google.records['event'][remote_id]['summary']=='Версия Импульса'
    assert run()['conflicts']==0
    # A remote deletion must not silently erase a locally modified event.
    assert alice.put('/api/tasks/'+item['id'],json={**{k:item[k] for k in ('start','end','category')},'title':'Сохранить правку'}).status_code==200
    google.add('event',remote_id,status='cancelled')
    run()
    assert alice.get('/api/tasks').json()
    assert alice.post('/api/google/resolve',json={**payload,'source':'remote'}).status_code==200
    assert alice.get('/api/tasks').json()==[]

def test_repeating_all_day_and_excluded_occurrences_are_exported(exchange):
    alice,bob,google,owner,run=exchange
    item=local_event(alice,recurrence={'frequency':'weekly','timezone':'Asia/Tomsk'})
    with AccountSessionLocal(info={'owner_id':owner}) as db:
        start=datetime.fromisoformat(item['start'].replace('Z','+00:00'))
        RecurrenceDAO(db).exclude(item['id'],start+timedelta(days=7))
        db.add(Task(title='Весь день',start=datetime(2098,12,4,tzinfo=timezone.utc),end=datetime(2098,12,5,tzinfo=timezone.utc),is_all_day=True))
        db.commit()
    assert run()['changed']==2
    exported=google.records['event'][item['id'].replace('-','')]
    assert exported['start']['timeZone']=='Asia/Tomsk'
    assert exported['recurrence'][0]=='RRULE:FREQ=WEEKLY'
    assert exported['recurrence'][1].startswith('EXDATE:20981208T030000Z')
    all_day=next(value for value in google.records['event'].values() if value.get('summary')=='Весь день')
    assert all_day['start']=={'date':'2098-12-04'}
    assert run()['changed']==0

def test_bulk_auto_exchange_continues_in_batches_and_pause_stops_it(exchange):
    alice,bob,google,owner,run=exchange
    with AccountSessionLocal(info={'owner_id':owner}) as db:
        db.add_all([Todo(title='Задача '+str(i)) for i in range(35)])
        db.commit()
    assert run()['partial'] is True
    assert run()['changed']==10
    assert run()['changed']==0
    assert len(google.records['todo'])==35
    assert alice.post('/api/google/auto-sync',json={'enabled':False}).json()['auto_sync'] is False
    assert run() is None
    assert alice.post('/api/google/sync-now').status_code==409
    assert bob.post('/api/google/auto-sync',json={'enabled':True}).status_code==409

def test_background_scheduler_retries_safely_without_account_data_in_error(exchange,monkeypatch):
    alice,bob,google,owner,run=exchange
    from app.google_sync import worker
    calls=[]
    def failing(db):
        calls.append(db.info['owner_id'])
        raise RuntimeError('private-token private-user-address')
    monkeypatch.setattr(worker,'automatic_sync',failing)
    worker.run_due_syncs()
    assert calls==[owner]
    with SessionLocal() as db:
        connection=db.get(GoogleConnection,owner)
        assert connection.next_sync_at>datetime.now(timezone.utc)
        assert 'private' not in connection.sync_error
        assert connection.sync_error

def test_remote_version_can_restore_a_locally_deleted_record(exchange):
    alice,bob,google,owner,run=exchange
    item=local_event(alice)
    run()
    remote_id=item['id'].replace('-','')
    remote=google.records['event'][remote_id]
    assert alice.delete('/api/tasks/'+item['id']).status_code==204
    google.add('event',remote_id,**{**{k:v for k,v in remote.items() if k not in {'id','etag'}},'summary':'Сохранить версию Google'})
    run()
    assert len(alice.get('/api/google/conflicts').json())==1
    result=alice.post('/api/google/resolve',json={'local_id':item['id'],'kind':'event','source':'remote'})
    assert result.status_code==200,result.text
    assert alice.get('/api/tasks').json()[0]['title']=='Сохранить версию Google'
    assert run()['changed']==0

def test_local_version_can_restore_an_event_deleted_in_google(exchange):
    alice,bob,google,owner,run=exchange
    item=local_event(alice)
    run()
    remote_id=item['id'].replace('-','')
    assert alice.put('/api/tasks/'+item['id'],json={**{k:item[k] for k in ('start','end','category')},'title':'Оставить в календаре'}).status_code==200
    google.add('event',remote_id,status='cancelled')
    run()
    response=alice.post('/api/google/resolve',json={'local_id':item['id'],'kind':'event','source':'local'})
    assert response.status_code==200,response.text
    copies=[value for value in google.records['event'].values() if value.get('summary')=='Оставить в календаре']
    assert len(copies)==1 and copies[0]['id']!=remote_id
    assert run()['changed']==0

def test_remote_edit_can_replace_the_local_version_without_changing_its_id(exchange):
    alice,bob,google,owner,run=exchange
    item=local_event(alice)
    run()
    remote_id=item['id'].replace('-','')
    remote=google.records['event'][remote_id]
    assert alice.put('/api/tasks/'+item['id'],json={**{k:item[k] for k in ('start','end','category')},'title':'Локальная версия'}).status_code==200
    google.add('event',remote_id,**{**{k:v for k,v in remote.items() if k not in {'id','etag'}},'summary':'Новая версия Google'})
    run()
    response=alice.post('/api/google/resolve',json={'local_id':item['id'],'kind':'event','source':'remote'})
    assert response.status_code==200,response.text
    row=alice.get('/api/tasks').json()[0]
    assert row['id']==item['id'] and row['title']=='Новая версия Google'
    assert run()['changed']==0

def test_parallel_sync_is_skipped_while_another_process_holds_the_account_lock(exchange):
    alice,bob,google,owner,run=exchange
    from app.core.database import engine
    from sqlalchemy import text
    key=-1-(owner.int & ((1<<63)-1))
    with engine.begin() as lock:
        lock.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':key})
        assert run() is None
        assert not google.writes

def test_moving_a_google_weekly_series_updates_weekdays_until_and_exceptions():
    from types import SimpleNamespace
    from app.google_sync.service import export_recurrence_lines
    old=datetime(2026,11,17,3,tzinfo=timezone.utc)
    shifted=datetime(2026,11,18,5,tzinfo=timezone.utc)
    row=SimpleNamespace(start=shifted,recurrence={'frequency':'google','timezone':'Asia/Tomsk','source_start':old.isoformat(),
        'rules':['RRULE:FREQ=WEEKLY;BYDAY=TU;UNTIL=20261229T030000Z','EXDATE:20261124T030000Z']})
    lines=export_recurrence_lines(row)
    assert lines==['RRULE:FREQ=WEEKLY;BYDAY=WE;UNTIL=20261230T050000Z','EXDATE:20261125T050000Z']
