import hashlib
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from time import monotonic
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, text
from app.core.database import engine
from sqlalchemy.exc import IntegrityError

from app.google_sync.models import GoogleConnection, GoogleLink
from app.google_sync.oauth import refresh_access
from app.recurrences.dao import RecurrenceDAO
from app.recurrences.service import google_schedule, project_google_occurrence
from app.tasks.dao import TaskDAO
from app.tasks.schemas import TaskInput
from app.tasks.service import calendar_lock
from app.todos.dao import TodoDAO
from app.todos.models import Todo
from app.todos.schemas import TodoInput

EVENTS = 'https://www.googleapis.com/calendar/v3/calendars/primary/events'
TODOS = 'https://tasks.googleapis.com/tasks/v1/lists/@default/tasks'


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def event_data(row):
    return {'summary': row.title, 'description': row.description,
            'start': {'dateTime': row.start.isoformat()}, 'end': {'dateTime': row.end.isoformat()}}


def todo_data(row):
    return {'title': row.title, 'notes': row.description,
            'status': 'completed' if row.completed else 'needsAction'}


def fetch(client, method, url, **kwargs):
    try:
        result = client.request(method, url, **kwargs)
        if result.status_code in {404, 409, 410, 412} and method in {'PATCH', 'POST'}:
            return None
        result.raise_for_status()
        data = result.json()
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, 'Google не завершил обмен. Проверьте подключение и повторите.') from None


def google_time(point):
    if 'date' in point:
        return datetime.combine(date.fromisoformat(point['date']), time.min, timezone.utc)
    value = datetime.fromisoformat(point['dateTime'])
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo(point['timeZone']))
    return value.astimezone(timezone.utc)


def incoming(remote, kind):
    if kind == 'todo':
        if remote.get('deleted'):
            raise ValueError
        return TodoInput(title=remote['title'], description=remote.get('notes') or '',
                         completed=remote.get('status') == 'completed')
    if remote.get('eventType', 'default') not in {'default', 'birthday'}:
        raise ValueError
    first, last = google_time(remote['start']), google_time(remote['end'])
    if first == last and 'dateTime' in remote['start']:
        # Google permits point events; our task intervals require a positive length.
        last += timedelta(seconds=1)
    return TaskInput(title=(remote.get('summary') or '').strip()[:200] or 'Событие Google',
                     description=(remote.get('description') or '')[:5000], start=first, end=last)


def series_rule(remote, data, calendar_zone):
    lines = remote['recurrence']
    if not isinstance(lines, list) or not lines or len(lines) > 64:
        raise ValueError
    for line in lines:
        if not isinstance(line, str) or len(line) > 4096 or '\n' in line or '\r' in line:
            raise ValueError
        if line.startswith('RRULE:') and not re.search(r'(?:[:;])FREQ=(?:DAILY|WEEKLY|MONTHLY|YEARLY)(?:;|$)', line):
            raise ValueError
        if not line.startswith(('RRULE:', 'RDATE:', 'RDATE;', 'EXDATE:', 'EXDATE;')):
            raise ValueError
    all_day = 'date' in remote['start']
    zone = 'UTC' if all_day else remote['start'].get('timeZone') or calendar_zone
    rule = {'frequency': 'google', 'timezone': zone, 'rules': lines}
    google_schedule(rule, data.start, all_day)
    return rule


def event_snapshot(row):
    data = event_data(row)
    if row.recurrence:
        data['recurrence'] = row.recurrence
    return data


def remote_key(remote):
    key = remote.get('id')
    if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,1024}', key):
        raise ValueError
    return key


