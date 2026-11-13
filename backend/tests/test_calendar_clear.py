from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.commands import context
from app.commands.calendar_clear import is_calendar_clear
from app.core.database import AccountSession, get_session
from app.main import app
from app.recurrences.models import RecurrenceException
from app.tasks.models import Task
from app.todos.models import Todo
from app.users.models import User
from test_api import client

COMMAND = 'Снеси нахуй все задачи, мероприятия, вообще всё убери.'
START = datetime(2098, 11, 12, 9, tzinfo=timezone.utc)


@pytest.mark.parametrize('text', [
    COMMAND, 'Очисти календарь', 'Удали всё из моего календаря.', 'Снеси весь календарь!',
])
def test_unqualified_calendar_clear(text):
    assert is_calendar_clear(text)


@pytest.mark.parametrize('text', [
    'Удали все события на завтра.', 'Удали все задачи кроме пары.', 'Не убирай все события.',
    'Удали все тренировки.', 'Что будет, если очистить календарь?', 'Удали событие «все задачи».',
])
def test_scoped_or_negative_command_cannot_clear_calendar(text):
    assert not is_calendar_clear(text)


@pytest.mark.parametrize('scope', ['series', 'occurrence'])
def test_clear_calendar_over_context_limit_is_confirmed_and_account_scoped(client, monkeypatch, scope):
    api, db = client
    alice = User(email='clear-alice@example.com', password_hash='fixture')
    bob = User(email='clear-bob@example.com', password_hash='fixture')
    db.add_all([alice, bob])
    db.flush()
    alice_id, bob_id = alice.id, bob.id
    events = [
        Task(owner_id=alice_id, title=f'Event {index}', start=START + timedelta(days=index),
             end=START + timedelta(days=index, hours=1))
        for index in range(181)
    ]
    series = Task(owner_id=alice_id, title='Daily series', start=START, end=START + timedelta(hours=1),
                  recurrence={'frequency': 'daily', 'timezone': 'UTC'})
    other = Task(owner_id=bob_id, title='Other calendar', start=START + timedelta(days=300),
                 end=START + timedelta(days=300, hours=1))
    todo = Todo(owner_id=alice_id, title='Separate list')
    db.add_all([*events, series, other, todo])
    db.flush()
    db.add(RecurrenceException(task_id=series.id, occurrence_start=START + timedelta(days=1)))
    db.add(Task(owner_id=alice_id, title='Moved occurrence', series_parent_id=series.id,
                start=START + timedelta(days=250), end=START + timedelta(days=250, hours=1)))
    db.commit()

    owner = alice_id

    def scoped_session():
        with AccountSession(bind=db.bind, join_transaction_mode='create_savepoint',
                            info={'owner_id': owner}) as session:
            yield session

    monkeypatch.setitem(app.dependency_overrides, get_session, scoped_session)
    monkeypatch.setattr(context, 'calendar_context', lambda *_: pytest.fail('Clear must bypass model context'))
    prepared = api.post('/api/commands', json={'text': COMMAND})
    assert prepared.status_code == 200, prepared.text
    preview = prepared.json()
    assert preview['kind'] == 'calendar_clear' and preview['count'] == 183
    assert preview['ordinary'] == 181
    assert [item['series_id'] for item in preview['series']] == [str(series.id)]
    assert datetime.fromisoformat(preview['series'][0]['occurrence_start']) == START
    path = '/api/commands/' + preview['id']
    assert db.scalar(select(func.count()).select_from(Task)) == 184
    db.commit()

    assert api.post(path + '/execute', json={'choices': [{'candidate': 0}]}).status_code == 422
    owner = bob_id
    assert api.post(path + '/clear-calendar').status_code == 404
    owner = alice_id

    # A different set with the same count still needs another confirmation.
    db.delete(events[0])
    db.flush()
    db.add(Task(owner_id=alice_id, title='New event', start=START, end=START + timedelta(hours=1)))
    db.commit()
    assert api.post(path + '/clear-calendar').status_code == 409

    second = api.post('/api/commands', json={'text': COMMAND}).json()
    confirmed_path = '/api/commands/' + second['id'] + '/clear-calendar'
    assert api.post(confirmed_path).status_code == 422
    selected = {'choices': [{'series_id': str(series.id), 'scope': scope}]}
    confirmed = api.post(confirmed_path, json=selected)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()['deleted'] == (183 if scope == 'series' else 182)
    assert api.post(confirmed_path, json=selected).json() == confirmed.json()

    remaining = {'Other calendar'} if scope == 'series' else {'Other calendar', 'Daily series', 'Moved occurrence'}
    assert set(db.scalars(select(Task.title))) == remaining
    assert list(db.scalars(select(Todo.title))) == ['Separate list']
    assert db.scalar(select(func.count()).select_from(RecurrenceException)) == (0 if scope == 'series' else 2)
