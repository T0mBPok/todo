from fastapi import FastAPI
from sqlalchemy import text
from app.core.database import engine
from app.core import config
from app.plans.ai import model_status
from app.tasks.router import router as tasks_router
from app.plans.router import router as plans_router

from app.voice.router import router as voice_router

app = FastAPI(title='Voice ToDo', version='0.1.0')
app.include_router(tasks_router, prefix='/api')
app.include_router(voice_router, prefix='/api')
app.include_router(plans_router, prefix='/api')

@app.get('/api/health', tags=['system'])
def health():
    with engine.connect() as connection:
        connection.execute(text('SELECT 1'))
    return {'status': 'ok', 'ai_configured': model_status(), 'ai_provider': config.AI_PROVIDER, 'ai_model': config.ai_model(), 'ai_status_check': 'configuration' if config.AI_PROVIDER!='ollama' else 'connection'}

from app.commands.router import router as commands_router
app.include_router(commands_router,prefix="/api")

from app.todos.router import router as todos_router
app.include_router(todos_router,prefix="/api")

from app.balance.router import router as balance_router
app.include_router(balance_router,prefix="/api")
