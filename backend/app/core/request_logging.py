from contextvars import ContextVar
import logging
import json
import re

from pydantic import ValidationError
from time import perf_counter
from uuid import uuid4

from fastapi import Request

logger = logging.getLogger('uvicorn.error')
request_id = ContextVar('request_id', default='-')


def log_dependency(service, operation, started, status=None, outcome='ok'):
    level = logging.INFO if outcome == 'ok' else logging.WARNING
    logger.log(
        level, 'dependency request_id=%s service=%s operation=%s status=%s outcome=%s duration_ms=%.0f',
        request_id.get(), service, operation, status or '-', outcome, (perf_counter() - started) * 1000,
    )


PATH_FIELDS = frozenset("intent operations new_events keep_refs note create_text action refs selection scope new_title description append_description new_time new_date_reference duration_minutes new_recurrence new_category title start end recurrence frequency timezone tasks needs_clarification review task_index reason text message content summary assessments moves event_ref slot_ref flexibility category is_fixed".split())


def safe_path(location):
    parts = []
    for item in location:
        if isinstance(item, int):
            parts.append(f'[{item}]' if 0 <= item < 10000 else '[index]')
        else:
            name = item if item in PATH_FIELDS else '<unknown_field>'
            parts.append(('.' if parts else '') + name)
    return ''.join(parts) or '<root>'


def error_diagnostics(error):
    # Never serialize ValidationError/HTTPError as text: their repr includes
    # rejected input, response bodies, URLs and sometimes credentials.
    if error is None:
        return {}
    result = {'exception': type(error).__name__}
    if isinstance(error, ValidationError):
        errors = error.errors(include_input=False, include_context=True, include_url=False)
        result['stage'] = 'schema_validation'
        result['error_count'] = len(errors)
        result['issues'] = [{'path': safe_path(item['loc']),
                             'type': item['type'] if re.fullmatch('[a-z_]{1,64}', item['type']) else 'validation_error'}
                            for item in errors[:12]]
        for issue, raw in zip(result['issues'], errors):
            # Literal expectations come from the declared schema, never the rejected value.
            if raw['type'] == 'literal_error':
                issue['expected'] = str(raw.get('ctx', {}).get('expected', ''))[:200]
            if raw['type'] == 'value_error':
                message = str(raw.get('ctx', {}).get('error', ''))
                if message in {'Окончание должно быть позже начала', 'Повторяющееся событие должно длиться не более 24 часов'}:
                    issue['reason'] = message
        result['truncated'] = len(errors) > 12
    elif isinstance(error, json.JSONDecodeError):
        result.update(stage='json_decode', line=error.lineno, column=error.colno,
                      position=error.pos, response_chars=len(error.doc))
    elif isinstance(error, KeyError):
        result.update(stage='response_envelope', missing_field=safe_path(error.args[:1]))
    elif getattr(error, 'response', None) is not None:
        result.update(stage='provider_http', http_status=error.response.status_code)
    else:
        result['stage'] = 'response_processing'
    return result


def log_result_rejection(operation, reason, error=None):
    logger.warning('ai_result request_id=%s operation=%s outcome=%s diagnostics=%s',
                   request_id.get(), operation, reason,
                   json.dumps(error_diagnostics(error), ensure_ascii=False, separators=(',', ':')))


async def log_request(request: Request, call_next):
    identifier = uuid4().hex
    request.state.request_id = identifier
    token = request_id.set(identifier)
    started = perf_counter()
    status = 500
    failure = '-'
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers['X-Request-ID'] = identifier
        return response
    except Exception as error:
        failure = type(error).__name__
        raise
    finally:
        request_id.reset(token)
        if request.url.path != '/api/health' or status >= 400:
            route = getattr(request.scope.get('route'), 'path', '<unmatched>')
            if request.url.path.startswith('/api/') and route.startswith('/') and not route.startswith('/api/'):
                route = '/api' + route
            level = logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.INFO
            logger.log(
                level, 'request request_id=%s method=%s route=%s status=%s duration_ms=%.0f exception=%s',
                identifier, request.method, route, status, (perf_counter() - started) * 1000, failure,
            )
