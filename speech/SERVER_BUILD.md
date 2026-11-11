# Сборка распознавания речи

В контейнере используется исходный чекпойнт GigaAM v3 e2e CTC и стандартный загрузчик GigaAM. Положите файлы `v3_e2e_ctc.ckpt` и `v3_e2e_ctc_tokenizer.model` в `speech/model-cache/`. Сборка сверяет SHA-256 обоих файлов. Модель не хранится в Git.

На ноутбуке исходные файлы сохранены в `~/.cache/voice-todo/gigaam-sber-2026-11-09/`. Перед сборкой на новом VPS перенесите их в его `speech/model-cache/`.

```bash
docker compose up -d --build --wait speech
```
