"""Google Tasks MCP transport and sync; calendar continues using its own OAuth grant."""
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from time import monotonic
from urllib.parse import urlsplit, unquote
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from app.google_sync.models import GoogleLink
from app.google_sync.oauth import refresh_access
from app.todos.dao import TodoDAO

ENDPOINT = 'https://tasksmcp.googleapis.com/mcp/v1'
KIND = 'todo_mcp'


def tool_error(result):
    # Recognize Google's access gate without echoing arbitrary tool payloads,
    # task contents or external error details into logs or the callback URL.
    texts = '\n'.join(item.get('text', '') for item in result.get('content', [])
                      if isinstance(item, dict) and item.get('type') == 'text' and isinstance(item.get('text'), str))
    if 'enrolled in the Google Workspace Developer Preview Program' in texts:
        match = re.search(r'Google Cloud project\s*\((\d{1,20})\)', texts)
        project = ' ' + match[1] if match else ''
        return ('Google пока отклоняет доступ Tasks MCP для проекта' + project + ', возвращая ограничение Developer Preview Program. '
                'Tasks MCP объявлен общедоступным 24 ноября 2026 года, но запуск может занимать до 10 дней. '
                'Возможна задержка запуска для аккаунта; повторите подключение позже. '
                'Этот ответ сам по себе не означает, что нужно покупать Google Workspace или домен. '
                'Прежняя синхронизация продолжает работать.')
    return 'Google Tasks MCP не выполнил действие. Обновите список и повторите обмен.'


def call(client, name, arguments):
    try:
        response = client.post(ENDPOINT, timeout=15, headers={'Accept': 'application/json, text/event-stream'},
                               json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                     'params': {'name': name, 'arguments': arguments}})
        if response.status_code in {401, 403}:
            raise HTTPException(502, 'Google Tasks MCP отклонил доступ. Проверьте Tasks MCP API и OAuth-клиент агента, затем подключите Tasks MCP заново.')
        response.raise_for_status()
        if 'text/event-stream' in response.headers.get('content-type', ''):
            messages = []
            for event in response.text.replace('\r\n', '\n').split('\n\n'):
                data = '\n'.join(line[5:].lstrip(' ') for line in event.splitlines() if line.startswith('data:'))
                if data:
                    messages.append(json.loads(data))
            envelope = next(value for value in messages if value.get('id') == 1)
        else:
            envelope = response.json()
        if envelope.get('error'):
            raise ValueError
        result = envelope['result']
        if result.get('isError'):
            raise HTTPException(502, tool_error(result))
        structured = result.get('structuredContent')
        if isinstance(structured, dict):
            return structured
        for content in result.get('content', []):
            if content.get('type') == 'text':
                parsed = json.loads(content['text'])
                if isinstance(parsed, dict):
                    return parsed
        raise ValueError
    except (httpx.HTTPError, ValueError, KeyError, TypeError, StopIteration):
        raise HTTPException(502, 'Не удалось прочитать ответ Google Tasks MCP. Повторите обмен.') from None


def snapshot(row):
    point = row.scheduled_at.astimezone(ZoneInfo(row.timezone)) if row.scheduled_at else None
    return {'title': row.title, 'description': row.description, 'completed': row.completed,
            'scheduledDate': row.scheduled_date.isoformat() if row.scheduled_date else '',
            'scheduledTime': point.strftime('%H:%M:%S') if point else '',
            'deadlineDate': row.deadline_date.isoformat() if row.deadline_date else '',
            'timeZone': row.timezone}


def normalize(raw):
    from app.google_sync.service import fingerprint
    key = raw.get('id')
    if not isinstance(key, str) or not 0 < len(key) <= 1024 or any(ord(c) < 32 for c in key):
        raise ValueError('Invalid task ID')
    return {**raw, '__mcp': True, 'etag': fingerprint(raw), 'notes': raw.get('description', ''),
            'status': 'completed' if raw.get('completed') else 'needsAction'}


