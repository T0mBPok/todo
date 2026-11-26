import hashlib
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from time import monotonic
from zoneinfo import ZoneInfo
from urllib.parse import quote

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
from app.recurrences.models import RecurrenceException
from app.google_sync import tasks_mcp

EVENTS = 'https://www.googleapis.com/calendar/v3/calendars/primary/events'
TODOS = 'https://tasks.googleapis.com/tasks/v1/lists/@default/tasks'
TASKLISTS = 'https://tasks.googleapis.com/tasks/v1/users/@me/lists'


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def event_data(row):
    return {'summary': row.title, 'description': row.description,
            'start': {'dateTime': row.start.isoformat()}, 'end': {'dateTime': row.end.isoformat()}}


def export_recurrence_lines(row):
    rule=row.recurrence
    if rule['frequency']!='google':
        return ['RRULE:FREQ='+rule['frequency'].upper()]
    lines=list(rule['rules'])
    if not rule.get('source_start'):
        return lines
    zone=ZoneInfo(rule['timezone'])
    original=datetime.fromisoformat(rule['source_start']).astimezone(zone)
    shifted=row.start.astimezone(zone)
    days=(shifted.date()-original.date()).days
    weekdays=['MO','TU','WE','TH','FR','SA','SU']
    result=[]
    def shift_value(value,all_day=False):
        if re.fullmatch(r'\d{8}',value):
            point=datetime.strptime(value,'%Y%m%d').replace(tzinfo=zone)
            moved=project_google_occurrence(rule,row.start,point)
            return moved.astimezone(zone).strftime('%Y%m%d')
        point=datetime.strptime(value,'%Y%m%dT%H%M%S'+('Z' if value.endswith('Z') else '')).replace(
            tzinfo=timezone.utc if value.endswith('Z') else zone)
        return project_google_occurrence(rule,row.start,point).astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    for line in lines:
        if line.startswith('RRULE:'):
            # Google commonly pins weekly rules to BYDAY; moving a whole series
            # must move this pin along with DTSTART and its exclusion dates.
            if 'FREQ=WEEKLY' in line and days:
                line=re.sub(r'BYDAY=([^;]+)',lambda match:'BYDAY='+','.join(
                    value[:-2]+weekdays[(weekdays.index(value[-2:])+days)%7] for value in match[1].split(',')),line)
            line=re.sub(r'UNTIL=(\d{8}(?:T\d{6}Z)?)',lambda match:'UNTIL='+shift_value(match[1]),line)
        elif line.startswith(('EXDATE','RDATE')):
            head,values=line.split(':',1)
            shifted_values=[shift_value(value) for value in values.split(',')]
            head=head.split(';')[0]+(';VALUE=DATE' if len(shifted_values[0])==8 else '')
            line=head+':'+','.join(shifted_values)
        result.append(line)
    return result


