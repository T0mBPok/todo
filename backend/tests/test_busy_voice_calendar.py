import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.commands.grounded_ai import MAX_CONTEXT_CHARS, calendar_payload
from app.commands.matching import timed_deletion
from app.commands.schemas import CommandRequest
from app.tasks.models import Task
from test_api import client

ZONE = ZoneInfo('Asia/Tomsk')


@pytest.mark.parametrize('text', [
    'Завтра тренировку с часа ночи убери.',
    'Удали завтра тренировку в 1:0.',
])
def test_timed_delete_keeps_other_times_days_and_repetitions(client, monkeypatch, text):
    api, db = client
    tomorrow = datetime.now(ZONE).date() + timedelta(days=1)
    start = datetime.combine(tomorrow, datetime.min.time(), ZONE) + timedelta(hours=1)

    def make(title, at, **extra):
        return Task(title=title, start=at, end=at + timedelta(minutes=30), **extra)

    target = make('Тренировка', start, recurrence={'frequency': 'weekly', 'timezone': 'Asia/Tomsk'})
    afternoon = make('Тренировка', start + timedelta(hours=17))
    other = make('Тренировка по баскетболу', start + timedelta(hours=1))
    # More unrelated events than the interpreter accepts; descriptions alone
    # also exceed its full prompt budget.
    filler = [make('Занятие ' + str(i), start + timedelta(days=i + 2), description='а' * 3000)
              for i in range(185)]
    db.add_all([target, afternoon, other, *filler])
    db.commit()

    def unexpected(*args):
        pytest.fail('An exact dated deletion should not depend on the model')

    monkeypatch.setattr('app.commands.grounded_ai.interpret_calendar', unexpected)
    result = api.post('/api/commands', json={'text': text, 'timezone': 'Asia/Tomsk'})
    assert result.status_code == 200, result.text
    command = result.json()
    assert len(command['operations']) == 1
    assert command['operations'][0]['instruction']['scope'] == 'occurrence'
    assert [c['id'] for c in command['operations'][0]['candidates']] == [str(target.id)]
    deleted = api.post(f"/api/commands/{command['id']}/execute", json={'choices': [{'candidate': 0}]})
    assert deleted.status_code == 200, deleted.text
    events = api.get('/api/tasks', params={'start': (start - timedelta(hours=1)).isoformat(),
                                         'end': (start + timedelta(days=8)).isoformat()}).json()
    assert [datetime.fromisoformat(e['start']) for e in events if e['id'] == str(target.id)] == [start + timedelta(days=7)]
    assert {str(afternoon.id), str(other.id)} <= {e['id'] for e in events}


def test_timed_delete_does_not_substitute_a_similar_title(client, monkeypatch):
    api, db = client
    tomorrow = datetime.now(ZONE).date() + timedelta(days=1)
    start = datetime.combine(tomorrow, datetime.min.time(), ZONE) + timedelta(hours=1)
    db.add(Task(title='Тренировка по волейболу', start=start, end=start + timedelta(hours=1)))
    db.commit()
    monkeypatch.setattr('app.commands.grounded_ai.interpret_calendar', lambda *_: pytest.fail('Unexpected model call'))
    response = api.post('/api/commands', json={'text': 'Завтра тренировку с часа ночи убери.'})
    assert response.status_code == 422
    assert '01:00' in response.json()['detail']
    assert len(api.get('/api/tasks').json()) == 1


@pytest.mark.parametrize('text', [
    'Завтра тренировку и волейбол в 01:00 убери.',
    'Завтра всю тренировку в 01:00 убери.',
    'Завтра тренировку в 01:00 убери и добавь новую.',
    'Завтра тренировку в 01:00 убери, ой нет.',
])
def test_compound_or_corrected_commands_keep_model_path(text):
    assert timed_deletion(text) is None


