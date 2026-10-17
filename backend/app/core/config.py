import os
from sqlalchemy import URL

DATABASE_URL = URL.create(
    'postgresql+psycopg', username=os.getenv('DB_USER', 'todo'),
    password=os.getenv('DB_PASSWORD', 'todo_local_change_me'),
    host=os.getenv('DB_HOST', 'db'), database=os.getenv('DB_NAME', 'todo'),
)
OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://host.docker.internal:11434').rstrip('/')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'qwen3.5:4b')
