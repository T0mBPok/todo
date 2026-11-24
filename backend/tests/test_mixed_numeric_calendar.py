import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from test_api import client
from app.commands.context import calendar_context
from app.commands.schemas import CommandRequest
from app.tasks.service import TaskService

SOURCE = 'Со среды убери повторяющуюся пару 1С. На завтра, на среду, 25-е, поставь на 13:15 ПО.'


def seed_numeric(api, title='1С'):
    zone = ZoneInfo('Asia/Tomsk')
    now = datetime.now(zone)
    day = now.date() + timedelta(days=(2-now.weekday()) % 7)
    values = []
    for hour, minute in [(10, 40), (13, 15)]:
        start = datetime.combine(day, datetime.min.time(), zone).replace(hour=hour, minute=minute)
        result = api.post('/api/tasks', json={
            'title': title, 'start': start.isoformat(), 'end': (start+timedelta(minutes=90)).isoformat(),
            'recurrence': {'frequency': 'weekly', 'timezone': 'Asia/Tomsk'}})
        assert result.status_code == 201, result.text
        values.append(result.json())
    start += timedelta(days=1)
    unrelated = api.post('/api/tasks', json={'title': 'Пара в университете', 'start': start.isoformat(),
                                            'end': (start+timedelta(hours=1)).isoformat()})
    assert unrelated.status_code == 201
    return values, unrelated.json(), day


@pytest.mark.parametrize('title', ['1С', '1C', '3D'])
def test_numeric_names_survive_targeted_context(client, title):
    api, session = client
    values, _, day = seed_numeric(api, title)
    request = CommandRequest(text=f'В среду убери повторяющуюся пару {title}. Добавь в среду в 13:15 ПО.')
    context, mapping = calendar_context(request, TaskService(session))
    assert {str(value.id) for value in mapping.values()} == {value['id'] for value in values}
    assert all(event['title'] == title for event in context['events'])


def response(value):
    return httpx.Response(200, request=httpx.Request('POST', 'http://model'),
                          json={'message': {'content': json.dumps(value)}})


def test_numeric_replacement_executes_atomically_and_preserves_series(client, monkeypatch):
    api, session = client
    values, unrelated, day = seed_numeric(api)
    def fake(url, **kwargs):
        payload = json.loads(kwargs['json']['messages'][1]['content'])
        events = payload['calendar']['events']
        assert {event['id'] for event in events} == {value['id'] for value in values}
        ref = next(event['ref'] for event in events if event['id'] == values[1]['id'])
        start = datetime.combine(day, datetime.min.time(), ZoneInfo('Asia/Tomsk')).replace(hour=13, minute=15)
        return response({'intent': 'manage', 'note': 'Убрать пару и добавить ПО',
                         'operations': [{'action': 'delete', 'refs': [ref], 'scope': 'occurrence'}],
                         'new_events': []})
    monkeypatch.setattr('app.commands.grounded_ai.ai_post', fake)
    monkeypatch.setattr('app.plans.ai.AIPlanner.normalize', lambda self, text: (text, ''))
    from app.plans.schemas import PlanOutput
    start = datetime.combine(day, datetime.min.time(), ZoneInfo('Asia/Tomsk')).replace(hour=13, minute=15)
    monkeypatch.setattr('app.plans.ai.AIPlanner.generate', lambda self, req, existing: PlanOutput(
        tasks=[{'title': 'ПО', 'start': start, 'end': start+timedelta(hours=1)}], note=''))
    prepared = api.post('/api/commands', json={'text': 'В среду убери повторяющуюся пару 1С в 13:15. На среду поставь на 13:15 ПО.'})
    assert prepared.status_code == 200, prepared.text
    command = prepared.json()
    assert [op['instruction']['operation'] for op in command['operations']] == ['delete', 'create']
    assert all(op['requires_confirmation'] for op in command['operations'])
    choices = [{'candidate': 0, 'scope': 'occurrence'}, {'candidate': 0}]
    saved = api.post('/api/commands/'+command['id']+'/execute', json={'choices': choices})
    assert saved.status_code == 200, saved.text
    def on_day(date):
        start = datetime.combine(date, datetime.min.time(), ZoneInfo('Asia/Tomsk'))
        return api.get('/api/tasks', params={'start': start.isoformat(), 'end': (start+timedelta(days=1)).isoformat()}).json()
    current = on_day(day)
    assert sorted(t['title'] for t in current) == ['1С', 'ПО']
    added = next(t for t in current if t['title'] == 'ПО')
    assert datetime.fromisoformat(added['start']).astimezone(ZoneInfo('Asia/Tomsk')).strftime('%H:%M') == '13:15'
    assert len([t for t in on_day(day+timedelta(days=7)) if t['title'] == '1С']) == 2
    assert any(t['id'] == unrelated['id'] for t in on_day(day+timedelta(days=1)))
    assert api.post('/api/commands/'+command['id']+'/execute', json={'choices': choices}).json() == saved.json()