def test_context_compaction_preserves_all_targets_and_history():
    events = [{'ref': f'E{i}', 'id': str(i), 'title': f'Занятие {i}', 'description': 'а' * 5000,
               'start': '2026-11-12T01:00:00+07:00', 'end': '2026-11-12T02:00:00+07:00',
               'selected': i == 44, 'recurrence': None, 'weekday': 'Thursday'} for i in range(120)]
    context = {'events': events, 'series': [{'description': 'б' * 5000}] * 20,
               'catalogue': [{'title': 'в' * 200}] * 300}
    request = CommandRequest(text='Удали все занятия завтра', history=[{'role': 'user', 'text': 'Уточнение'}])
    encoded = calendar_payload(request, context)
    assert len(encoded) <= MAX_CONTEXT_CHARS
    payload = json.loads(encoded)
    assert payload['request'] == request.text and payload['history'][0]['text'] == 'Уточнение'
    assert [item['ref'] for item in payload['calendar']['events']] == [item['ref'] for item in events]
    assert payload['calendar']['events'][44]['selected']
    assert len(context['events'][44]['description']) == 5000


@pytest.mark.parametrize('utterance,first,last,end_day', [
    ('Поставь мне тренировку завтра с 18:0 до 19:0.', '18:00', '19:00', 0),
    ('Поставь мне тренировку завтра с 23:30 до 00:15.', '23:30', '00:15', 1),
    ('Поставь на завтра тренировку с восемнадти до 19яна:00.', '18:00', '19:00', 0),
])
def test_exact_creation_keeps_local_time_without_model(client, monkeypatch, utterance, first, last, end_day):
    api, _ = client
    monkeypatch.setattr('app.commands.grounded_ai.interpret_calendar', lambda *_: pytest.fail('Unexpected model call'))
    tomorrow = datetime.now(ZONE).date() + timedelta(days=1)
    response = api.post('/api/commands', json={'text': utterance})
    assert response.status_code == 200, response.text
    plan = response.json()['plan']
    item = plan['tasks'][0]
    assert item['title'] == 'Тренировка'
    assert api.get('/api/tasks').json() == []
    confirmed = api.post(f"/api/plans/{plan['id']}/confirm", json={'tasks': plan['tasks']})
    assert confirmed.status_code == 200, confirmed.text
    actual = api.get('/api/tasks').json()[0]
    for key, clock, day in [('start', first, tomorrow), ('end', last, tomorrow + timedelta(days=end_day))]:
        value = datetime.fromisoformat(actual[key]).astimezone(ZONE)
        hour, minute = map(int, clock.split(':'))
        assert (value.date(), value.hour, value.minute) == (day, hour, minute)


@pytest.mark.parametrize('text,hour,weekday', [
    ('Поставь на завтра созвон на 8:00 утра.', 8, None),
    ('Поставь созвон на завтра в 8:00 вечера.', 20, None),
    ('Поставь на завтра созвон на 23:30.', 23, None),

])
def test_exact_creation_at_single_time_defaults_to_one_hour(client, monkeypatch, text, hour, weekday):
    api, _ = client

    def unexpected(*args, **kwargs):
        pytest.fail('An explicit single-time command should not call the model')

    monkeypatch.setattr('app.commands.grounded_ai.interpret_calendar', unexpected)
    monkeypatch.setattr('app.core.priority.classify_category', unexpected)
    response = api.post('/api/commands', json={'text': text, 'timezone': 'Asia/Tomsk'})
    assert response.status_code == 200, response.text
    plan = response.json()['plan']
    assert plan['tasks'][0]['title'] == 'Созвон'
    saved = api.post(f"/api/plans/{plan['id']}/confirm", json={'tasks': plan['tasks']})
    assert saved.status_code == 200, saved.text
    event = api.get('/api/tasks').json()[0]
    start, end = (datetime.fromisoformat(event[key]).astimezone(ZONE) for key in ('start', 'end'))
    today = datetime.now(ZONE).date()
    offset = 1 if weekday is None else (weekday - today.weekday()) % 7
    assert start.date() == today + timedelta(days=offset)
    assert (start.hour, start.minute) == (hour, 30 if hour == 23 else 0)
    assert end - start == timedelta(hours=1)
