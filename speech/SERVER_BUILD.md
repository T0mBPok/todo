# Сборка распознавания речи на сервере

Из корня репозитория на Linux-сервере с Docker и Compose:

```bash
docker compose up -d --build
```

При первой сборке `speech` скачивает модель GigaAM v3 e2e CTC (~442 МБ), токенизатор и конфигурацию с [официальной публикации ai-sage на Hugging Face](https://huggingface.co/ai-sage/GigaAM-v3/tree/cec030b4c4f35d928e4a9044a3bdb29ebd499fac). Ревизия и SHA-256 файлов закреплены в Dockerfile. Старый CDN GigaAM и файлы из существующих контейнеров для сборки не нужны.

Первая сборка требует доступа к Hugging Face и его файловому CDN, Docker Hub и источникам зависимостей. Запущенный `speech` загружает модель из собранного образа и работает без внешней сети.
