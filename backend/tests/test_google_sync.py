import json
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core import config
from app.core.database import SessionLocal
from app.google_sync.models import GoogleConnection
from app.google_sync.oauth import SCOPES
from app.main import app
from app.users.models import User
from email_helpers import capture_mail, register_verified


def test_callback_returns_to_home_without_session():
    with TestClient(app, base_url=config.PUBLIC_ORIGIN) as client:
        for params in ({}, {'state': 'previous-flow', 'code': 'unused'}):
            response = client.get('/api/google/callback', params=params, follow_redirects=False)
            assert response.status_code == 303
            assert response.headers['location'] == '/'
        assert client.get('/api/google/status').status_code == 401


def test_oauth_binding_and_bidirectional_exchange(monkeypatch):
    inbox = capture_mail(monkeypatch)
    monkeypatch.setattr(config, 'GOOGLE_CLIENT_ID', 'test-id')
    monkeypatch.setattr(config, 'GOOGLE_CLIENT_SECRET', 'test-secret')
    monkeypatch.setattr(config, 'GOOGLE_TOKEN_KEY', Fernet.generate_key().decode())
    saved = {'id': 'task-1', 'title': 'Google task', 'status': 'needsAction', 'etag': '"v1"'}
    event = {'id': 'event-1', 'summary': 'Google event', 'etag': '"e1"',
             'start': {'dateTime': '2098-11-15T10:00:00+07:00'},
             'end': {'dateTime': '2098-11-15T11:00:00+07:00'}}
    patched = []
    calendar_mode = 'initial'
    calendar_requests = []
    archive = {'id': 'archive', 'etag': '"a1"', 'summary': 'Old event',
               'start': {'dateTime': '2020-01-09T08:00:00+07:00'},
               'end': {'dateTime': '2020-01-09T09:00:00+07:00'}}
    series = {'id': 'series', 'etag': '"r1"', 'summary': 'Repeating event',
              'start': {'dateTime': '2020-01-09T08:30:00+07:00', 'timeZone': 'Asia/Tomsk'},
              'end': {'dateTime': '2020-01-09T09:30:00+07:00'},
              'recurrence': ['RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=TH;UNTIL=20200305T013000Z']}
    flat = {**series, 'id': 'series_20200109T013000Z', 'etag': '"old"'}
    del flat['recurrence']
    edited_flat = {**flat, 'id': 'series_20200206T013000Z', 'summary': 'Another old copy',
                   'start': {'dateTime': '2020-02-06T08:30:00+07:00'},
                   'end': {'dateTime': '2020-02-06T09:30:00+07:00'}}
    cancelled = {'id': 'series_20200123T013000Z', 'recurringEventId': 'series', 'status': 'cancelled',
                 'originalStartTime': {'dateTime': '2020-01-23T08:30:00+07:00'}}
    moved = {**flat, 'id': 'series_20200220T013000Z', 'recurringEventId': 'series', 'summary': 'Moved occurrence',
             'originalStartTime': {'dateTime': '2020-02-20T08:30:00+07:00'},
             'start': {'dateTime': '2020-02-21T08:30:00+07:00'},
             'end': {'dateTime': '2020-02-21T09:30:00+07:00'}}
    point = {'id': 'point', 'etag': '"p1"', 'summary': 'Point event',
             'start': {'dateTime': '2020-01-09T12:00:00+07:00'},
             'end': {'dateTime': '2020-01-09T12:00:00+07:00'}}
    birthday = {'id': 'birthday', 'etag': '"b1"', 'summary': 'Birthday', 'eventType': 'birthday',
                'start': {'date': '2020-01-09'}, 'end': {'date': '2020-01-10'}}

    def google(request):
        if request.url.host == 'oauth2.googleapis.com':
            return httpx.Response(200, json={'access_token': 'access-token',
                                            'refresh_token': 'refresh-token', 'scope': ' '.join(SCOPES)})
        assert request.headers['Authorization'] == 'Bearer access-token'
        if request.url.host == 'openidconnect.googleapis.com':
            return httpx.Response(200, json={'sub': 'google-account'})
        if request.method == 'GET':
            if calendar_mode == 'legacy' and '/events' in request.url.path:
                return httpx.Response(200, json={'items': [flat, edited_flat]})
            if calendar_mode == 'series' and '/events' in request.url.path:
                expanded = request.url.params['singleEvents'] == 'true'
                calendar_requests.append(expanded)
                assert 'timeMin' not in request.url.params
                if expanded:
                    return httpx.Response(200, json={'items': [
                        {'id': item['id'], 'recurringEventId': 'series', 'originalStartTime': item['start']}
                        for item in (flat, edited_flat)
                    ]})
                if request.url.params.get('pageToken') == 'page-2':
                    return httpx.Response(200, json={'items': [series, birthday, point]})
                return httpx.Response(200, json={'items': [archive, cancelled, moved], 'nextPageToken': 'page-2'})
            return httpx.Response(200, json={'items': [event if '/events' in request.url.path else saved]})
        assert request.method == 'PATCH'
        is_event = '/events/' in request.url.path
        expected = event if is_event else saved
        assert request.headers['If-Match'] == expected['etag']
        data = json.loads(request.content)
        patched.append(data)
        return httpx.Response(200, json={**expected, **data, 'etag': '"v2"'})

    emails = [f'{uuid4().hex}@example.com' for _ in range(2)]
    options = dict(base_url=config.PUBLIC_ORIGIN, headers={'Origin': config.PUBLIC_ORIGIN})
    try:
        with TestClient(app, **options) as alice, TestClient(app, **options) as bob:
            real_client = httpx.Client
            monkeypatch.setattr(httpx, 'Client', lambda **kw: real_client(transport=httpx.MockTransport(google), **kw))
            for client, email in zip((alice, bob), emails):
                assert register_verified(client, email, 'long-google-test-password', inbox).status_code == 200
            auth = alice.post('/api/google/connect')
            assert auth.status_code == 200, auth.text
            params = parse_qs(urlsplit(auth.json()['url']).query)
            assert params['code_challenge_method'] == ['S256']
            assert params['redirect_uri'] == [config.PUBLIC_ORIGIN + '/api/google/callback']
            for other_origin in config.ALLOWED_ORIGINS - {config.PUBLIC_ORIGIN}:
                response = alice.post('/api/google/connect', headers={'Origin': other_origin})
                assert response.status_code == 409
                assert config.PUBLIC_ORIGIN in response.json()['detail']
            callback = {'state': params['state'][0], 'code': 'test-code'}
            for client, expected in ((bob, 'error'), (alice, 'connected'), (alice, 'error')):
                response = client.get('/api/google/callback', params=callback, follow_redirects=False)
                assert 'google=' + expected in response.headers['location']
            with SessionLocal() as db:
                owner = db.scalar(select(User.id).where(User.email == emails[0]))
                connection = db.get(GoogleConnection, owner)
                assert connection.refresh_token != 'refresh-token'
                assert Fernet(config.GOOGLE_TOKEN_KEY).decrypt(connection.refresh_token) == b'refresh-token'
            assert not bob.get('/api/google/status').json()['connected']
            for kind, path in (('todo', '/api/todos'), ('event', '/api/tasks')):
                query = {'direction': 'pull', 'kind': kind}
                result = alice.post('/api/google/sync', json=query)
                assert result.status_code == 200, result.text
                assert result.json()['changed'] == 1
                assert alice.post('/api/google/sync', json=query).json()['changed'] == 0
                assert bob.get(path).json() == []
                row = alice.get(path).json()[0]
                fields = {'title': 'Edited locally'}
                if kind == 'event':
                    fields.update(start=row['start'], end=row['end'])
                assert alice.put(path + '/' + row['id'], json=fields).status_code == 200
                result = alice.post('/api/google/sync', json={'direction': 'push', 'kind': kind})
                assert result.status_code == 200, result.text
                assert result.json()['changed'] == 1
            assert len(patched) == 2
            event_pull = {'direction': 'pull', 'kind': 'event'}
            calendar_mode = 'legacy'
            assert alice.post('/api/google/sync', json=event_pull).json()['changed'] == 2
            old_tasks = {row['title']: row for row in alice.get('/api/tasks').json()}
            kept = old_tasks['Another old copy']
            patch = {key: kept[key] for key in ('start', 'end', 'description')}
            patch['title'] = 'Edited old copy'
            assert alice.put('/api/tasks/' + kept['id'], json=patch).status_code == 200
            calendar_mode = 'series'
            result = alice.post('/api/google/sync', json=event_pull)
            assert result.json() == {'changed': 7, 'skipped': 0, 'conflicts': 0, 'partial': False}
            assert calendar_requests == [False, False, True]
            calendar_requests.clear()
            assert alice.post('/api/google/sync', json=event_pull).json()['changed'] == 0
            assert calendar_requests == [False, False]
            result = alice.get('/api/tasks', params={'start': '2020-01-01T00:00:00Z', 'end': '2020-04-01T00:00:00Z'})
            rows = result.json()
            by_title = {row['title']: row for row in rows}
            assert by_title['Old event']['is_all_day'] is False
            repeating = [row for row in rows if row['title'] == 'Repeating event']
            assert [row['start'] for row in repeating] == ['2020-01-09T01:30:00Z', '2020-03-05T01:30:00Z']
            assert repeating[0]['id'] != old_tasks['Repeating event']['id']
            assert repeating[0]['recurrence']['frequency'] == 'google'
            assert by_title['Edited old copy']['id'] == kept['id']
            assert by_title['Moved occurrence']['start'] == '2020-02-21T01:30:00Z'
            assert by_title['Moved occurrence']['series_parent_id'] == repeating[0]['id']
            assert by_title['Birthday']['is_all_day'] is True
            assert by_title['Birthday']['start'] == '2020-01-09T00:00:00Z'
            assert by_title['Birthday']['end'] == '2020-01-10T00:00:00Z'
            assert by_title['Point event']['end'] == '2020-01-09T05:00:01Z'
            task = {'title': 'Local appointment', 'start': '2020-01-09T09:00:00+07:00',
                    'end': '2020-01-09T10:00:00+07:00'}
            assert alice.post('/api/tasks', json=task).status_code == 409
            task.update(start='2020-01-09T10:00:00+07:00', end='2020-01-09T11:00:00+07:00')
            assert alice.post('/api/tasks', json=task).status_code == 201
            series_id = repeating[0]['id']
            series_path = '/api/tasks/' + series_id
            occurrence = {'scope': 'occurrence', 'occurrence_start': repeating[0]['start']}
            payload = {'title': 'Changed one occurrence', 'start': repeating[0]['start'], 'end': repeating[0]['end']}
            edited = alice.put(series_path, params=occurrence, json=payload)
            assert edited.status_code == 200, edited.text
            edited = edited.json()
            assert edited['series_parent_id'] == series_id and edited['id'] != series_id

            payload.update(title='Changed entire series', start='2020-03-05T04:00:00Z', end='2020-03-05T05:00:00Z')
            edited_series = alice.put(series_path, params={'scope': 'series', 'occurrence_start': repeating[1]['start']},
                                      json=payload)
            assert edited_series.status_code == 200, edited_series.text
            assert edited_series.json()['recurrence']['rules'] == series['recurrence']
            assert alice.post('/api/google/sync', json=event_pull).json()['changed'] == 0
            visible = {'start': '2020-01-01T00:00:00Z', 'end': '2020-04-01T00:00:00Z'}
            rows = alice.get('/api/tasks', params=visible).json()
            assert [row['start'] for row in rows if row['id'] == series_id] == ['2020-03-05T04:00:00Z']
            assert [row['title'] for row in rows if row['id'] == edited['id']] == ['Changed one occurrence']

            birthday_path = '/api/tasks/' + by_title['Birthday']['id']
            birthday_edit = {'title': 'Birthday edit', 'start': '2020-01-10T00:00:00Z', 'end': '2020-01-11T00:00:00Z'}
            response = alice.put(birthday_path, json=birthday_edit)
            assert response.status_code == 200 and response.json()['is_all_day'] is True
            assert alice.delete(birthday_path).status_code == 204
            assert alice.delete(series_path, params={'scope': 'occurrence',
                                                     'occurrence_start': '2020-03-05T04:00:00Z'}).status_code == 204
            rows = alice.get('/api/tasks', params=visible).json()
            assert not any(row['id'] == series_id for row in rows)
            assert any(row['id'] == edited['id'] for row in rows)
            assert alice.delete('/api/tasks/' + edited['id'], params={'scope': 'series'}).status_code == 204
            assert alice.post('/api/google/sync', json=event_pull).json()['changed'] == 0
            rows = alice.get('/api/tasks', params=visible).json()
            assert not any(row['series_parent_id'] == series_id or row['id'] == by_title['Birthday']['id'] for row in rows)
            assert alice.post('/api/google/disconnect').status_code == 204
            assert not alice.get('/api/google/status').json()['connected']
    finally:
        with SessionLocal.begin() as db:
            db.execute(delete(User).where(User.email.in_(emails)))
