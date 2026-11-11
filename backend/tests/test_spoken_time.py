from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.commands import grounded_ai
from app.plans import ai
from test_api import client


def test_spoken_tomsk_range_survives_utc_model_error_and_auto_save(client, monkeypatch):
    api, _ = client
    zone = ZoneInfo('Asia/Tomsk')
    day = (datetime.now(zone).date() + timedelta(days=1)).isoformat()
    # Reproduce both failure modes: the first model call loses the explicit
    # interval, then the planner mistakes spoken wall time for UTC.
    monkeypatch.setattr(grounded_ai, 'interpret_calendar', lambda *_: grounded_ai.Decision(
        intent='create', note='', create_text='Завтра тренировка'))
    monkeypatch.setattr(ai.config, 'AI_PROVIDER', 'gigachat')
    model_plan = ai.ExtractedPlan(
        tasks=[{'title': 'Тренировка', 'start': day + 'T18:00:00Z', 'end': day + 'T19:00:00Z'}],
        note='', needs_clarification=False,
    )
    monkeypatch.setattr(ai, 'ai_post', lambda url, **_: httpx.Response(
        200, request=httpx.Request('POST', url), json={'message': {'content': model_plan.model_dump_json()}}))

    response = api.post('/api/commands', json={
        'text': 'Поставь мне тонировку на завтра с 18:00 до 19:00.', 'timezone': 'Asia/Tomsk',
    })
    assert response.status_code == 200, response.text
    draft = response.json()['plan']
    saved = api.post(f"/api/plans/{draft['id']}/confirm", json={'tasks': draft['tasks']})
    assert saved.status_code == 200, saved.text
    events = api.get('/api/tasks').json()
    assert len(events) == 1
    assert datetime.fromisoformat(events[0]['start']).astimezone(zone).isoformat() == day + 'T18:00:00+07:00'
    assert datetime.fromisoformat(events[0]['end']).astimezone(zone).isoformat() == day + 'T19:00:00+07:00'
