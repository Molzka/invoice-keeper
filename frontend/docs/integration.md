# Подключение API

## Почему в real-режиме появляется 404

Проверено на `main` на коммите `f9976fa1af63d863dbf4cdd3d58ed5a631743fa7` (24.10.2026): `backend/app/main.py` подключает маршруты авторизации и пользователей. Маршруты платежей пока не опубликованы. `GET /api/v1/payments/summary` и `GET /api/v1/payment-occurrences` в этой сборке возвращают 404 «Маршрут не найден».

Источники: [подключение backend routers](https://github.com/Molzka/invoice-keeper/blob/f9976fa1af63d863dbf4cdd3d58ed5a631743fa7/backend/app/main.py), [состояние интеграции в README](https://github.com/Molzka/invoice-keeper/blob/f9976fa1af63d863dbf4cdd3d58ed5a631743fa7/README.md).

Фронтенд использует пути из `docs/api-contract.md`. Изменение URL на случайный соседний маршрут не подключает платёжный сервис. Для реальных данных backend должен реализовать и подключить:

- `GET /api/v1/payments/summary`;
- `GET /api/v1/payment-occurrences`, `GET/PATCH /api/v1/payment-occurrences/{id}`;
- `GET/POST /api/v1/recurring-payments`, `DELETE /api/v1/recurring-payments/{id}`.

404 коллекции отображается как недоступный платёжный API с адресом запроса в раскрываемых технических деталях. Обычный 404 конкретного периода сохраняет сообщение сервера. 503 `PERIODS_NOT_READY` сохраняет отдельное состояние ожидания. Ошибки не подменяются демонстрационными данными или нулевыми итогами.

## Демонстрация интерфейса

Для текущего `main`, где платежи ещё разрабатываются, используйте `mock`:

- локально: `VITE_API_MODE=mock` в `.env.local`, затем перезапуск Vite;
- общий Docker Compose: `FRONTEND_API_MODE=mock` в корневом `.env`, затем `docker compose up -d --build frontend`.

Это демонстрация с тестовыми аккаунтами и фиксированной датой. Данные авторизации и пользователей в таком режиме также демонстрационные.

## Реальный backend

После подключения платёжного модуля:

- локально: `VITE_API_MODE=real`, `VITE_API_BASE_URL=/api/v1`, `API_PROXY_TARGET=http://127.0.0.1:8000`, затем перезапуск Vite;
- Docker Compose: `FRONTEND_API_MODE=real`, затем `docker compose up -d --build frontend`.

`VITE_*` в Docker встраиваются во время сборки. Одного перезапуска готового контейнера недостаточно. Платёжные запросы должны доходить через same-origin `/api/v1` до backend. Клиент отправляет cookie, получает CSRF из login/me и передаёт `X-CSRF-Token` при изменениях. Создающий POST после тайм-аута не повторяется автоматически.

Проверка подключения: реальный вход → `/auth/me` → сводка и список периодов → создание регулярного платежа → оплата периода → исправление даты → отмена отметки → история прекращённого платежа. Итоги остаются серверными, суммы передаются строками.
