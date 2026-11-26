import json
from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import select

from app.core import config
from app.core.database import SessionLocal
from app.google_sync import tasks_mcp
from app.google_sync.models import GoogleConnection, GoogleLink
from app.google_sync.service import incoming
from test_google_auto_sync import exchange, Google


@pytest.fixture
def mcp_exchange(exchange, monkeypatch):
    alice, bob, google, owner, run = exchange
    monkeypatch.setattr(config, 'GOOGLE_TASKS_MCP_CLIENT_ID', 'mcp-client')
    monkeypatch.setattr(config, 'GOOGLE_TASKS_MCP_CLIENT_SECRET', 'mcp-secret')
    google.mcp = {}
    google.mcp_writes = []
    google.mcp_subject = 'mock-google'
    google.mcp_status = 200
    google.mcp_sse = False
    google.mcp_tool_error = None
    original = Google.__call__

    def request(self, request):
        if request.url.host == 'oauth2.googleapis.com':
            fields = parse_qs(request.content.decode())
            if fields.get('client_id') == ['mcp-client']:
                assert fields['client_secret'] == ['mcp-secret']
                return httpx.Response(200, json={'access_token': 'mcp-access', 'refresh_token': 'mcp-refresh',
                                               'scope': 'openid https://www.googleapis.com/auth/tasks'})
        if request.url.host == 'openidconnect.googleapis.com' and request.headers.get('Authorization') == 'Bearer mcp-access':
            return httpx.Response(200, json={'sub': self.mcp_subject})
        if request.url.host != 'tasksmcp.googleapis.com':
            return original(self, request)
        assert request.headers['Authorization'] == 'Bearer mcp-access'
        assert request.headers['accept'] == 'application/json, text/event-stream'
        if self.mcp_status != 200:
            return httpx.Response(self.mcp_status)
        value = json.loads(request.content)
        name, args = value['params']['name'], value['params']['arguments']
        if self.mcp_tool_error:
            return httpx.Response(200, json={'jsonrpc': '2.0', 'id': 1, 'result': {
                'isError': True, 'content': [{'type': 'text', 'text': self.mcp_tool_error}]}})
        if name == 'list_tasks':
            assert args['filter']['state'] == 'ALL'
            data = {'tasks': deepcopy(list(self.mcp.values()))}
        elif name == 'get_task':
            data = deepcopy(self.mcp[args['taskId']])
        else:
            self.mcp_writes.append((name, deepcopy(args)))
            key = args.get('taskId') or 'mcp-created-' + str(len(self.mcp_writes))
            data = {**self.mcp.get(key, {}), **args, 'id': key, 'lastModified': str(len(self.mcp_writes))}
            data.pop('taskId', None)
            if name in {'complete_task', 'uncomplete_task'}:
                data['completed'] = name == 'complete_task'
            elif name == 'delete_task':
                assert not args['deleteSeries']
                data['deleted'] = True
            self.mcp[key] = deepcopy(data)
        result = {'jsonrpc': '2.0', 'id': 1, 'result': {'structuredContent': data}}
        if self.mcp_sse:
            return httpx.Response(200, text='event: message\ndata: ' + json.dumps(result) + '\n\n',
                                  headers={'content-type': 'text/event-stream'})
        return httpx.Response(200, json=result)

    monkeypatch.setattr(Google, '__call__', request)

    def connect(client=alice):
        result = client.post('/api/google/tasks-mcp/connect')
        assert result.status_code == 200, result.text
        params = parse_qs(urlsplit(result.json()['url']).query)
        assert params['client_id'] == ['mcp-client']
        assert 'calendar' not in params['scope'][0]
        assert params['access_type'] == ['offline']
        assert params['redirect_uri'] == [config.PUBLIC_ORIGIN + '/api/google/callback']
        return client.get('/api/google/callback', params={'state': params['state'][0], 'code': 'mcp-code'}, follow_redirects=False)

    yield alice, bob, google, owner, run, connect


def test_separate_oauth_requires_same_google_account_and_keeps_calendar_grant(mcp_exchange):
    alice, bob, google, owner, run, connect = mcp_exchange
    assert bob.post('/api/google/tasks-mcp/connect').status_code == 409
    assert alice.post('/api/google/tasks-mcp/connect', headers={'Origin': 'https://wrong.example'}).status_code == 403
    google.mcp_subject = 'wrong-account'
    assert 'google=error' in connect().headers['location']
    assert not alice.get('/api/google/status').json()['tasks_mcp_connected']
    google.mcp_subject = 'mock-google'
    assert 'google=connected' in connect().headers['location']
    with SessionLocal() as db:
        conn = db.get(GoogleConnection, owner)
        assert conn.mcp_refresh_token and conn.mcp_refresh_token != conn.refresh_token
        assert 'mcp-refresh' not in conn.mcp_refresh_token
    assert not bob.get('/api/google/status').json()['tasks_mcp_connected']
    assert run()['conflicts'] == 0
    assert alice.post('/api/google/disconnect').status_code == 204
    assert not alice.get('/api/google/status').json()['tasks_mcp_connected']