def records(client):
    args = {'pageSize': 100, 'filter': {'state': 'ALL', 'includeDeleted': True}}
    result = []
    seen = set()
    deadline = monotonic() + 25
    for _ in range(100):
        page = call(client, 'list_tasks', args)
        if not isinstance(page.get('tasks', []), list):
            raise HTTPException(502, 'Google Tasks MCP вернул некорректный список задач.')
        result.extend(page.get('tasks', []))
        token = page.get('nextPageToken')
        if not token:
            return result
        if token in seen or monotonic() > deadline:
            break
        seen.add(token)
        args['pageToken'] = token
    # Never infer deletions or migrate IDs from a truncated collection.
    raise HTTPException(502, 'Google Tasks MCP не вернул полный список. Повторим обмен позже.')


def web_key(value):
    if not value:
        return None
    parsed = urlsplit(value)
    return (parsed.hostname, unquote(parsed.path).rstrip('/'), parsed.query)


def migration_signature(raw, rest=False):
    due = raw.get('due')
    return (raw.get('title') or '', raw.get('notes' if rest else 'description') or '',
            raw.get('status') == 'completed' if rest else bool(raw.get('completed')),
            due[:10] if rest and due else raw.get('scheduledDate') or '')


def migrate(db, client, connection, remote_records):
    from app.google_sync.service import fetch, fingerprint, local_modified, todo_endpoint
    legacy = list(db.scalars(select(GoogleLink).where(GoogleLink.subject == connection.subject,
                                                     GoogleLink.kind == 'todo')))
    existing = {link.local_id for link in db.scalars(select(GoogleLink).where(
        GoogleLink.subject == connection.subject, GoogleLink.kind == KIND))}
    by_web, by_signature = defaultdict(list), defaultdict(list)
    for raw in remote_records:
        if raw.get('link'):
            by_web[web_key(raw['link'])].append(raw)
        by_signature[migration_signature(raw)].append(raw)
    matches = []
    used = set()
    dao = TodoDAO(db)
    if legacy:
        # REST IDs are explicitly incompatible. Resolve using Google's task URL,
        # or an exact, unique full REST-visible record in this same account.
        with httpx.Client(timeout=8, trust_env=False) as rest:
            rest.headers['Authorization'] = 'Bearer ' + refresh_access(rest, connection)
            for old in legacy:
                if old.local_id in existing:
                    continue
                from urllib.parse import quote
                source = fetch(rest, 'GET', todo_endpoint(old.task_list_id) + '/' + quote(old.remote_id, safe=''))
                if source is None:
                    raise HTTPException(409, 'Не удалось сопоставить старую задачу Google. Переход на Tasks MCP приостановлен; данные сохранены.')
                candidates = by_web.get(web_key(source.get('webViewLink')), [])
                if not candidates:
                    candidates = by_signature.get(migration_signature(source, rest=True), [])
                if len(candidates) != 1 or candidates[0]['id'] in used:
                    raise HTTPException(409, 'Есть неоднозначные задачи при переходе на Tasks MCP. Обмен задачами приостановлен, чтобы сохранить записи без дублей.')
                remote = candidates[0]
                used.add(remote['id'])
                row = dao.get(old.local_id)
                signature = fingerprint(snapshot(row)) if row else old.fingerprint
                if row and (local_modified(db, old, row, 'todo') or row.scheduled_at or row.deadline_date):
                    signature = 'migration-local-changes'
                matches.append(GoogleLink(subject=connection.subject, kind=KIND, local_id=old.local_id,
                                          task_list_id=remote.get('taskListId') or '~default', remote_id=remote['id'],
                                          fingerprint=signature, etag=''))
    db.add_all(matches)
    connection.mcp_migrated = True
    db.flush()


def pull(db, client, connection, summary):
    from app.google_sync.service import pull_record
    items = records(client)
    if not connection.mcp_migrated:
        migrate(db, client, connection, items)
    links = {link.remote_id: link for link in db.scalars(select(GoogleLink).where(
        GoogleLink.subject == connection.subject, GoogleLink.kind == KIND))}
    dao = TodoDAO(db)
    for raw in items:
        try:
            remote = normalize(raw)
        except (ValueError, TypeError):
            summary['skipped'] += 1
            continue
        pull_record(db, remote, KIND, connection.subject, links, dao, summary,
                    task_list_id=raw.get('taskListId') or '~default')
    db.commit()