def pull_record(db, remote, kind, subject, links, dao, summary, calendar_zone='UTC', parent=None):
    try:
        key = remote_key(remote)
        etag = remote.get('etag')
        if not isinstance(etag, str) or not etag:
            raise ValueError
        link = links.get(key)
        row = dao.get(link.local_id) if link and kind == 'event' else None
        if link and link.etag == etag:
            if parent and row and not row.series_parent_id and not row.recurrence:
                row.series_parent_id, row.series_original_start = parent
                summary['changed'] += 1
            return row
        data = incoming(remote, kind)
        if link and kind == 'todo':
            row = db.scalar(select(Todo).where(Todo.id == link.local_id).with_for_update())
        encode = event_snapshot if kind == 'event' else todo_data
        if link and (row is None or fingerprint(encode(row)) != link.fingerprint):
            summary['conflicts'] += 1
            return None
        rule = series_rule(remote, data, calendar_zone) if kind == 'event' and remote.get('recurrence') else None
        with db.begin_nested():
            if row is None:
                row = dao.add(data)
            else:
                for name, value in data.model_dump(exclude={'category', 'is_fixed', 'recurrence'}).items():
                    setattr(row, name, value)
            if kind == 'event':
                row.from_google = True
                row.is_all_day = 'date' in remote['start']
                row.recurrence = rule
                if parent:
                    row.series_parent_id, row.series_original_start = parent
            if link is None:
                db.flush()
                link = GoogleLink(subject=subject, kind=kind, local_id=row.id, remote_id=key)
                db.add(link)
            link.fingerprint = fingerprint(encode(row))
            link.etag = etag
        links[key] = link
        summary['changed'] += 1
        return row
    except (ValidationError, ValueError, KeyError, TypeError, IntegrityError, OverflowError):
        summary['skipped'] += 1
        return None


def calendar_pages(client, params):
    deadline = monotonic() + 16
    items = []
    zone = 'UTC'
    for _ in range(10):
        if monotonic() > deadline:
            break
        page = fetch(client, 'GET', EVENTS, params=params)
        zone = page.get('timeZone') or zone
        items.extend(page.get('items', []))
        if not page.get('nextPageToken'):
            return items, zone
        params['pageToken'] = page['nextPageToken']
    return None, zone


def retire_copy(db, dao, recurrences, link, root, original, summary):
    row = dao.get(link.local_id)
    if row and not row.from_google:
        return
    if row is None:
        recurrences.exclude(root.id, original)
    else:
        if (not row.recurrence and not row.is_fixed and not row.plan_id
                and row.category == 'important_not_urgent'
                and fingerprint(event_snapshot(row)) == link.fingerprint):
            dao.delete(row)
        else:
            # Preserve locally edited copies in their original position in the series.
            recurrences.exclude(root.id, original)
            if not row.recurrence:
                row.series_parent_id = root.id
                row.series_original_start = original
        summary['changed'] += 1
    db.delete(link)


def pull_calendar(db, client, subject, links, summary):
    records, zone = calendar_pages(client, {
        'singleEvents': 'false', 'showDeleted': 'true', 'maxResults': 1000,
        'fields': 'nextPageToken,timeZone,items(id,etag,status,eventType,start,end,summary,description,recurrence,recurringEventId,originalStartTime)',
    })
    if records is None:
        summary['partial'] = True
        return

    dao = TaskDAO(db)
    recurrences = RecurrenceDAO(db)
    roots = {}
    exception_ids = {event.get('id') for event in records if event.get('recurringEventId')}
    master_ids = {event.get('id') for event in records if event.get('recurrence') and event.get('status') != 'cancelled'}
    # Previous versions used Google instance IDs as standalone event IDs.
    # Verify candidate IDs with Google before replacing their local rows.
    legacy = {key for key in links if key not in exception_ids
              and key.rpartition('_')[0] in master_ids
              and re.fullmatch(r'\d{8}(?:T\d{6}Z)?', key.rpartition('_')[2])}
    expanded = []
    if legacy:
        expanded, _ = calendar_pages(client, {
            'singleEvents': 'true', 'showDeleted': 'false', 'maxResults': 1000,
            'timeMax': (datetime.now(timezone.utc) + timedelta(days=365)).isoformat(),
            'fields': 'nextPageToken,items(id,recurringEventId,originalStartTime)',
        })
        if expanded is None:
            summary['partial'] = True
            return

    for remote in records:
        if remote.get('recurringEventId') or remote.get('status') == 'cancelled':
            continue
        row = pull_record(db, remote, 'event', subject, links, dao, summary, zone)
        if row and row.recurrence and remote.get('recurrence'):
            roots[remote['id']] = row

    for remote in records:
        root = roots.get(remote.get('recurringEventId'))
        if root is None:
            continue
        try:
            original = project_google_occurrence(root.recurrence, root.start, google_time(remote['originalStartTime']))
            key = remote_key(remote)
        except (ValueError, KeyError, TypeError):
            summary['skipped'] += 1
            continue
        recurrences.exclude(root.id, original)
        if remote.get('status') != 'cancelled':
            pull_record(db, remote, 'event', subject, links, dao, summary, zone, (root.id, original))
        elif key in links:
            retire_copy(db, dao, recurrences, links[key], root, original, summary)

    for remote in expanded:
        key = remote.get('id')
        root = roots.get(remote.get('recurringEventId'))
        if key not in legacy or root is None:
            continue
        try:
            original = project_google_occurrence(root.recurrence, root.start, google_time(remote['originalStartTime']))
        except (ValueError, KeyError, TypeError):
            summary['skipped'] += 1
            continue
        retire_copy(db, dao, recurrences, links[key], root, original, summary)
    db.commit()


