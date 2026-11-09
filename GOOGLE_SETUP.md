# Подключение Google к «Импульсу»

Настройки ниже выполняет владелец приложения один раз. Пользователь входит в «Импульс», нажимает **Google → Подключить аккаунт Google**, выбирает аккаунт и даёт разрешение в окне Google. После возврата «Импульс» предлагает загрузить из Google **календарь**, **задачи** или оба пункта. **Позже** закрывает предложение и ничего не импортирует. Обмен остаётся доступен по кнопке **Google**.

## 1. Включить два API

Выберите один проект Google Cloud. В нём включите [Google Calendar API](https://console.cloud.google.com/apis/library/calendar-json.googleapis.com) и [Google Tasks API](https://console.cloud.google.com/apis/library/tasks.googleapis.com).

## 2. Заполнить Google Auth Platform

- **Branding → Get started:** название `Импульс`, почта поддержки и контактная почта.
- **Audience:** выберите **External** для личных аккаунтов Gmail. Для проверки оставьте **Testing** и добавьте аккаунт, которым будете подключать Google, в **Test users**.
- **Data Access → Add or Remove Scopes:** добавьте `openid`, `https://www.googleapis.com/auth/calendar.events.owned` и `https://www.googleapis.com/auth/tasks`. Текущая версия запрашивает разрешения на оба сервиса; после авторизации пользователь выбирает, какие данные загрузить.

[Инструкция Google по экрану согласия](https://developers.google.com/workspace/guides/configure-oauth-consent)

## 3. Создать OAuth-клиент

В том же проекте откройте **Google Auth Platform → Clients → Create client**. Тип — **Web application**, имя — `Импульс (локально)`. В **Authorized redirect URIs** добавьте:

```text
http://localhost:5173/api/google/callback
```

После создания сохраните **Client ID** и **Client secret**. Адрес должен точно совпадать с `${PUBLIC_ORIGIN}/api/google/callback`. Для локальной проверки открывайте `http://localhost:5173`; для сервера укажите его HTTPS-домен в `PUBLIC_ORIGIN` и добавьте соответствующий адрес возврата в Google.

[Инструкция Google по OAuth-клиенту](https://developers.google.com/identity/protocols/oauth2/web-server)

## 4. Добавить значения в проект

В корневом `.env` проекта `todo` заполните:

```dotenv
PUBLIC_ORIGIN=http://localhost:5173
GOOGLE_CLIENT_ID=идентификатор_из_Google
GOOGLE_CLIENT_SECRET=секрет_из_Google
GOOGLE_TOKEN_KEY=локальный_ключ_шифрования
```

`GOOGLE_TOKEN_KEY` генерируется один раз в терминале Ubuntu из папки проекта. Скопируйте выведенную строку в `.env`. Сохраните ключ между перезапусками: им зашифрованы уже сохранённые токены Google.

```bash
cd ~/projects/todo
docker compose exec -T backend python -c 'from cryptography.fernet import Fernet; print("GOOGLE_TOKEN_KEY=" + Fernet.generate_key().decode())'
```

После сохранения всех значений в `.env` пересоздайте backend:

```bash
docker compose up -d --no-deps --force-recreate backend
```

Ключи остаются в серверном `.env`. Не добавляйте их в репозиторий и не отправляйте в чат.

## 5. Проверить

Откройте [локальный «Импульс»](http://localhost:5173), войдите в учётную запись «Импульса» с подтверждённой почтой и нажмите **Google → Подключить аккаунт Google**. После согласия Google появится экран выбора. Приложение загружает события основного календаря и задачи списка по умолчанию. Настройка SMTP нужна для получения кода при регистрации в «Импульсе»; она отделена от Google OAuth.

Режим **Testing** подходит для перечисленных тестовых аккаунтов. Для такого внешнего OAuth-приложения токен обновления [действует 7 дней](https://developers.google.com/identity/protocols/oauth2#expiration). Для публичного доступа настройте Production и [верификацию Google](https://support.google.com/cloud/answer/13464321?hl=en).