def test_rejected_mcp_access_does_not_switch_existing_sync(mcp_exchange):
    alice, bob, google, owner, run, connect = mcp_exchange
    google.mcp_status = 403
    assert 'google=error' in connect().headers['location']
    assert not alice.get('/api/google/status').json()['tasks_mcp_connected']
    assert run()['conflicts'] == 0


def test_preview_gate_explains_rollout_and_preserves_rest_sync(mcp_exchange):
    alice, bob, google, owner, run, connect = mcp_exchange
    google.mcp_tool_error = ('Access to this tool requires that your Google Cloud project (123456789012) '
                            'is enrolled in the Google Workspace Developer Preview Program. '
                            'Please see https://developers.google.com/workspace/preview')
    response = connect()
    params = parse_qs(urlsplit(response.headers['location']).query)
    assert params['google'] == ['error']
    assert 'проекта 123456789012' in params['detail'][0]
    assert 'Developer Preview Program' in params['detail'][0]
    assert 'до 10 дней' in params['detail'][0]
    assert 'не означает, что нужно покупать' in params['detail'][0]
    assert 'Подайте заявку' not in params['detail'][0]
    assert not alice.get('/api/google/status').json()['tasks_mcp_connected']
    assert run()['conflicts'] == 0


def test_unknown_mcp_error_does_not_expose_external_payloads():
    message = tasks_mcp.tool_error({'content': [{'type': 'text', 'text': 'sensitive-external-payload'}]})
    assert 'sensitive-external-payload' not in message


def test_mcp_dates_time_deadline_roundtrip_completion_and_deletion(mcp_exchange):
    alice, bob, google, owner, run, connect = mcp_exchange
    google.mcp['opaque:id/1'] = {'id': 'opaque:id/1', 'title': 'Из Google', 'description': 'Детали',
        'scheduledDate': '2098-12-10', 'scheduledTime': '09:30:00', 'timeZone': 'Asia/Tomsk',
        'deadlineDate': '2098-12-12', 'taskListId': 'secondary', 'lastModified': 'v1'}
    assert 'connected' in connect().headers['location']
    google.mcp_sse = True
    assert run()['changed'] == 1
    row = alice.get('/api/todos').json()[0]
    assert row['scheduled_at'] == '2098-12-10T02:30:00Z'
    assert row['deadline_date'] == '2098-12-12'
    assert row['deadline_at'] is None
    assert bob.get('/api/todos').json() == []
    payload = {key: row[key] for key in ('title', 'description', 'timezone', 'scheduled_date', 'scheduled_at', 'deadline_date')}
    payload.update(scheduled_at='2098-12-10T06:15:00Z', deadline_at='2098-12-12T10:00:00Z')
    assert alice.put('/api/todos/' + row['id'], json=payload).status_code == 200
    assert run()['changed'] == 1
    assert google.mcp_writes[-1] == ('update_task', {'taskId': 'opaque:id/1', 'scheduledTime': '13:15:00', 'timeZone': 'Asia/Tomsk'})
    google.mcp['opaque:id/1'].update(title='Правка Google', lastModified='v3')
    assert run()['changed'] == 1
    row = alice.get('/api/todos').json()[0]
    assert row['deadline_at'] == '2098-12-12T10:00:00Z'
    payload.update(title=row['title'], scheduled_date=None, scheduled_at=None, deadline_date=None, deadline_at=None, completed=True)
    assert alice.put('/api/todos/' + row['id'], json=payload).status_code == 200
    assert run()['changed'] == 1
    assert google.mcp['opaque:id/1']['scheduledDate'] == ''
    assert google.mcp['opaque:id/1']['scheduledTime'] == ''
    assert google.mcp['opaque:id/1']['deadlineDate'] == ''
    assert google.mcp_writes[-1][0] == 'complete_task'
    assert alice.delete('/api/todos/' + row['id']).status_code == 204
    assert run()['changed'] == 1
    assert google.mcp_writes[-1][0] == 'delete_task'
    assert run()['changed'] == 0


def test_migrate_rest_links_without_duplicates_and_import_precise_time(mcp_exchange):
    alice, bob, google, owner, run, connect = mcp_exchange
    google.add('todo', 'rest-id', title='Раньше REST', notes='Описание', status='needsAction',
               due='2098-12-10T00:00:00Z', webViewLink='https://tasks.google.com/task/unique')
    assert run()['changed'] == 1
    old = alice.get('/api/todos').json()[0]
    google.mcp['new-id'] = {'id': 'new-id', 'title': 'Раньше REST', 'description': 'Описание',
        'scheduledDate': '2098-12-10', 'scheduledTime': '10:00:00', 'timeZone': 'Asia/Tomsk',
        'link': 'https://tasks.google.com/task/unique', 'lastModified': 'v1'}
    connect()
    assert run()['changed'] == 1
    rows = alice.get('/api/todos').json()
    assert len(rows) == 1 and rows[0]['id'] == old['id']
    assert rows[0]['scheduled_at'] == '2098-12-10T03:00:00Z'
    assert google.mcp_writes == []
    assert run()['changed'] == 0
    assert alice.get('/api/google/status').json()['tasks_mcp_migrated']


