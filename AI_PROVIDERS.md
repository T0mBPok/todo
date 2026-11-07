# Провайдер ИИ

Официальный Qwen: `AI_PROVIDER=dashscope`, `DASHSCOPE_API_KEY` из Alibaba Cloud Model Studio, `DASHSCOPE_MODEL=qwen3.7-plus`. По умолчанию используется Singapore; для другого региона или workspace установите `DASHSCOPE_BASE_URL` из консоли (до `/compatible-mode/v1` включительно). После правки `.env`: `docker compose up -d backend`. Ключ OpenRouter здесь не подходит. Аудио распознаётся локальным GigaAM, внешней модели передаются текст и нужный календарный контекст.


Локально в `.env`: `AI_PROVIDER=ollama`. По умолчанию используется `qwen3.5:4b`, облако не вызывается.

Серверный шаблон `.env.server.example` настроен на OpenRouter и бесплатную модель Nemotron. В серверном `.env` задайте `AI_PROVIDER=openrouter`, `OPENROUTER_MODEL=nvidia/nemotron-3.5-super-vl:free` и свой `OPENROUTER_API_KEY`. Затем пересоздайте backend. В обоих облачных режимах Ollama на сервере не нужна. Если раньше добавляли сервис ollama в серверный Compose, удалите зависимость backend от него.

Ключ вводите только в серверный .env, не в frontend и не в чат. После изменения настроек: `docker compose up -d --build backend frontend` (с теми же -f файлами, что использованы для запуска). Файл .env исключён из Git. Не публикуйте вывод docker compose config: он содержит секреты.

OPENROUTER_MODEL — точный ID доступной модели. Бесплатные модели могут менять доступность и лимиты. `json_object` передаёт схему в инструкции и проверяет ответ существующими валидаторами. `json_schema` включайте только для модели/провайдера с поддержкой Structured Outputs. Автоматического переключения на платную модель или другого провайдера нет. Запросы не повторяются автоматически.

Все операции (нормализация речи, создание/редактирование календаря, балансировка, список задач, определение категории) используют один выбранный провайдер. Распознавание аудио остаётся в CPU-контейнере speech. OpenRouter получает текст и нужный контекст задач/календаря.

/api/health показывает провайдера и модель без ключа. Для OpenRouter ai_configured означает наличие конфигурации, а не проверку ключа и квоты: health не тратит API-запросы. Полноценную проверку выполните небольшой текстовой командой после ввода ключа.

## Облачный запуск без списаний

В Singapore → Usage & Billing → Free Quota проверьте остаток для точного ID `qwen3.7-plus`, включите Free Quota Only и дождитесь применения. Без этой настройки после квоты возможны списания. У `qwen-plus` бесплатной квоты для новых аккаунтов нет. [Условия Alibaba](https://www.alibabacloud.com/help/en/model-studio/new-free-quota).

Для существующей установки не перезаписывайте `.env` шаблоном: оставьте настройки БД и добавьте только `AI_PROVIDER=dashscope`, `DASHSCOPE_MODEL=qwen3.7-plus`, `DASHSCOPE_API_KEY` и адрес Singapore из `.env.server.example` или консоли. Пересоздайте backend: `docker compose up -d --build backend`.

Когда ограничение в консоли вступило в силу, выполните `docker compose exec -T backend python -m app.core.check_ai`. Это один запрос с тестовым текстом без данных календаря. Если квота отсутствует, оставьте `AI_PROVIDER=ollama` или используйте OpenRouter с моделью `:free`.
