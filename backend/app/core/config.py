import os
from sqlalchemy import URL

DATABASE_URL = URL.create(
    'postgresql+psycopg', username=os.getenv('DB_USER', 'todo'),
    password=os.getenv('DB_PASSWORD', 'todo_local_change_me'),
    host=os.getenv('DB_HOST', 'db'), database=os.getenv('DB_NAME', 'todo'),
)
OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://host.docker.internal:11434').rstrip('/')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'qwen3.5:4b')

AI_PROVIDER = os.getenv('AI_PROVIDER','ollama').strip().lower()
if AI_PROVIDER not in {'ollama','dashscope','openrouter'}:
    raise ValueError('AI_PROVIDER должен быть ollama, dashscope или openrouter')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY','').strip()
OPENROUTER_MODEL = os.getenv('OPENROUTER_MODEL','nvidia/nemotron-3.5-super-vl:free').strip()
OPENROUTER_RESPONSE_FORMAT = os.getenv('OPENROUTER_RESPONSE_FORMAT','json_object').strip()
if OPENROUTER_RESPONSE_FORMAT not in {'json_object','json_schema'}:
    raise ValueError('OPENROUTER_RESPONSE_FORMAT должен быть json_object или json_schema')
DASHSCOPE_API_KEY = os.getenv('DASHSCOPE_API_KEY','').strip()
DASHSCOPE_MODEL = os.getenv('DASHSCOPE_MODEL','qwen3.7-plus').strip()
DASHSCOPE_BASE_URL = os.getenv('DASHSCOPE_BASE_URL','https://dashscope-intl.aliyuncs.com/compatible-mode/v1').rstrip('/')

def ai_model():
    if AI_PROVIDER=='dashscope':return DASHSCOPE_MODEL
    return OPENROUTER_MODEL if AI_PROVIDER=='openrouter' else OLLAMA_MODEL
