from contextvars import ContextVar
import logging
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


def log_result_rejection(operation, reason):
    logger.warning('ai_result request_id=%s operation=%s outcome=%s', request_id.get(), operation, reason)


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
