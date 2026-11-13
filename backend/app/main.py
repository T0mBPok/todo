from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.balance.router import router as balance_router
from app.commands.router import router as commands_router
from app.core import config
from app.core.database import engine
from app.core.request_logging import log_request
from app.google_sync.router import router as google_router
from app.plans.ai import model_status
from app.plans.router import router as plans_router
from app.tasks.router import router as tasks_router
from app.todos.router import router as todos_router
from app.users.router import require_user, router as auth_router
from app.voice.router import router as voice_router

app = FastAPI(title='Импульс', docs_url=None, redoc_url=None, openapi_url=None)


@app.exception_handler(RequestValidationError)
async def invalid_input(request: Request, _error):
    return JSONResponse({'detail': 'Проверьте формат и длину введённых данных.'}, status_code=422)


@app.exception_handler(Exception)
async def internal_error(request: Request, _error):
    return JSONResponse({'detail': 'Внутренняя ошибка сервера. Попробуйте ещё раз.'}, status_code=500,
                        headers={'X-Request-ID': request.state.request_id, 'Cache-Control': 'no-store'})


@app.middleware('http')
async def enforce_browser_boundary(request: Request, call_next):
    if request.method not in {'GET', 'HEAD', 'OPTIONS'} and request.headers.get('origin') not in config.ALLOWED_ORIGINS:
        response = JSONResponse({'detail': 'Запрос с этого сайта запрещён.'}, status_code=403)
    else:
        response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


app.middleware('http')(log_request)

app.include_router(auth_router, prefix='/api')
for router in (tasks_router, plans_router, commands_router, todos_router, balance_router, voice_router, google_router):
    app.include_router(router, prefix='/api', dependencies=[Depends(require_user)])


@app.get('/api/health', tags=['system'])
def health():
    with engine.connect() as connection:
        connection.execute(text('SELECT 1'))
    return {'status': 'ok', 'ai_configured': model_status(), 'ai_provider': config.AI_PROVIDER,
            'ai_model': config.ai_model(), 'ai_status_check': 'configuration' if config.AI_PROVIDER != 'ollama' else 'connection'}