def test_migration_ambiguous_records_pause_without_writes(mcp_exchange):
    alice, bob, google, owner, run, connect = mcp_exchange
    google.add('todo', 'rest-id', title='Одинаковая', status='needsAction')
    run()
    google.mcp = {key: {'id': key, 'title': 'Одинаковая', 'lastModified': 'v1'} for key in ('one', 'two')}
    connect()
    result = run()
    assert result['partial'] and google.mcp_writes == []
    assert len(alice.get('/api/todos').json()) == 1
    status = alice.get('/api/google/status').json()
    assert 'неоднозначные' in status['sync_error']
    assert not status['tasks_mcp_migrated']


def test_mcp_conflicts_local_remote_choices_and_remote_delete(mcp_exchange):
    alice, bob, google, owner, run, connect = mcp_exchange
    google.mcp['one'] = {'id': 'one', 'title': 'Начало', 'lastModified': 'v1'}
    connect()
    run()
    row = alice.get('/api/todos').json()[0]
    alice.put('/api/todos/' + row['id'], json={'title': 'Локально', 'scheduled_date': '2098-12-11'})
    google.mcp['one'].update(title='Удалённо', scheduledDate='2098-12-12', lastModified='v2')
    assert run()['conflicts'] == 1
    conflicts = alice.get('/api/google/conflicts').json()
    assert len(conflicts) == 1 and conflicts[0]['kind'] == 'todo'
    choice = {'local_id': row['id'], 'kind': 'todo', 'source': 'remote'}
    assert bob.post('/api/google/resolve', json=choice).status_code == 409
    assert alice.post('/api/google/resolve', json=choice).status_code == 200
    row = alice.get('/api/todos').json()[0]
    assert row['title'] == 'Удалённо' and row['scheduled_date'] == '2098-12-12'
    alice.put('/api/todos/' + row['id'], json={'title': 'Локальный выбор'})
    google.mcp['one'].update(title='Ещё правка', lastModified='v3')
    run()
    choice['source'] = 'local'
    assert alice.post('/api/google/resolve', json=choice).status_code == 200
    assert google.mcp['one']['title'] == 'Локальный выбор'
    google.mcp['one'].update(deleted=True, lastModified='v4')
    assert run()['changed'] == 1
    assert alice.get('/api/todos').json() == []


def test_mcp_create_then_reopen_and_move_date(mcp_exchange):
    alice, bob, google, owner, run, connect = mcp_exchange
    connect()
    row = alice.post('/api/todos', json={'title': 'Новая', 'scheduled_date': '2098-12-02',
            'scheduled_at': '2098-12-02T03:00:00Z', 'deadline_date': '2098-12-04', 'completed': True}).json()
    assert run()['changed'] == 1
    assert [name for name, args in google.mcp_writes] == ['create_task', 'complete_task']
    assert google.mcp_writes[0][1]['scheduledTime'] == '10:00:00'
    assert google.mcp_writes[0][1]['deadlineDate'] == '2098-12-04'
    assert len(google.records['todo']) == 0
    row['completed'] = False
    assert alice.put('/api/todos/' + row['id'], json={key: row[key] for key in ('title', 'completed')}).status_code == 200
    assert run()['changed'] == 1
    assert google.mcp_writes[-1][0] == 'uncomplete_task'
    assert run()['changed'] == 0


def test_mcp_pagination_and_text_content_transport():
    calls = []
    def request(req):
        args = json.loads(req.content)['params']['arguments']
        calls.append(args)
        data = {'tasks': [{'id': 'b'}]} if args.get('pageToken') else {'tasks': [{'id': 'a'}], 'nextPageToken': 'page-2'}
        return httpx.Response(200, json={'result': {'content': [{'type': 'text', 'text': json.dumps(data)}]}})
    with httpx.Client(transport=httpx.MockTransport(request)) as client:
        assert [raw['id'] for raw in tasks_mcp.records(client)] == ['a', 'b']
    assert calls[1]['pageToken'] == 'page-2'
    assert calls[1]['filter']['includeDeleted']


@pytest.mark.parametrize('raw', [
    {'scheduledDate': 'invalid'},
    {'scheduledDate': '2098-12-01', 'scheduledTime': '25:00:00'},
    {'scheduledDate': '2098-12-01', 'scheduledTime': '10:00:00', 'timeZone': 'invalid'},
])
def test_invalid_mcp_dates_are_rejected(raw):
    with pytest.raises((ValueError, KeyError)):
        incoming({'__mcp': True, 'title': 'Test', **raw}, 'todo_mcp')
