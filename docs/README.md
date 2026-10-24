# Вики Invoice Keeper

Начните с [быстрого запуска](../README.md#локальный-запуск). Если нужно разобраться в коде, откройте [карту репозитория](development/repository-structure.md): она объясняет связь API, интерфейса, Telegram, worker и проверок.

## Запуск и эксплуатация

- [Docker, миграции, обновление и логи](operations/deployment.md).
- [Настройки приложения](operations/configuration.md): доступ сотрудников, уточнение о регистрации, права, пароли, часовой пояс и OpenAPI.
- [Заявки сотрудников и защита входа](operations/account-security.md): одобрение, добровольная MFA, личный Telegram, резервные коды и настройка ключей.
- [Telegram](operations/telegram.md): команды, локальный запуск, подключение API и проверка без отправки.
- [Доставка напоминаний](operations/reminder-integration.md): очередь, состояния, повторы и восстановление.
- [Резервная копия и восстановление](operations/backups.md).
- [Тестовые данные и демонстрация](operations/demo-data.md): отдельный стенд и полный сценарий платежа.

## API и правила учёта

- [Обзор авторизации и правил](api/overview.md).
- [Контракт API v1](api/api-contract.md): запросы, ответы, периоды, даты, суммы и ошибки.
- [Смена собственного пароля](api/frontend-password-change.md).
- [Календарь и серверный журнал](api/calendar-audit-integration.md).
- [Бюджет и подтверждения оплаты](api/budget-receipts.md).
- [OpenAPI JSON](../backend/openapi.json); [обновление спецификации](development/backend.md#экспорт-openapi-для-передачи-решения).

## Разработка

- [Соответствие исходному ТЗ: правила, исправления и границы проверки](development/spec-compliance.md).
- [Карта репозитория: где менять и отлаживать](development/repository-structure.md).
- [Команда, зависимости, Git и миграции](development/team-workflow.md).
- [Локальный backend](development/backend.md).
- [Проверки API, Compose, браузера и Telegram](development/checks.md).
- [README frontend](../frontend/README.md) и [README Telegram](../telegram/README.md).

## Интерфейс

- [Подключение frontend к API](frontend/integration.md).
- [Ввод платежей, предварительные даты и фильтры](frontend/payment-workflow.md).
- [Календарь оплат и журнал действий](frontend/calendar-activity.md).
- [Смена пароля в интерфейсе](frontend/password-change.md).
- [Визуальное направление](frontend/design-direction.md) и [источники графики](frontend/asset-notes.md).
- [Скриншоты](frontend/screenshots/) находятся рядом с описаниями экранов; ссылки внутри документов сохранены.

## История решений и проверок

Эти документы сохраняют сведения своего этапа и не заменяют текущие инструкции или новый прогон проверок:

- [Первичные проверки интерфейса и последующие обновления](frontend/qa-report.md).
- [Обновление визуального оформления](frontend/visual-refresh.md).
- [Иллюстрации и отклик интерфейса](frontend/visual-polish.md).
- [Переписка о согласовании платежей и доставки](development/participant-2-reply.md).