def event_export(row, db):
    payload = event_data(row)
    if row.is_all_day:
        payload['start'] = {'date':row.start.date().isoformat()}
        payload['end'] = {'date':row.end.date().isoformat()}
    rule = row.recurrence
    if rule:
        zone = rule.get('timezone','UTC')
        if not row.is_all_day:
            payload['start']['timeZone'] = zone
            payload['end']['timeZone'] = zone
        lines = export_recurrence_lines(row)
        excluded = db.scalars(select(RecurrenceException.occurrence_start).where(RecurrenceException.task_id==row.id)).all()
        if excluded:
            if row.is_all_day:
                lines.append('EXDATE;VALUE=DATE:'+','.join(sorted({value.strftime('%Y%m%d') for value in excluded})))
            else:
                lines.append('EXDATE:'+','.join(sorted({value.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ') for value in excluded})))
        payload['recurrence'] = lines
    else:
        # PATCH must explicitly clear a previous recurrence.
        payload['recurrence'] = []
    return payload


def local_modified(db, link, row, kind):
    if row is None:
        return True
    encode = event_snapshot if kind=='event' else tasks_mcp.snapshot if kind==tasks_mcp.KIND else todo_data
    if fingerprint(encode(row)) != link.fingerprint:
        return True
    return bool(kind=='event' and link.export_fingerprint and
                fingerprint(event_export(row,db)) != link.export_fingerprint)


def pull_deleted(db, link, kind, dao, summary):
    if link is None:
        return
    row = dao.get(link.local_id)
    if row is not None and local_modified(db,link,row,kind):
        link.conflict = {'deleted':True}
        summary['conflicts'] += 1
        return
    if row is not None:
        db.delete(row)
    db.delete(link)
    summary['changed'] += 1


def todo_data(row):
    return {'title': row.title, 'notes': row.description,
            'status': 'completed' if row.completed else 'needsAction',
            'due': row.scheduled_date.isoformat() + 'T00:00:00Z' if row.scheduled_date else None}


def todo_endpoint(task_list_id='@default'):
    return 'https://tasks.googleapis.com/tasks/v1/lists/' + quote(task_list_id, safe='@') + '/tasks'


def todo_list_ids(client, summary):
    default = fetch(client, 'GET', TASKLISTS + '/@default')
    if not default or not isinstance(default.get('id'), str):
        raise HTTPException(502, 'Не удалось прочитать основной список Google Tasks.')
    result = ['@default']
    seen = {default['id'], '@default'}
    params = {'maxResults': 1000}
    for _ in range(3):
        page = fetch(client, 'GET', TASKLISTS, params=params)
        if page is None:
            raise HTTPException(502, 'Не удалось прочитать списки Google Tasks.')
        for item in page.get('items', []):
            key = item.get('id')
            if not isinstance(key, str) or not 0 < len(key) <= 1024 or any(ord(char) < 32 for char in key):
                summary['skipped'] += 1
                continue
            if key not in seen:
                result.append(key)
                seen.add(key)
        if not page.get('nextPageToken'):
            return result
        params['pageToken'] = page['nextPageToken']
    summary['partial'] = True
    return result


def upgrade_todo_fingerprints(db, links, dao):
    # Old versions never exchanged dates. Import missing dates on the first
    # new pull, while preserving locally assigned dates for export/conflict checks.
    for link in links.values():
        row = dao.get(link.local_id)
        if row is None:
            continue
        current = todo_data(row)
        legacy = {name: value for name, value in current.items() if name != 'due'}
        if link.fingerprint == fingerprint(legacy):
            link.fingerprint = fingerprint({**legacy, 'due': None})
            if row.scheduled_date is None:
                link.etag = ''
    db.flush()


def fetch(client, method, url, **kwargs):
    try:
        result = client.request(method, url, **kwargs)
        if result.status_code in {404,410} and method=='DELETE':
            return {}
        if result.status_code in {404,410} and method=='GET':
            return None
        if result.status_code in {404, 409, 410, 412} and method in {'PATCH', 'POST', 'DELETE'}:
            return None
        result.raise_for_status()
        if result.status_code==204:
            return {}
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
    if kind in {'todo', tasks_mcp.KIND}:
        if remote.get('deleted'):
            raise ValueError
        if remote.get('__mcp'):
            day = remote.get('scheduledDate') or None
            clock = remote.get('scheduledTime')
            zone = remote.get('timeZone') or 'UTC'
            point = datetime.combine(date.fromisoformat(day), time.fromisoformat(clock), ZoneInfo(zone)) if day and clock else None
            if point and point.utcoffset() is None:
                raise ValueError
            return TodoInput(title=(remote.get('title') or '').strip()[:200] or 'Задача Google',
                             description=(remote.get('description') or '')[:5000],
                             completed=bool(remote.get('completed')), scheduled_date=day,
                             scheduled_at=point, deadline_date=remote.get('deadlineDate') or None, timezone=zone)
        due = remote.get('due')
        scheduled_date = datetime.fromisoformat(due.replace('Z', '+00:00')).date() if due else None
        return TodoInput(title=(remote.get('title') or '').strip()[:200],
                         description=(remote.get('notes') or '')[:5000],
                         completed=remote.get('status') == 'completed', scheduled_date=scheduled_date)
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
    if remote.get('__mcp'):
        if not isinstance(key, str) or not 0 < len(key) <= 1024 or any(ord(char) < 32 for char in key):
            raise ValueError
        return key
    if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,1024}', key):
        raise ValueError
    return key


def pull_record(db, remote, kind, subject, links, dao, summary, calendar_zone='UTC', parent=None, task_list_id='@default'):
    try:
        key = remote_key(remote)
        if remote.get('deleted') or remote.get('status')=='cancelled':
            pull_deleted(db,links.get(key),kind,dao,summary)
            return None
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
        if link and kind in {'todo', tasks_mcp.KIND}:
            row = db.scalar(select(Todo).where(Todo.id == link.local_id).with_for_update())
        if kind == 'todo' and row is not None:
            data.timezone = row.timezone
            # REST Tasks has no deadline fields. Keep local deadlines during
            # normal imports and when resolving a conflict in Google's favor.
            data.deadline_date = row.deadline_date
            data.deadline_at = row.deadline_at
            if row.scheduled_date == data.scheduled_date:
                data.scheduled_at = row.scheduled_at
        elif kind == tasks_mcp.KIND and row is not None and row.deadline_date == data.deadline_date:
            # Google has a date-only deadline; retain our independent precise time.
            data.deadline_at = row.deadline_at
        encode = event_snapshot if kind == 'event' else tasks_mcp.snapshot if kind == tasks_mcp.KIND else todo_data
        if link and local_modified(db,link,row,kind):
            link.conflict = {'remote':remote,'calendar_zone':calendar_zone}
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
                link = GoogleLink(subject=subject, kind=kind, local_id=row.id, remote_id=key, task_list_id=task_list_id)
                db.add(link)
            link.fingerprint = fingerprint(encode(row))
            link.etag = etag
            link.conflict = None
            if kind=='event':
                link.export_fingerprint = fingerprint(event_export(row,db))
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
    for remote in records:
        if remote.get('status')=='cancelled' and not remote.get('recurringEventId'):
            pull_deleted(db,links.get(remote.get('id')),'event',dao,summary)
    db.commit()


def pull(db, client, connection, kind, summary):
    if kind == 'todo' and connection.mcp_refresh_token:
        return tasks_mcp.pull(db, client, connection, summary)
    all_links = list(db.scalars(select(GoogleLink).where(
        GoogleLink.subject == connection.subject, GoogleLink.kind == kind)))
    if kind == 'event':
        links = {item.remote_id: item for item in all_links}
        pull_calendar(db, client, connection.subject, links, summary)
        return

    dao = TodoDAO(db)
    for task_list_id in todo_list_ids(client, summary):
        links = {item.remote_id: item for item in all_links if item.task_list_id == task_list_id}
        upgrade_todo_fingerprints(db, links, dao)
        params = {'maxResults': 100, 'showCompleted': 'true', 'showHidden': 'true', 'showDeleted': 'true'}
        deadline = monotonic() + 16
        for _ in range(10):
            if monotonic() > deadline:
                summary['partial'] = True
                break
            page = fetch(client, 'GET', todo_endpoint(task_list_id), params=params)
            if page is None:
                # A list may be removed between listing it and fetching its tasks.
                summary['partial'] = True
                break
            for remote in page.get('items', []):
                pull_record(db, remote, kind, connection.subject, links, dao, summary,
                            task_list_id=task_list_id)
            db.commit()
            calendar_lock(db)
            current = db.scalar(select(GoogleConnection).with_for_update())
            if current is None or current.subject != connection.subject:
                summary['partial'] = True
                return
            if not page.get('nextPageToken'):
                break
            params['pageToken'] = page['nextPageToken']
        else:
            summary['partial'] = True


def push(db, client, connection, kind, summary):
    if kind == 'todo' and connection.mcp_refresh_token:
        return tasks_mcp.push(db, client, connection, summary)
    endpoint, dao = (EVENTS,TaskDAO(db)) if kind=='event' else (TODOS,TodoDAO(db))
    encode = event_snapshot if kind=='event' else todo_data
    links = {item.local_id:item for item in db.scalars(select(GoogleLink).where(
        GoogleLink.subject==connection.subject,GoogleLink.kind==kind))}
    rows = dao.list()
    present = {row.id for row in rows}
    deadline = monotonic()+16
    writes = 0
    for local_id,link in list(links.items()):
        if local_id in present or link.conflict:
            continue
        if writes>=25 or monotonic()>deadline:
            summary['partial']=True
            break
        writes+=1
        endpoint = EVENTS if kind == 'event' else todo_endpoint(link.task_list_id)
        remote=fetch(client,'DELETE',endpoint+'/'+quote(link.remote_id, safe=''),headers={'If-Match':link.etag},
                     params={'sendUpdates':'none'} if kind=='event' else {})
        if remote is None:
            current=fetch(client,'GET',endpoint+'/'+quote(link.remote_id, safe=''))
            link.conflict={'remote':current} if current else {'deleted':True}
            summary['conflicts']+=1
        else:
            db.delete(link);summary['changed']+=1
        db.commit()
        calendar_lock(db)
    for row in rows:
        link=links.get(row.id)
        if link and (link.conflict or not local_modified(db,link,row,kind)):
            continue
        if writes>=25 or monotonic()>deadline:
            summary['partial']=True
            break
        writes+=1
        endpoint = EVENTS if kind == 'event' else todo_endpoint(link.task_list_id if link else '@default')
        payload=event_export(row,db) if kind=='event' else todo_data(row)
        signature=fingerprint(encode(row))
        export_signature=fingerprint(payload) if kind=='event' else None
        params={'sendUpdates':'none'} if kind=='event' else {}
        if link:
            remote=fetch(client,'PATCH',endpoint+'/'+quote(link.remote_id, safe=''),headers={'If-Match':link.etag},params=params,json=payload)
        else:
            if kind=='event':payload['id']=row.id.hex
            remote=fetch(client,'POST',endpoint,params=params,json=payload)
            if remote is None and kind=='event':
                # A previous successful insert may have lost its local commit.
                current=fetch(client,'GET',endpoint+'/'+row.id.hex)
                if current and all(current.get(key)==value for key,value in payload.items() if key!='id'):
                    remote=current
        if remote is None:
            if link:
                current=fetch(client,'GET',endpoint+'/'+quote(link.remote_id, safe=''))
                link.conflict={'remote':current} if current else {'deleted':True}
                db.commit()
            summary['conflicts']+=1
            continue
        try:
            key=remote_key(remote)
            if not isinstance(remote.get('etag'),str) or not remote['etag']:raise ValueError
        except ValueError:
            summary['skipped']+=1
            continue
        if link is None:
            link=GoogleLink(subject=connection.subject,kind=kind,local_id=row.id,remote_id=key)
            db.add(link)
        link.fingerprint=signature;link.etag=remote['etag'];link.export_fingerprint=export_signature;link.conflict=None
        db.commit();summary['changed']+=1
        calendar_lock(db)
        current=db.scalar(select(GoogleConnection).with_for_update())
        if current is None or current.subject!=connection.subject:
            summary['partial']=True
            break


def run_sync(db, direction, kind):
    calendar_lock(db)
    connection = db.scalar(select(GoogleConnection).with_for_update())
    if connection is None:
        raise HTTPException(409, 'Сначала подключите аккаунт Google.')
    summary = {'changed': 0, 'skipped': 0, 'conflicts': 0, 'partial': False}
    with httpx.Client(timeout=httpx.Timeout(5, connect=3), trust_env=False) as client:
        provider = 'tasks_mcp' if kind == 'todo' and connection.mcp_refresh_token else 'google'
        client.headers['Authorization'] = 'Bearer ' + refresh_access(client, connection, provider=provider)
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


def automatic_sync(db):
    key=-1-(db.info['owner_id'].int & ((1<<63)-1))
    with engine.begin() as lock:
        if not lock.scalar(text('SELECT pg_try_advisory_xact_lock(:key)'),{'key':key}):
            return None
        calendar_lock(db)
        connection=db.scalar(select(GoogleConnection).with_for_update())
        if connection is None or not connection.sync_enabled:
            return None
        summary={'changed':0,'skipped':0,'conflicts':0,'partial':False}
        mcp_error = None
        with httpx.Client(timeout=httpx.Timeout(5,connect=3),trust_env=False) as client:
            for kind in ('event','todo'):
                provider = 'tasks_mcp' if kind == 'todo' and connection.mcp_refresh_token else 'google'
                try:
                    client.headers['Authorization']='Bearer '+refresh_access(client,connection,provider=provider)
                    pull(db,client,connection,kind,summary)
                    calendar_lock(db)
                    current=db.scalar(select(GoogleConnection).with_for_update())
                    if current is None or not current.sync_enabled or current.subject!=connection.subject:
                        return summary
                    push(db,client,current,kind,summary)
                except HTTPException as error:
                    if provider != 'tasks_mcp':
                        raise
                    db.rollback()
                    mcp_error = str(error.detail)
                    summary['partial'] = True
                    break
        connection=db.scalar(select(GoogleConnection).with_for_update())
        if connection:
            connection.last_synced_at=datetime.now(timezone.utc)
            connection.next_sync_at=datetime.now(timezone.utc)+timedelta(seconds=20 if summary['partial'] else 60)
            connection.sync_error=mcp_error
            connection.sync_partial=summary['partial']
            connection.sync_conflicts=len(db.scalars(select(GoogleLink).where(
                GoogleLink.subject==connection.subject,
                GoogleLink.kind.in_(['event', tasks_mcp.KIND if connection.mcp_refresh_token else 'todo']),
                GoogleLink.conflict.is_not(None))).all())
            db.commit()
        return summary


def conflict_records(db):
    connection=db.scalar(select(GoogleConnection))
    if connection is None:return []
    result=[]
    for link in db.scalars(select(GoogleLink).where(GoogleLink.subject==connection.subject,
            GoogleLink.kind.in_(['event', tasks_mcp.KIND if connection.mcp_refresh_token else 'todo']),
            GoogleLink.conflict.is_not(None))):
        dao=TaskDAO(db) if link.kind=='event' else TodoDAO(db)
        row=dao.get(link.local_id)
        local={'title':row.title} if row else None
        if row and link.kind=='event':local.update(start=row.start.isoformat(),end=row.end.isoformat())
        elif row:
            local.update(completed=row.completed, scheduled_date=row.scheduled_date.isoformat() if row.scheduled_date else None,
                         scheduled_at=row.scheduled_at.isoformat() if row.scheduled_at else None,
                         deadline_date=row.deadline_date.isoformat() if row.deadline_date else None)
        if row and link.kind=='todo':local['completed']=row.completed
        raw=link.conflict.get('remote')
        remote=None
        if raw and not raw.get('deleted') and raw.get('status')!='cancelled':
            remote={'title':raw.get('summary') or raw.get('title') or 'Событие Google'}
            if link.kind=='event':
                try:remote.update(start=google_time(raw['start']).isoformat(),end=google_time(raw['end']).isoformat())
                except (KeyError,ValueError,TypeError):pass
            else:
                remote['completed']=raw.get('status')=='completed'
                try:
                    data=incoming(raw,'todo')
                    remote['scheduled_date']=data.scheduled_date.isoformat() if data.scheduled_date else None
                    remote['scheduled_at']=data.scheduled_at.isoformat() if data.scheduled_at else None
                    remote['deadline_date']=data.deadline_date.isoformat() if data.deadline_date else None
                except (ValueError,TypeError,AttributeError):
                    remote['scheduled_date']=None
        result.append({'local_id':str(link.local_id),'kind':'todo' if link.kind==tasks_mcp.KIND else link.kind,'local':local,'remote':remote})
    return result


def resolve_conflict(db,kind,local_id,source):
    from uuid import uuid4
    key=-1-(db.info['owner_id'].int & ((1<<63)-1))
    with engine.begin() as lock:
        if not lock.scalar(text('SELECT pg_try_advisory_xact_lock(:key)'),{'key':key}):
            raise HTTPException(409,'Сейчас идёт обмен с Google. Повторите через несколько секунд.')
        calendar_lock(db)
        connection=db.scalar(select(GoogleConnection).with_for_update())
        if connection is None:raise HTTPException(409,'Подключите аккаунт Google.')
        if kind == 'todo' and connection.mcp_refresh_token:
            return resolve_mcp_conflict(db, connection, local_id, source)
        link=db.scalar(select(GoogleLink).where(GoogleLink.subject==connection.subject,GoogleLink.kind==kind,GoogleLink.local_id==local_id).with_for_update())
        if link is None or not link.conflict:raise HTTPException(409,'Конфликт уже разрешён. Обновите список.')
        endpoint,dao=(EVENTS,TaskDAO(db)) if kind=='event' else (todo_endpoint(link.task_list_id),TodoDAO(db))
        encode=event_snapshot if kind=='event' else todo_data
        row=dao.get(local_id)
        with httpx.Client(timeout=httpx.Timeout(5,connect=3),trust_env=False) as client:
            client.headers['Authorization']='Bearer '+refresh_access(client,connection)
            remote=fetch(client,'GET',endpoint+'/'+quote(link.remote_id, safe=''))
            removed=not remote or remote.get('deleted') or remote.get('status')=='cancelled'
            params={'sendUpdates':'none'} if kind=='event' else {}
            if source=='remote':
                if removed:
                    if row is not None:db.delete(row)
                    db.delete(link)
                else:
                    if row is None:
                        db.delete(link);db.flush()
                        links={}
                    else:
                        link.fingerprint=fingerprint(encode(row))
                        link.export_fingerprint=fingerprint(event_export(row,db)) if kind=='event' else None
                        link.etag=''
                        links={link.remote_id:link}
                    summary={'changed':0,'skipped':0,'conflicts':0,'partial':False}
                    updated=pull_record(db,remote,kind,connection.subject,links,dao,summary,
                                        link.conflict.get('calendar_zone','UTC'), task_list_id=link.task_list_id)
                    if updated is None:raise HTTPException(422,'Не удалось прочитать эту запись Google. Исправьте её в Google и повторите обмен.')
            elif row is None:
                if not removed and fetch(client,'DELETE',endpoint+'/'+quote(link.remote_id, safe=''),headers={'If-Match':remote['etag']},params=params) is None:
                    raise HTTPException(409,'Запись Google снова изменилась. Повторите выбор версии.')
                db.delete(link)
            else:
                payload=event_export(row,db) if kind=='event' else todo_data(row)
                if removed:
                    if kind=='event':payload['id']=uuid4().hex
                    saved=fetch(client,'POST',endpoint,params=params,json=payload)
                else:
                    saved=fetch(client,'PATCH',endpoint+'/'+quote(link.remote_id, safe=''),headers={'If-Match':remote['etag']},params=params,json=payload)
                if not saved:raise HTTPException(409,'Запись Google снова изменилась. Повторите выбор версии.')
                link.remote_id=remote_key(saved);link.etag=saved['etag'];link.fingerprint=fingerprint(encode(row))
                link.export_fingerprint=fingerprint(event_export(row,db)) if kind=='event' else None
                link.conflict=None
        db.flush()
        connection.sync_conflicts=len(db.scalars(select(GoogleLink).where(GoogleLink.subject==connection.subject,GoogleLink.conflict.is_not(None))).all())
        connection.next_sync_at=datetime.now(timezone.utc)
        db.commit()
        return {'note':'Выбранная версия сохранена.'}


def resolve_mcp_conflict(db, connection, local_id, source):
    link = db.scalar(select(GoogleLink).where(GoogleLink.subject == connection.subject,
                     GoogleLink.kind == tasks_mcp.KIND, GoogleLink.local_id == local_id).with_for_update())
    if link is None or not link.conflict:
        raise HTTPException(409, 'Конфликт уже разрешён. Обновите список.')
    row = TodoDAO(db).get(local_id)
    with httpx.Client(timeout=8, trust_env=False) as client:
        client.headers['Authorization'] = 'Bearer ' + refresh_access(client, connection, provider='tasks_mcp')
        tasks_mcp.resolve(db, client, connection, link, row, source)
    db.flush()
    connection.sync_conflicts = len(conflict_records(db))
    connection.next_sync_at = datetime.now(timezone.utc)
    db.commit()
    return {'note': 'Выбранная версия сохранена.'}