def get(client, key):
    return normalize(call(client, 'get_task', {'taskId': key}))


def save(client, row, current=None, task_list_id='~default'):
    payload = snapshot(row)
    completed = payload.pop('completed')
    if current:
        fields = {name: value for name, value in payload.items()
                  if value != (current.get(name) or ('' if name != 'timeZone' else 'UTC'))}
        if fields:
            fields['timeZone'] = row.timezone
            if current.get('recurrenceRule') and fields.get('deadlineDate'):
                raise HTTPException(422, 'Google не поддерживает дедлайн у повторяющейся задачи. Уберите дедлайн или повторение в Google.')
            current = normalize(call(client, 'update_task', {'taskId': current['id'], **fields}))
    else:
        fields = {name: value for name, value in payload.items() if value != ''}
        current = normalize(call(client, 'create_task', {'taskListId': task_list_id, **fields}))
    if bool(current.get('completed')) != completed:
        current = normalize(call(client, 'complete_task' if completed else 'uncomplete_task', {'taskId': current['id']}))
    return current


def push(db, client, connection, summary):
    from app.google_sync.service import calendar_lock, fingerprint, local_modified
    if not connection.mcp_migrated:
        # A direct export must bootstrap before creating any remote records.
        pull(db, client, connection, summary)
    dao = TodoDAO(db)
    links = {link.local_id: link for link in db.scalars(select(GoogleLink).where(
        GoogleLink.subject == connection.subject, GoogleLink.kind == KIND))}
    rows = {row.id: row for row in dao.list()}
    deadline = monotonic() + 20
    writes = 0
    for local_id in dict.fromkeys([*links, *rows]):
        row, link = rows.get(local_id), links.get(local_id)
        if link and (link.conflict or (row and not local_modified(db, link, row, KIND))):
            continue
        if writes >= 25 or monotonic() > deadline:
            summary['partial'] = True
            break
        writes += 1
        current = get(client, link.remote_id) if link else None
        if link and current['etag'] != link.etag:
            link.conflict = {'remote': current} if not current.get('deleted') else {'deleted': True}
            summary['conflicts'] += 1
        elif row is None:
            call(client, 'delete_task', {'taskId': link.remote_id, 'deleteSeries': False})
            db.delete(link)
            summary['changed'] += 1
        else:
            remote = save(client, row, current)
            if link is None:
                link = GoogleLink(subject=connection.subject, kind=KIND, local_id=row.id,
                                  task_list_id=remote.get('taskListId') or '~default', remote_id=remote['id'])
                db.add(link)
            link.etag = remote['etag']
            link.remote_id = remote['id']
            link.fingerprint = fingerprint(snapshot(row))
            link.conflict = None
            summary['changed'] += 1
        db.commit()
        calendar_lock(db)


def resolve(db, client, connection, link, row, source):
    from app.google_sync.service import fingerprint, pull_record
    current = get(client, link.remote_id)
    removed = current.get('deleted')
    if source == 'remote':
        if removed:
            if row:
                db.delete(row)
            db.delete(link)
        else:
            if row:
                link.fingerprint = fingerprint(snapshot(row))
                link.etag = ''
                links = {link.remote_id: link}
            else:
                db.delete(link)
                db.flush()
                links = {}
            summary = {'changed': 0, 'skipped': 0, 'conflicts': 0, 'partial': False}
            if pull_record(db, current, KIND, connection.subject, links, TodoDAO(db), summary,
                           task_list_id=link.task_list_id) is None:
                raise HTTPException(422, 'Не удалось прочитать эту задачу Google.')
    elif row is None:
        if not removed:
            call(client, 'delete_task', {'taskId': link.remote_id, 'deleteSeries': False})
        db.delete(link)
    else:
        remote = save(client, row, None if removed else current, link.task_list_id)
        link.remote_id, link.etag = remote['id'], remote['etag']
        link.fingerprint, link.conflict = fingerprint(snapshot(row)), None
