import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.commands import grounded_ai
from app.core import config
from app.plans import ai
from test_api import client


def test_complete_review_draft_can_be_edited_before_confirming(client, monkeypatch):
    api, _ = client
    zone = ZoneInfo('Asia/Tomsk')
    day = (datetime.now(zone).date() + timedelta(days=1)).isoformat()
    monkeypatch.setattr(config, 'AI_PROVIDER', 'gigachat')
    monkeypatch.setattr(ai.AIPlanner, 'normalize', lambda self, text: (text, ''))
    monkeypatch.setattr(grounded_ai, 'interpret_calendar', lambda *_: grounded_ai.Decision(intent='create', note=''))
    draft = {
        'tasks': [
            {'title': 'Работа', 'start': f'{day}T09:00:00+07:00', 'end': f'{day}T18:00:00+07:00'},
            {'title': 'Разбор портфолио', 'start': f'{day}T07:30:00+07:00', 'end': f'{day}T09:00:00+07:00'},
            {'title': 'Выставка', 'start': f'{day}T18:00:00+07:00', 'end': f'{day}T19:00:00+07:00'},
        ],
        'note': '', 'needs_clarification': True,
        'review': [{'task_index': 2, 'reason': 'Проверьте время по билету.'}],
    }
    monkeypatch.setattr(ai, 'ai_post', lambda *args, **kwargs: httpx.Response(
        200, request=httpx.Request('POST', 'http://example.invalid'), json={'message': {'content': json.dumps(draft)}}))

    response = api.post('/api/commands', json={
        'text': ('Завтра работа с 9 до 6. Завтра разбор портфолио с семи тридцати до девяти. '
                 'Завтра выставка примерно в 18:00 на полчаса.'),
        'timezone': zone.key,
    })
    assert response.status_code == 200, response.text
    plan = response.json()['plan']
    assert len(plan['tasks']) == 3
    assert all(task['title'] and task['start'] and task['end'] for task in plan['tasks'])
    assert [item['task_index'] for item in plan['review']] == [1, 2]
    assert datetime.fromisoformat(plan['tasks'][2]['end']).astimezone(zone).strftime('%H:%M') == '18:30'
    assert len(plan['review'][0]['options']) == 2
    assert api.get('/api/plans/' + plan['id']).json()['review'] == plan['review']
    assert api.get('/api/tasks').json() == []

    plan['tasks'][0]['title'] = 'Рабочая смена'
    plan['tasks'][1].update(plan['review'][0]['options'][1])
    plan['tasks'].pop(2)
    saved = api.post('/api/plans/' + plan['id'] + '/confirm', json={'tasks': plan['tasks']})
    assert saved.status_code == 200, saved.text
    tasks = {task['title']: task for task in saved.json()}
    assert set(tasks) == {'Рабочая смена', 'Разбор портфолио'}
    evening = datetime.fromisoformat(tasks['Разбор портфолио']['start']).astimezone(zone)
    assert evening.strftime('%H:%M') == '19:30'
