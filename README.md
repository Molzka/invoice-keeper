# Invoice Keeper

Приложение для регулярных расходов команды: аренды, подписок, серверов и других платежей. Администратор добавляет расходы и пользователей, участники отмечают оплату, а worker напоминает о сроках в Telegram. Периоды, история и итоги RUB, USD и EUR хранятся отдельно, без конвертации валют.

Общий Docker Compose запускает PostgreSQL, FastAPI, React/Nginx, Telegram-бота и worker. Интерфейс по умолчанию работает с настоящим API и сохраняет данные в PostgreSQL. [Вики проекта](docs/README.md) содержит инструкции, контракты и объяснение устройства.

## Доступ для судей

**Сайт: [invoicekeeper.online](https://invoicekeeper.online)** — приложение уже запущено, устанавливать ничего не нужно.

На странице входа введите данные выбранной роли:

| Роль | Логин | Пароль |
| --- | --- | --- |
| Администратор | `admin` | `C8-BjRBe1RNH_uSOy6Y745HRg1JtgtnM` |
| Обычный пользователь | `judge` | `KOR9XgPhnLzHqYumX2Nv` |

Администратор управляет расходами и пользователями. Обычный пользователь просматривает расходы и отмечает оплату. Чтобы проверить обе роли одновременно, откройте второй аккаунт в приватном окне браузера; для смены роли в одном окне сначала выйдите из аккаунта.

Аккаунты общие для проверки проекта. Пожалуйста, не меняйте пароль пользователя `judge`, чтобы другие судьи тоже могли войти.

## Локальный запуск

Нужны Docker Desktop с Linux containers и Docker Compose v2. Все команды выполняются из корня репозитория.

1. Если `.env` ещё нет, создайте его из `.env.example`: `Copy-Item .env.example .env` в PowerShell или `cp .env.example .env` в Linux/macOS.
2. Заполните `POSTGRES_PASSWORD`, `ADMIN_USERNAME` и `ADMIN_PASSWORD` длиной 8–128 символов. Для существующей базы используйте прежний пароль PostgreSQL.
3. Соберите приложения и подготовьте базу:

```sh
docker compose config --quiet
docker compose build backend worker frontend
docker compose up -d --wait --wait-timeout 90 postgres
docker compose run --rm backend alembic upgrade head
```

4. Только для новой базы создайте первого администратора:

```sh
docker compose run --rm backend python -m app.cli create-admin
```

5. Запустите веб-панель и API:

```sh
docker compose up -d --wait --wait-timeout 90 backend frontend
docker compose ps
```

Откройте [localhost:8080](http://localhost:8080) и войдите созданным администратором. [Swagger](http://localhost:8080/api/v1/docs) описывает API; [ready](http://localhost:8080/api/v1/ready) проверяет подключение к БД.

Telegram подключается после заполнения `BOT_TOKEN` и получения `CHAT_ID` командой `/id`. Для чтения платежей ботом нужен отдельный обычный пользователь API. Порядок настройки и запуска `bot`/`worker` — в [инструкции Telegram](docs/operations/telegram.md). Не запускайте два polling-процесса с одним токеном.

Для полного сценария обязательно запустите `worker` по этой инструкции: он не только отправляет напоминания, но и создаёт следующие месячные периоды. Запуск только `backend` и `frontend` выше подготавливает веб-панель, но не включает фоновые задачи.

Для остановки используйте `docker compose stop`. Данные остаются в томе после обычного `docker compose down`; **`down -v` удаляет данные**. Обновление с миграциями, смена портов и диагностика описаны в [полной инструкции запуска](docs/operations/deployment.md).

## Карта проекта

| Каталог | Назначение |
| --- | --- |
| `backend/` | API, модели, миграции PostgreSQL и очередь напоминаний |
| `frontend/` | React-интерфейс, API-клиент и браузерные проверки |
| `telegram/` | Команды бота, клиент API, сообщения и отдельное окружение Python |
| `scripts/checks/` | Проверки взаимодействия сервисов и их `fixtures/` |
| `scripts/ops/` | Операционные утилиты, включая резервное копирование |
| `docs/` | Контракты, разработка, эксплуатация и скриншоты |

Общий запуск и окружение находятся в `compose.yaml` и корневом `.env`. Подробнее: [образовательная карта репозитория](docs/development/repository-structure.md).

## Дальше

- [Вики и полный индекс](docs/README.md).
- [Настройки, роли и часовой пояс](docs/operations/configuration.md).
- [Демонстрация с отдельной БД и тремя валютами](docs/operations/demo-data.md).
- [Контракт API](docs/api/api-contract.md) и [OpenAPI JSON](backend/openapi.json).
- [Разработка frontend](frontend/README.md), [backend](docs/development/backend.md) и [Telegram](telegram/README.md).
- [Командная работа и миграции](docs/development/team-workflow.md).
- [Проверки приложения](docs/development/checks.md).
- [Резервные копии](docs/operations/backups.md) и [доставка напоминаний](docs/operations/reminder-integration.md).
