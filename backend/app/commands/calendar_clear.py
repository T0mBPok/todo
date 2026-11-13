import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256

from fastapi import HTTPException

from app.commands.dao import CommandDAO
from app.commands.models import Command
from app.recurrences.dao import RecurrenceDAO
from app.recurrences.service import next_occurrence, require_occurrence
from app.tasks.dao import TaskDAO
from app.tasks.service import calendar_lock, commit

ENTITY = 'calendar_clear'
DELETE_WORDS = {
    'снеси', 'снести', 'убери', 'убрать', 'удали', 'удалить',
    'сотри', 'стереть', 'очисти', 'очистить', 'почисти', 'почистить', 'сбрось', 'сбросить',
}
CLEAR_WORDS = {'очисти', 'очистить', 'почисти', 'почистить', 'сбрось', 'сбросить'}
CALENDAR_WORDS = {'календарь', 'календаря', 'календаре', 'календарик', 'календарика', 'календарике'}
ALL_WORDS = {'все', 'весь', 'всю', 'целиком', 'полностью'}
OBJECT_WORDS = {'задачи', 'события', 'мероприятия', 'записи', 'серии', 'повторения'}
FILLER_WORDS = {
    'давай', 'давайте', 'пожалуйста', 'короче', 'вообще', 'прям', 'прямо', 'нахуй', 'нахрен',
    'надо', 'нужно', 'мне', 'мой', 'моего', 'моем', 'и', 'из', 'в',
}
UNSCOPED = DELETE_WORDS | CALENDAR_WORDS | ALL_WORDS | OBJECT_WORDS | FILLER_WORDS


def is_calendar_clear(text):
    if not re.fullmatch(r'[а-яёА-ЯЁ\s,.!?–—-]+', text):
        return False
    words = set(re.findall(r'[а-я]+', text.casefold().replace('ё', 'е')))
    if words - UNSCOPED or not (words & DELETE_WORDS):
        return False
    return bool(words & ALL_WORDS or (words & CLEAR_WORDS and words & CALENDAR_WORDS))


def fingerprint(rows):
    values = [
        (str(row.id), row.start.isoformat(), row.end.isoformat(), row.recurrence, str(row.series_parent_id))
        for row in rows
    ]
    return sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def group_occurrences(rows):
    children = defaultdict(list)
    for row in rows:
        if row.series_parent_id:
            children[row.series_parent_id].append(row)
    return children


def series_preview(session, rows):
    now = datetime.now(timezone.utc)
    exceptions = RecurrenceDAO(session).exceptions()
    children = group_occurrences(rows)
    result = []
    for row in rows:
        if not row.recurrence:
            continue
        next_pair = next_occurrence(row, now, exceptions.get(row.id, set()))
        available = [(next_pair[0], row.id)] if next_pair else []
        available.extend((child.start, child.id) for child in children[row.id] if child.start >= now)
        nearest = min(available, default=None)
        result.append({
            'series_id': str(row.id),
            'title': row.title,
            'occurrence_id': str(nearest[1]) if nearest else None,
            'occurrence_start': nearest[0].isoformat() if nearest else None,
        })
    return result


def prepare_clear(session, transcript):
    owner_id = session.info.get('owner_id')
    if owner_id is None:
        raise HTTPException(401, 'Войдите в аккаунт.')
    rows = TaskDAO(session).calendar_rows(owner_id)
    if not rows:
        raise HTTPException(422, 'Календарь уже пуст.')
    series = series_preview(session, rows)
    ordinary = sum(not row.recurrence and row.series_parent_id is None for row in rows)
    note = 'Что удалить в каждой серии?' if series else 'Удалить все события календаря?'
    command = Command(
        text=transcript,
        operations=[{'entity': ENTITY, 'snapshot': fingerprint(rows), 'series': series}],
        note=note,
    )
    session.add(command)
    commit(session)
    return {'kind': ENTITY, 'id': command.id, 'count': len(rows), 'ordinary': ordinary, 'series': series, 'note': note}


def execute_clear(session, command_id, choices):
    owner_id = session.info.get('owner_id')
    if owner_id is None:
        raise HTTPException(401, 'Войдите в аккаунт.')
    calendar_lock(session)
    command = CommandDAO(session).locked(command_id)
    if (command is None or command.owner_id != owner_id or len(command.operations) != 1
            or command.operations[0].get('entity') != ENTITY):
        raise HTTPException(404, 'Команда очистки не найдена.')
    if command.status == 'executed':
        return command.result
    dao = TaskDAO(session)
    rows = dao.calendar_rows(owner_id)
    snapshot = command.operations[0]
    if fingerprint(rows) != snapshot['snapshot']:
        raise HTTPException(409, 'Список событий изменился. Повтори команду и проверь новый список.')
    series = {item['series_id']: item for item in snapshot['series']}
    scopes = {str(choice.series_id): choice.scope for choice in choices}
    if len(scopes) != len(choices) or scopes.keys() != series.keys():
        raise HTTPException(422, 'Выбери одно повторение или всю серию для каждого повторяющегося события.')

    by_id = {str(row.id): row for row in rows}
    children = group_occurrences(rows)
    recurrences = RecurrenceDAO(session)
    exceptions = recurrences.exceptions()
    task_ids = {row.id for row in rows if not row.recurrence and row.series_parent_id is None}
    exclusions = 0
    for series_id, scope in scopes.items():
        root = by_id[series_id]
        if scope == 'series':
            task_ids.add(root.id)
            task_ids.update(row.id for row in children[root.id])
            continue
        occurrence_id = series[series_id]['occurrence_id']
        occurrence_start = series[series_id]['occurrence_start']
        if occurrence_id is None or occurrence_start is None:
            raise HTTPException(422, 'Для этой серии в списке нет ближайшего повторения.')
        occurrence = by_id[occurrence_id]
        if occurrence.id != root.id:
            task_ids.add(occurrence.id)
        else:
            start = datetime.fromisoformat(occurrence_start)
            if start in exceptions.get(root.id, set()):
                raise HTTPException(409, 'Повторение уже изменилось. Повтори команду.')
            require_occurrence(root, start)
            recurrences.exclude(root.id, start)
            exclusions += 1
    if task_ids:
        dao.delete_calendar(owner_id, list(task_ids))
    deleted = len(task_ids) + exclusions
    result = {'deleted': deleted, 'note': f'Удалено событий и записей серий: {deleted}.'}
    command.status = 'executed'
    command.result = result
    commit(session)
    return result
