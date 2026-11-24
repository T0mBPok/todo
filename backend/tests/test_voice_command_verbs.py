import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.plans.transcript_guard import safe_transcript_edit
from app.plans.prompts import normalize_transcript
from app.voice.service import polish_transcript
from app.commands.matching import declarative_calendar_add
from app.tasks.models import Task
from test_api import client


@pytest.mark.parametrize(('original', 'edited'), [
    ('Поставь завтра в 09:00 созвон.', 'Завтра в 09:00 созвон.'),
    ('Добавь завтра в 09:00 созвон.', 'Удали завтра в 09:00 созвон.'),
    ('Перенеси завтра встречу на 09:00.', 'Поставь завтра встречу на 09:00.'),
    ('Удали завтра пару в 09:00.', 'Завтра пару в 09:00.'),
    ('Добавь созвон в 09:00. Удали пару в 10:00.', 'Удали созвон в 09:00. Добавь пару в 10:00.'),
])
def test_cleanup_cannot_remove_replace_or_reorder_requested_actions(original, edited):
    assert not safe_transcript_edit(original, edited)


@pytest.mark.parametrize(('original', 'edited'), [
    ('Поставишь завтра в 09:00 созвон?', 'Поставь завтра в 09:00 созвон.'),
    ('Поставьте завтра в 09:00 созвон.', 'Добавь завтра в 09:00 созвон.'),
    ('Удалишь завтра пару в 09:00?', 'Убери завтра пару в 09:00.'),
])
def test_polite_forms_and_equivalent_action_verbs_remain_usable(original, edited):
    assert safe_transcript_edit(original, edited)


def test_screenshot_cleanup_preserves_command_in_display_and_execution(monkeypatch):
    from app.plans import ai
    raw = 'Поставь на четверг 26-го, на 9 вечера написать волокитину.'
    edited = 'На четверг 26-го, на 9 вечера написать Волокитиной.'
    monkeypatch.setattr(ai, 'ai_post', lambda url, **kw: httpx.Response(200,
        request=httpx.Request('POST', url), json={'message': {'content': json.dumps({'text': edited, 'note': ''})}}))
    result = polish_transcript({'text': raw, 'engine': 'GigaAM v3'})
    assert result['raw_text'] == raw
    assert result['text'].startswith('Поставь ')
    assert result['command_text'] == result['text']
    assert 'волокитину' in result['command_text']
    assert '09:00 вечера' in result['command_text']


@pytest.mark.parametrize(('text', 'expected'), [
    ('На четверг 26-го, на 9 вечера написать Волокитину.', True),
    ('Завтра в 9 утра созвон.', True),
    ('Завтра в 9 утра что у меня?', False),
    ('Завтра в 9 утра покажи расписание.', False),
    ('Завтра в 9 утра перенеси эту встречу.', False),
])
def test_date_first_creation_does_not_require_an_introductory_verb(text, expected):
    assert declarative_calendar_add(text) is expected


@pytest.mark.parametrize(('source', 'expected'), [
    ('На 9 вечера созвон.', 'На 09:00 вечера созвон.'),
    ('В 9 утра созвон.', 'В 09:00 утра созвон.'),
    ('К 9 часам вечера созвон.', 'К 9 часам вечера созвон.'),
    ('Купить 9 тетрадей вечером.', 'Купить 9 тетрадей вечером.'),
    ('На четверг 26-го написать письмо.', 'На четверг 26-го написать письмо.'),
])
def test_numeric_hour_with_daypart_keeps_dates_and_quantities_intact(source, expected):
    assert normalize_transcript(source) == expected