def pull(db, client, connection, kind, summary):
    links = {item.remote_id: item for item in db.scalars(select(GoogleLink).where(
        GoogleLink.subject == connection.subject, GoogleLink.kind == kind))}
    if kind == 'event':
        pull_calendar(db, client, connection.subject, links, summary)
        return

    dao = TodoDAO(db)
    params = {'maxResults': 100, 'showCompleted': 'true', 'showHidden': 'true'}
    deadline = monotonic() + 16
    for _ in range(10):
        if monotonic() > deadline:
            break
        page = fetch(client, 'GET', TODOS, params=params)
        for remote in page.get('items', []):
            pull_record(db, remote, kind, connection.subject, links, dao, summary)
        db.commit()
        if not page.get('nextPageToken'):
            return
        params['pageToken'] = page['nextPageToken']
        calendar_lock(db)
        current = db.scalar(select(GoogleConnection).with_for_update())
        if current is None or current.subject != connection.subject:
            break
    summary['partial'] = True


def push(db, client, connection, kind, summary):
    endpoint, dao, encode = (EVENTS, TaskDAO(db), event_data) if kind == 'event' else (TODOS, TodoDAO(db), todo_data)
    links = {item.local_id: item for item in db.scalars(select(GoogleLink).where(
        GoogleLink.subject == connection.subject, GoogleLink.kind == kind))}
    deadline = monotonic() + 16
    writes = 0
    for row in dao.list():
        if kind == 'event' and (row.is_all_day or row.recurrence or row.series_parent_id):
            summary['skipped'] += 1
            continue
        payload = encode(row)
        signature = fingerprint(payload)
        link = links.get(row.id)
        if link and signature == link.fingerprint:
            continue
        if writes >= 25 or monotonic() > deadline:
            summary['partial'] = True
            break
        writes += 1
        params = {'sendUpdates': 'none'} if kind == 'event' else {}
        if link:
            remote = fetch(client, 'PATCH', endpoint + '/' + link.remote_id,
                           headers={'If-Match': link.etag}, params=params, json=payload)
        else:
            if kind == 'event':
                payload['id'] = row.id.hex
            remote = fetch(client, 'POST', endpoint, params=params, json=payload)
        if remote is None:
            summary['conflicts'] += 1
            continue
        try:
            key = remote_key(remote)
            if not isinstance(remote.get('etag'), str) or not remote['etag']:
                raise ValueError
        except ValueError:
            summary['skipped'] += 1
            continue
        if link is None:
            link = GoogleLink(subject=connection.subject, kind=kind, local_id=row.id, remote_id=key)
            db.add(link)
        link.fingerprint = signature
        link.etag = remote['etag']
        db.commit()
        summary['changed'] += 1
        calendar_lock(db)
        current = db.scalar(select(GoogleConnection).with_for_update())
        if current is None or current.subject != connection.subject:
            summary['partial'] = True
            break


def run_sync(db, direction, kind):
    calendar_lock(db)
    connection = db.scalar(select(GoogleConnection).with_for_update())
    if connection is None:
        raise HTTPException(409, 'Сначала подключите аккаунт Google.')
    summary = {'changed': 0, 'skipped': 0, 'conflicts': 0, 'partial': False}
    with httpx.Client(timeout=httpx.Timeout(5, connect=3), trust_env=False) as client:
        client.headers['Authorization'] = 'Bearer ' + refresh_access(client, connection)
        operation = pull if direction == 'pull' else push
        operation(db, client, connection, kind, summary)
    return summary


def sync(db, direction, kind):
    # Hold a separate transaction lock across per-item commits so retries
    # and multiple tabs cannot create the same Google task concurrently.
    key = -1 - (db.info['owner_id'].int & ((1 << 63) - 1))
    with engine.begin() as lock:
        if not lock.scalar(text('SELECT pg_try_advisory_xact_lock(:key)'), {'key': key}):
            raise HTTPException(409, 'Обмен с Google уже выполняется.')
        return run_sync(db, direction, kind)
