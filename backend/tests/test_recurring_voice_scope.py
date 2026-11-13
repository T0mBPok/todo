from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.commands import grounded_ai
from app.tasks.models import Task
from test_api import client


@pytest.mark.parametrize('scope', ['occurrence', 'series'])
def test_targeted_recurring_edit_sends_one_occurrence_and_waits_for_scope(client, monkeypatch, scope):
    api, db = client
    zone = ZoneInfo('Asia/Tomsk')
    start = (datetime.now(zone) + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    series = Task(title='Тренировка в зале', start=start, end=start + timedelta(hours=1),
                  recurrence={'frequency': 'daily', 'timezone': zone.key})
    filler = [Task(title=f'Семинар {i}', start=start + timedelta(days=i, hours=5),
                   end=start + timedelta(days=i, hours=6)) for i in range(190)]
    db.add_all([series, *filler])
    db.commit()

    def interpret(request, context):
        assert len(context['events']) == len(context['catalogue']) == len(context['series']) == 1
        event = context['events'][0]
        assert event['id'] == str(series.id)
        return grounded_ai.Decision(intent='manage', note='Изменить тренировку.', operations=[
            grounded_ai.SelectedOperation(action='update', refs=[event['ref']], scope='series', new_time='11:00'),
        ])

    monkeypatch.setattr(grounded_ai, 'interpret_calendar', interpret)
    response = api.post('/api/commands', json={'text': 'Перенеси тренировку в зале на 11:00.'})
    assert response.status_code == 200, response.text
    command = response.json()
    assert command['operations'][0]['requires_confirmation']
    assert command['operations'][0]['instruction']['scope'] == 'unspecified'
    path = f"/api/commands/{command['id']}/execute"
    assert api.post(path, json={'choices': [{'candidate': 0}]}).status_code == 422
    done = api.post(path, json={'choices': [{'candidate': 0, 'scope': scope}]})
    assert done.status_code == 200, done.text
    changed = done.json()['tasks'][0]
    assert changed['series_parent_id'] == (str(series.id) if scope == 'occurrence' else None)
    records = api.get('/api/tasks', params={
        'start': start.isoformat(), 'end': (start + timedelta(days=2)).isoformat(),
    }).json()
    occurrences = sorted(datetime.fromisoformat(row['start']).astimezone(zone)
                         for row in records if row['title'] == series.title)
    assert [item.hour for item in occurrences] == ([11, 10] if scope == 'occurrence' else [11, 11])