@pytest.mark.parametrize('selected', ['one', 'all'])
def test_exact_screenshot_offers_both_source_pairs_without_using_destination_time(client, monkeypatch, selected):
    api, session = client
    values, _, day = seed_numeric(api)
    def fake(url, **kwargs):
        payload = json.loads(kwargs['json']['messages'][1]['content'])
        assert payload['request'] == 'Со среды убери повторяющуюся пару 1С'
        refs = [event['ref'] for event in payload['calendar']['events']]
        return response({'intent': 'manage', 'note': '', 'operations': [
            {'action': 'delete', 'refs': refs if selected == 'all' else refs[:1], 'selection': selected}]})
    monkeypatch.setattr('app.commands.grounded_ai.ai_post', fake)
    monkeypatch.setattr('app.plans.ai.AIPlanner.normalize', lambda self, text: (text, ''))
    def unexpected(*args):
        pytest.fail('An explicit date, clock and short title need no model inference')
    monkeypatch.setattr('app.plans.ai.AIPlanner.generate', unexpected)
    prepared = api.post('/api/commands', json={'text': SOURCE})
    assert prepared.status_code == 200, prepared.text
    command = prepared.json()
    assert len(command['operations']) == 2
    removed, added = command['operations']
    assert {event['id'] for event in removed['candidates']} == {value['id'] for value in values}
    assert added['candidates'][0]['title'] == 'ПО'
    assert added['candidates'][0]['start'] == '2026-11-25T06:15:00Z'
    assert all(op['requires_confirmation'] for op in command['operations'])


def test_replacement_conflict_rolls_back_deletion(client, monkeypatch):
    api, session = client
    values, _, day = seed_numeric(api)
    start = datetime.combine(day, datetime.min.time(), ZoneInfo('Asia/Tomsk')).replace(hour=16)
    occupied = api.post('/api/tasks', json={'title': 'Занято', 'start': start.isoformat(),
                                         'end': (start+timedelta(hours=1)).isoformat()})
    assert occupied.status_code == 201
    def fake(url, **kwargs):
        payload = json.loads(kwargs['json']['messages'][1]['content'])
        ref = payload['calendar']['events'][1]['ref']
        return response({'intent': 'manage', 'note': '', 'operations': [{'action': 'delete', 'refs': [ref]}]})
    monkeypatch.setattr('app.commands.grounded_ai.ai_post', fake)
    monkeypatch.setattr('app.plans.ai.AIPlanner.normalize', lambda self, text: (text, ''))
    result = api.post('/api/commands', json={'text': 'В среду убери пару 1С в 13:15. На среду поставь на 16:00 ПО.'})
    assert result.status_code == 200, result.text
    command = result.json()
    saved = api.post('/api/commands/'+command['id']+'/execute', json={'choices': [
        {'candidate': 0, 'scope': 'occurrence'}, {'candidate': 0}]})
    assert saved.status_code == 409, saved.text
    end = start.replace(hour=0)+timedelta(days=1)
    remaining = api.get('/api/tasks', params={'start': start.replace(hour=0).isoformat(), 'end': end.isoformat()}).json()
    assert len([t for t in remaining if t['title'] == '1С']) == 2
    assert not any(t['title'] == 'ПО' for t in remaining)


@pytest.mark.parametrize('addition', ['На среду поставь на 06:00 вечера встречу.',
                                    'На среду поставь на 13:15 ПО на два часа.'])
def test_mixed_addition_keeps_time_and_duration_qualification(client, monkeypatch, addition):
    api, session = client
    values, _, day = seed_numeric(api)
    def fake(url, **kwargs):
        payload = json.loads(kwargs['json']['messages'][1]['content'])
        return response({'intent': 'manage', 'note': '', 'operations': [
            {'action': 'delete', 'refs': [payload['calendar']['events'][0]['ref']]}]})
    monkeypatch.setattr('app.commands.grounded_ai.ai_post', fake)
    monkeypatch.setattr('app.plans.ai.AIPlanner.normalize', lambda self, text: (text, ''))
    from app.plans.schemas import PlanOutput
    def generate(self, request, existing):
        assert request.text == addition
        start = datetime.combine(day, datetime.min.time(), ZoneInfo('Asia/Tomsk')).replace(hour=18)
        return PlanOutput(tasks=[{'title': 'Встреча', 'start': start, 'end': start+timedelta(hours=2)}], note='')
    monkeypatch.setattr('app.plans.ai.AIPlanner.generate', generate)
    result = api.post('/api/commands', json={'text': 'В среду убери пару 1С. '+addition})
    assert result.status_code == 200, result.text
    created = result.json()['operations'][-1]['candidates'][0]
    assert datetime.fromisoformat(created['end'])-datetime.fromisoformat(created['start']) == timedelta(hours=2)
