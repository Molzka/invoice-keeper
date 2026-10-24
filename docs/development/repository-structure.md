# Как устроен репозиторий

Проект состоит из трёх приложений и общего окружения. Их исходники, зависимости и контейнеры разделены по каталогам; запуск всего стенда остаётся в корневом `compose.yaml`. Это позволяет менять одну часть, не смешивая её зависимости с другой.

## Карта каталогов

```text
invoice_keeper/
├── compose.yaml                 общий запуск сервисов
├── .env.example                 шаблон настроек Compose и локального Telegram
├── backend/                     FastAPI, модели, миграции, очередь worker
│   ├── app/                     API и бизнес-правила
│   ├── alembic/versions/         история схемы PostgreSQL
│   ├── scripts/                 утилиты самого backend: OpenAPI, test_postgres
│   └── pyproject.toml, uv.lock   зависимости backend
├── frontend/                    React, Vite, типы API и браузерные сценарии
├── telegram/                    aiogram, клиент API и форматирование сообщений
│   ├── Dockerfile, .dockerignore
│   └── pyproject.toml, uv.lock   зависимости Telegram
├── scripts/
│   ├── checks/                  проверки всего стенда
│   │   └── fixtures/            вспомогательные процессы и данные проверок
│   └── ops/db_backup.py         копирование и восстановление базы
└── docs/                        единая документация и снимки интерфейса
```

`backend/scripts/` нужен инструментам backend, а `scripts/checks/` проверяет взаимодействие сервисов. Например, экспорт OpenAPI работает в окружении Python API; проверка бота поднимает отдельные контейнеры API и PostgreSQL и обращается к ним через настоящую сеть приложения.

## Кто с кем общается

Браузер получает React-приложение у Nginx (`frontend`). Запросы `/api/v1` тот же Nginx передаёт в `backend`. FastAPI проверяет сессию, Origin и CSRF, затем читает или изменяет PostgreSQL.

Сервис `bot` из каталога `telegram/` принимает команды Telegram и читает API под отдельным обычным пользователем. Он не подключается к PostgreSQL. Сервис `worker` использует код backend, читает постоянную очередь в БД и отправляет готовые напоминания через Telegram-транспорт. Поэтому `bot` и `worker` имеют разные задачи: polling команд и доставка очереди.

В `compose.yaml` находятся сервисы `postgres`, `backend`, `worker`, `frontend`, `bot`, общая сеть, том базы и ограничения логов. У Telegram собственный контекст сборки `telegram/`; у backend и frontend — свои Dockerfile. Корневой Compose не нужно копировать внутрь приложений.

## Где менять задачу

| Задача | Основные файлы | Как проверить |
| --- | --- | --- |
| Поля API, авторизация, расчёт платежей | `backend/app/api/`, `schemas/`, `services/` | существующие backend-проверки, экспорт OpenAPI, [контракт](../api/api-contract.md) |
| Новая таблица или колонка | `backend/app/models/`, `backend/alembic/versions/` | миграция на отдельной БД; см. [правила команды](team-workflow.md) |
| Экран, форма, состояния загрузки | `frontend/src/` | lint, typecheck, build и подходящие существующие browser/E2E-сценарии |
| Команда и кнопка Telegram | `telegram/bot.py`, `telegram/texts.json` | `scripts/checks/check_bot_api.py`, локальный Telegram-адаптер |
| Запросы Telegram к API | `telegram/api.py` | та же проверка API, включая сессию и права чата |
| Вид карточки или сводки Telegram | `telegram/features.py`, `telegram/formatting.py` | smoke без отправки и существующая проверка команд |
| Расписание и повтор доставки | `backend/app/delivery/`, `backend/app/services/payment_source.py` | `scripts/checks/check_reminder_worker.py` |
| Контейнеры и переменные окружения | `compose.yaml`, Dockerfile приложений, `.env.example` | `docker compose config --quiet`, сборка и [проверки](checks.md) |
| Объяснение поведения | `docs/api`, `docs/frontend`, `docs/operations` | ссылки, команды и соответствие действующему коду |

## Как запускать и отлаживать

