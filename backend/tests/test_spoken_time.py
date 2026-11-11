import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.commands import grounded_ai
from app.plans import ai
from test_api import client


def test_spoken_tomsk_range_survives_utc_model_error_and_auto_save(client, monkeypatch):
    api, _ = client
    zone = ZoneInfo('Asia/Tomsk')
    day = (datetime.now(zone).date() + timedelta(days=1)).isoformat()
    # Reproduce both failure modes: the first model call loses the explicit
    # interval, then the planner mistakes spoken wall time for UTC.
    def interpret(request, _context):
        assert request.text == 'Завтра тренировка с 18:00 до 19:00'
        return grounded_ai.Decision(intent='create', note='', create_text='Завтра тренировка')

    monkeypatch.setattr(grounded_ai, 'interpret_calendar', interpret)
    monkeypatch.setattr(ai.config, 'AI_PROVIDER', 'gigachat')
    model_plan = ai.ExtractedPlan(
        tasks=[{'title': 'Тренировка', 'start': day + 'T18:00:00Z', 'end': day + 'T19:00:00Z'}],
        note='', needs_clarification=False,
    )
    calls = []
    def model(url, **kwargs):
        payload = kwargs['json']
        calls.append(payload)
        if 'text' in payload['format'].get('properties', {}):
            assert '18:00 до 19:00' in payload['messages'][1]['content']
            content = '{"text":"Завтра тренировка с 18:00 до 19:00","note":""}'
        else:
            assert payload['messages'][1]['content'].startswith('Завтра тренировка с 18:00 до 19:00')
            content = model_plan.model_dump_json()
        return httpx.Response(200, request=httpx.Request('POST', url), json={'message': {'content': content}})

    monkeypatch.setattr(ai, 'ai_post', model)

    response = api.post('/api/commands', json={
        'text': 'Пожалуйста, поставь мне тонировку на завтра с 18:0 до 19:0.', 'timezone': 'Asia/Tomsk',
    })
    assert response.status_code == 200, response.text
    assert len(calls) == 2
    draft = response.json()['plan']
    saved = api.post(f"/api/plans/{draft['id']}/confirm", json={'tasks': draft['tasks']})
    assert saved.status_code == 200, saved.text
    events = api.get('/api/tasks').json()
    assert len(events) == 1
    assert datetime.fromisoformat(events[0]['start']).astimezone(zone).isoformat() == day + 'T18:00:00+07:00'
    assert datetime.fromisoformat(events[0]['end']).astimezone(zone).isoformat() == day + 'T19:00:00+07:00'


@pytest.mark.parametrize('transcript', [
    'Поставь мне на завтра с 18:00 до 1900 тренировку, а на пятницу на 08:00 утра созвон.',
    'Поставь тренировку завтра с 18:00 до 1900 и созвон в пятницу на 08:00 утра.',
])
def test_multi_event_voice_command_preserves_each_local_time(client, monkeypatch, transcript):
    api, _ = client
    zone = ZoneInfo('Asia/Tomsk')
    today = datetime.now(zone).date()
    tomorrow = today + timedelta(days=1)
    friday = today + timedelta(days=(4 - today.weekday()) % 7)
    normalized = transcript.replace('1900', '19:00')
    monkeypatch.setattr(ai.config, 'AI_PROVIDER', 'gigachat')

    def interpret(request, _context):
        assert request.text == normalized
        return grounded_ai.Decision(intent='create', note='', create_text='Добавь тренировку и созвон.')

    monkeypatch.setattr(grounded_ai, 'interpret_calendar', interpret)
    wrong_plan = ai.ExtractedPlan(
        # GigaChat returned local clock readings marked as UTC, in reverse order.
        tasks=[
            {'title': 'Созвон', 'start': f'{friday}T08:00:00Z', 'end': f'{friday}T09:00:00Z'},
            {'title': 'Тренировка', 'start': f'{tomorrow}T18:00:00Z', 'end': f'{tomorrow}T19:00:00Z'},
        ],
        note='', needs_clarification=False,
    )

    def model(url, **kwargs):
        payload = kwargs['json']
        if 'text' in payload['format'].get('properties', {}):
            assert payload['messages'][1]['content'] == normalized
            content = json.dumps({'text': normalized, 'note': ''})
        else:
            content = wrong_plan.model_dump_json()
        return httpx.Response(200, request=httpx.Request('POST', url), json={'message': {'content': content}})

    monkeypatch.setattr(ai, 'ai_post', model)
    response = api.post('/api/commands', json={'text': transcript, 'timezone': zone.key})
    assert response.status_code == 200, response.text
    draft = response.json()['plan']
    saved = api.post(f"/api/plans/{draft['id']}/confirm", json={'tasks': draft['tasks']})
    assert saved.status_code == 200, saved.text

    expected = {
        'Тренировка': (f'{tomorrow}T18:00:00+07:00', f'{tomorrow}T19:00:00+07:00'),
        'Созвон': (f'{friday}T08:00:00+07:00', f'{friday}T09:00:00+07:00'),
    }
    for events in (draft['tasks'], api.get('/api/tasks').json()):
        actual = {event['title']: tuple(datetime.fromisoformat(event[key]).astimezone(zone).isoformat()
                                       for key in ('start', 'end')) for event in events}
        assert actual == expected
