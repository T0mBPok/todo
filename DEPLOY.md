# Развёртывание Импульса на VPS

Используйте Docker Engine и Docker Compose на VPS. Проект можно перенести через Git. Создайте отдельный серверный файл командой `cp .env.server.example .env` и ограничьте доступ командой `chmod 600 .env`.

| Настройка | Значение на VPS |
| --- | --- |
| `PUBLIC_ORIGIN` | Точный адрес сайта, например `https://todo.example.com`. Укажите домен, с которого браузер открывает приложение. |
| `POSTGRES_PASSWORD` | Новый случайный пароль для пустого серверного тома. Сгенерируйте командой `openssl rand -hex 32`. При наличии серверного тома сначала проверьте пароль существующей роли PostgreSQL. |
| `POSTGRES_DB`, `POSTGRES_USER` | Можно оставить `todo`. |
| `AI_PROVIDER` | Оставьте `openrouter` для нынешней модели Nemotron и перенесите рабочий ключ. Для своей Qwen на отдельном Ollama укажите `ollama`, `OLLAMA_MODEL` и `OLLAMA_BASE_URL` с адресом, доступным из контейнера backend по приватной сети. |
| `SMTP_*`, `EMAIL_CODE_KEY` | Можно перенести текущие значения защищённым способом. Проверьте доступность SMTP с VPS и доставку кода на тестовый ящик. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_TOKEN_KEY` | Можно перенести текущие значения. В Google Cloud добавьте `https://todo.example.com/api/google/callback` в список разрешённых redirect URI для веб-клиента. |
| `SPEECH_URL`, `SPEECH_LOCAL_FALLBACK` | Для VPS с 2 ГБ оставьте `SPEECH_LOCAL_FALLBACK=0`. Укажите базовый адрес внешнего сервиса GigaAM в приватной сети. Пустой `SPEECH_URL` отключает распознавание и оставляет текстовый ввод. |

На VPS с 2 ГБ запустите только веб-приложение и PostgreSQL. Compose подтянет базу как зависимость backend.

```sh
docker compose config --quiet
docker compose up -d --build --wait backend frontend
docker compose ps
curl -fsS http://127.0.0.1:5173/api/health
```

На сервере с достаточной памятью для локальной GigaAM укажите `SPEECH_URL=http://speech:8001` и запустите все сервисы командой `docker compose up -d --build --wait`.

Направьте DNS-запись домена на публичный IPv4 VPS. На хосте настройте HTTPS reverse proxy к `127.0.0.1:5173`. Пример Caddyfile:

```caddyfile
todo.example.com {
    reverse_proxy 127.0.0.1:5173
}
```

Откройте входящие TCP 80 и 443 для Caddy. Оставьте порты PostgreSQL, backend и frontend закрытыми снаружи. Для публичного доступа нескольким пользователям отдельно настройте ограничения на вход по IP на внешнем прокси или проверенную передачу IP в backend.

Проверьте с браузера регистрацию с кодом, вход, создание задачи и подключение Google. Если нужна речь, проверьте запись через HTTPS. Новый серверный том PostgreSQL создаётся пустым. Для переноса локальных аккаунтов, календарей и задач потребуется отдельный экспорт и импорт БД.