Для всего приложения начните с [быстрого запуска](../../README.md#локальный-запуск) и [подробной инструкции Docker](../operations/deployment.md). Из корня `docker compose ps -a` показывает состояния, `docker compose logs --tail=100 backend` — ошибки API; имя сервиса можно заменить на `frontend`, `bot` или `worker`.

Для локальной разработки зависимости устанавливаются отдельно:

```sh
# Из корня репозитория
uv sync --locked --directory backend
uv sync --locked --directory telegram
cd frontend
npm ci
```

Backend при запуске без Docker использует `backend/.env`: [подробные команды](backend.md). Локальный Telegram использует корневой `.env`, отдельный `telegram/.env` не нужен:

```sh
uv run --locked --project telegram python -X utf8 telegram/smoke.py --dry-run
uv run --locked --project telegram python -X utf8 telegram/bot.py
```

Эти две команды выполняются из корня. Внутри контейнера пути не меняются: `docker compose run --rm --no-deps bot python smoke.py --dry-run`. Для frontend команды выполняются в `frontend/`: `npm run dev`, `npm run typecheck`, `npm run lint`, `npm test`, `npm run build`. Подключение Vite к API описано в [README frontend](../../frontend/README.md).

## Проверки и операционные утилиты

Команды выполняются из корня репозитория. Для двух HTTP-проверок ниже заранее поднимите отдельный тестовый стенд, например на порту `8081`:

```sh
python scripts/checks/check_backend.py http://127.0.0.1:8081
python scripts/checks/check_bot_api.py --timezone Asia/Tokyo
python scripts/checks/check_reminder_worker.py
python scripts/checks/check_frontend.py http://127.0.0.1:8081 --api-ready
python scripts/ops/db_backup.py backup
```

`check_frontend.py` и `check_backend.py` работают с уже запущенным HTTP-стендом. Первая проверка читает сайт и API; вторая входит с `ADMIN_USERNAME` / `ADMIN_PASSWORD` тестового администратора из окружения и создаёт/удаляет тестовые аккаунты. Поэтому `check_backend.py` направляйте только на отдельный тестовый стенд, не на рабочую БД.

`check_bot_api.py` и `check_reminder_worker.py` сами поднимают изолированные контейнеры API/PostgreSQL и локальный Telegram-адаптер. `--help` показывает доступные настройки. В `scripts/checks/fixtures/` находятся вспомогательные адаптеры, проверки внутри контейнеров и тестовые данные; их не нужно запускать вместо обычного API или заполнять рабочими секретами.

`db_backup.py` — операционная утилита, а не тест: она работает с выбранным Compose-проектом. Восстановление создаёт отдельную БД и не переключает приложение на неё; порядок действий — в [инструкции резервного копирования](../operations/backups.md). Проверки с локальным Telegram-адаптером не подтверждают реальную доставку сообщения.

## Словарь

- **Сервис** — отдельный процесс в Compose: API, сайт, бот или worker.
- **Контекст сборки** — каталог файлов, доступных Dockerfile; `.dockerignore` исключает лишнее из этого каталога.
- **Миграция** — сохранённое изменение схемы БД, которое применяет Alembic.
- **Fixture** — вспомогательные данные или процесс для изолированной проверки.
- **Период платежа** — конкретное обязательство с отдельным сроком и состоянием оплаты; регулярное правило создаёт такие периоды.
- **Worker** — фоновый обработчик постоянной очереди; его результат отличается от ответа команды бота.

## Что делаем

- Общий список платежей со сроками, статусами и историей по месяцам.
- Подтверждение оплаты, отмена отметки и исправление фактической даты.
- Напоминания в Telegram за три дня до срока.
- Итоги отдельно в рублях, долларах и евро, без конвертации.
- Две роли: администратор управляет платежами и пользователями, остальные работают с оплатой.

## Стек

| Часть | Инструменты |
|---|---|
| Бэкенд | Python, FastAPI, SQLAlchemy async, asyncpg |
| База данных | PostgreSQL, миграции Alembic |
| Авторизация | Серверные сессии в PostgreSQL, HttpOnly cookie |
| Пароли | pwdlib с Argon2 |
| Фронтенд | React, TypeScript, Vite |
| Telegram | aiogram |
| Запуск | Docker Compose |
| Зависимости | uv для Python, npm для фронтенда |

Образы PostgreSQL `18.6-bookworm`, Node.js `24.22.1-bookworm-slim` и Nginx `1.30.6-alpine` закреплены по версии и digest. Для сборки фронтенда используется npm `11.6.2`; зависимости закреплены в `frontend/package-lock.json`. Python-зависимости закреплены в backend/uv.lock.