@pytest.mark.parametrize('prefix', ['Поставь ', 'Поставьте ', ''])
@pytest.mark.parametrize('end', [None, '2026-11-26T21:00:00+07:00', '2026-11-26T20:00:00+07:00'])
def test_screenshot_creates_correct_event_in_large_calendar_despite_bad_model_end(client, monkeypatch, prefix, end):
    from app.plans import ai, dates, colloquial_time
    from app.commands import service
    api, db = client
    zone = ZoneInfo('Asia/Tomsk')
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            point = datetime(2026, 11, 24, 18, tzinfo=zone)
            return point.astimezone(tz) if tz else point.replace(tzinfo=None)
    for module in (ai, dates, colloquial_time, service):
        monkeypatch.setattr(module, 'datetime', FixedDateTime)
    monkeypatch.setattr(ai.config, 'AI_PROVIDER', 'gigachat')
    base = datetime(2098, 1, 1, 10, tzinfo=zone)
    db.add_all([Task(title='Постороннее ' + str(index), start=base + timedelta(days=index),
                    end=base + timedelta(days=index, hours=1)) for index in range(185)])
    db.commit()
    source = prefix + 'на четверг 26-го, на 9 вечера написать волокитину.'
    def model(url, **kwargs):
        if kwargs['operation'] == 'transcript_normalization':
            value = {'text': 'На четверг 26-го, на 9 вечера написать Волокитиной.', 'note': ''}
        else:
            assert kwargs['operation'] == 'calendar_plan'
            task = {'title': 'Написать Волокитиной', 'start': '2026-11-26T21:00:00+07:00'}
            if end is not None:
                task['end'] = end
            value = {'tasks': [task], 'note': '', 'needs_clarification': False}
        return httpx.Response(200, request=httpx.Request('POST', url),
                              json={'message': {'content': json.dumps(value)}})
    monkeypatch.setattr(ai, 'ai_post', model)
    monkeypatch.setattr('app.commands.grounded_ai.interpret_calendar',
                        lambda *_: pytest.fail('Creation must not be interpreted as editing an existing event'))
    result = api.post('/api/commands', json={'text': source, 'timezone': 'Asia/Tomsk'})
    assert result.status_code == 200, result.text
    draft = result.json()['plan']
    assert len(draft['tasks']) == 1 and draft['review'] == []
    event = draft['tasks'][0]
    assert event['start'] == '2026-11-26T14:00:00Z'
    assert event['end'] == '2026-11-26T15:00:00Z'
    saved = api.post('/api/plans/' + draft['id'] + '/confirm', json={'tasks': draft['tasks']})
    assert saved.status_code == 200, saved.text
    events = api.get('/api/tasks').json()
    assert len(events) == 186
    assert any(row['title'] == 'Написать Волокитину' and row['start'] == event['start'] for row in events)


@pytest.mark.parametrize('recipient', ['волокитину', 'Алексею Волокитину', 'Иванову', 'Сергею Петрову'])
def test_contact_names_keep_spoken_spelling_in_cleanup_and_plan(monkeypatch, recipient):
    from app.plans import ai
    changed = recipient.replace('волокитину', 'волокитиной').replace('Волокитину', 'Волокитиной').replace('Иванову', 'Ивановой').replace('Петрову', 'Петровой')
    original = f'Поставь на четверг 26-го на 21:00 написать {recipient}.'
    edited = f'Поставь на четверг 26-го на 21:00 написать {changed}.'
    monkeypatch.setattr(ai, 'ai_post', lambda url, **kwargs: httpx.Response(200,
        request=httpx.Request('POST', url), json={'message': {'content': json.dumps({'text': edited, 'note': ''})}}))
    normalized, _ = ai.AIPlanner().normalize(original)
    assert recipient in normalized
    task = {'title': f'Написать {changed}', 'description': f'Написать {changed} по вопросу доклада',
            'start': '2026-11-26T21:00:00+07:00', 'end': '2026-11-26T22:00:00+07:00'}
    plan = ai.parse_plan(json.dumps({'tasks': [task], 'note': '', 'needs_clarification': False}),
                         original, 'Asia/Tomsk')
    assert plan.tasks[0].title == f'Написать {recipient}'
    assert plan.tasks[0].description == f'Написать {recipient} по вопросу доклада'


def test_unrelated_invented_recipient_is_rejected_instead_of_replacing_the_user(monkeypatch):
    from app.plans import ai
    original = 'Поставь завтра в 21:00 написать Волокитину.'
    edited = 'Поставь завтра в 21:00 написать Ивановой.'
    monkeypatch.setattr(ai, 'ai_post', lambda url, **kwargs: httpx.Response(200,
        request=httpx.Request('POST', url), json={'message': {'content': json.dumps({'text': edited, 'note': ''})}}))
    assert ai.AIPlanner().normalize(original)[0] == original
