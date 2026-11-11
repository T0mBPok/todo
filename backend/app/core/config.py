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
if AI_PROVIDER not in {'ollama','dashscope','openrouter','gigachat'}:
    raise ValueError('AI_PROVIDER должен быть ollama, dashscope, openrouter или gigachat')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY','').strip()
OPENROUTER_MODEL = os.getenv('OPENROUTER_MODEL','nvidia/nemotron-3.5-super-vl:free').strip()
OPENROUTER_RESPONSE_FORMAT = os.getenv('OPENROUTER_RESPONSE_FORMAT','json_object').strip()
if OPENROUTER_RESPONSE_FORMAT not in {'json_object','json_schema'}:
    raise ValueError('OPENROUTER_RESPONSE_FORMAT должен быть json_object или json_schema')
DASHSCOPE_API_KEY = os.getenv('DASHSCOPE_API_KEY','').strip()
DASHSCOPE_MODEL = os.getenv('DASHSCOPE_MODEL','qwen3.7-plus').strip()
DASHSCOPE_BASE_URL = os.getenv('DASHSCOPE_BASE_URL','https://dashscope-intl.aliyuncs.com/compatible-mode/v1').rstrip('/')

PUBLIC_ORIGIN = os.getenv('PUBLIC_ORIGIN', 'http://localhost:5173').rstrip('/')
SECURE_COOKIES = PUBLIC_ORIGIN.startswith('https://')
if not SECURE_COOKIES and PUBLIC_ORIGIN not in {'http://localhost:5173', 'http://127.0.0.1:5173'}:
    raise ValueError('PUBLIC_ORIGIN должен использовать HTTPS вне localhost.')
if SECURE_COOKIES and DATABASE_URL.password in {'todo_local_change_me', 'CHANGE_ME', ''}:
    raise ValueError('Укажите отдельный пароль PostgreSQL для публичного режима.')
ALLOWED_ORIGINS = {PUBLIC_ORIGIN} if SECURE_COOKIES else {'http://localhost:5173', 'http://127.0.0.1:5173'}
TRUSTED_PROXIES = set(os.getenv('TRUSTED_PROXIES', '').split())
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', '')
GOOGLE_TOKEN_KEY = os.getenv('GOOGLE_TOKEN_KEY', '')

SMTP_HOST = os.getenv('SMTP_HOST', '')
SMTP_TLS = os.getenv('SMTP_TLS', 'starttls')
if SMTP_TLS not in {'implicit', 'starttls'}:
    raise ValueError('SMTP_TLS must be implicit or starttls.')
SMTP_PORT = int(os.getenv('SMTP_PORT') or (465 if SMTP_TLS == 'implicit' else 587))
SMTP_FROM = os.getenv('SMTP_FROM', '')
SMTP_USERNAME = os.getenv('SMTP_USERNAME', '')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
EMAIL_CODE_KEY = os.getenv('EMAIL_CODE_KEY', '')

GIGACHAT_AUTH_KEY = os.getenv('GIGACHAT_AUTH_KEY', '').strip()
GIGACHAT_MODEL = os.getenv('GIGACHAT_MODEL', 'GigaChat-2').strip()

def ai_model():
    if AI_PROVIDER == 'gigachat':
        return GIGACHAT_MODEL
    if AI_PROVIDER=='dashscope':return DASHSCOPE_MODEL
    return OPENROUTER_MODEL if AI_PROVIDER=='openrouter' else OLLAMA_MODEL
