# Telegram-модуль Invoice Keeper

Этот каталог содержит бота aiogram, cookie-клиент API, форматирование сообщений, `Dockerfile`, `.dockerignore` и зафиксированные Python-зависимости. Общий Compose находится [в корне проекта](../compose.yaml).

Из корня репозитория (перед запуском бота задайте `API_BASE_URL` и `API_ORIGIN` по [инструкции локального запуска](../docs/operations/telegram.md#локальный-запуск-из-каталога-проекта)):

```sh
uv sync --locked --directory telegram
uv run --locked --project telegram python -X utf8 telegram/smoke.py --dry-run
uv run --locked --project telegram python -X utf8 telegram/bot.py
```

`--locked` проверяет зафиксированные зависимости, а `-X utf8` включает корректный вывод кириллицы и символов Telegram в Windows. Локальные процессы читают корневой `.env`. Копировать его в `telegram/.env` не нужно; переменные окружения процесса имеют приоритет. Smoke по умолчанию печатает примеры, реальная отправка требует явного `--send`.

В Docker рабочий каталог остаётся `/app`, поэтому команда проверки прежняя:

```sh
docker compose run --rm --no-deps bot python smoke.py --dry-run
```

Бот читает API под обычным пользователем и принимает команды только в разрешённом для финансовых данных чате. Автоматические напоминания отправляет backend worker через постоянную очередь, отдельного планировщика в боте нет.

[Настройка, команды и диагностика](../docs/operations/telegram.md) · [Карта репозитория](../docs/development/repository-structure.md) · [Проверки](../docs/development/checks.md)
