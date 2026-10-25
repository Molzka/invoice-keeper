# Сервер с HTTPS по IP

Серверный запуск использует `compose.yaml` вместе с `compose.server.yaml`.
Caddy принимает HTTPS и автоматически продлевает сертификат Let's Encrypt для
публичного IP или доменного имени. Порты PostgreSQL, frontend и backend на хосте
не публикуются; наружу нужны TCP 80/443 и SSH.

Нужны Docker Engine, Compose v2 с поддержкой `!reset`, свободные TCP 80/443 и
исходящий HTTPS к реестрам образов, Let's Encrypt и Telegram. Конфигурация
проверена с Docker 29.1.3, Compose 2.40.3 и Caddy 2.11.7.

## Настройки

Разместите исходники в `/opt/invoice-keeper`, создайте `.env` из `.env.example`
и ограничьте доступ к нему: `chmod 600 .env`. Для Linux-сервера задайте:

```dotenv
COMPOSE_FILE=compose.yaml:compose.server.yaml
PUBLIC_HOST=<PUBLIC_IP>
APP_ENV=production
SESSION_COOKIE_SECURE=true
ALLOWED_ORIGINS='["https://<PUBLIC_IP>"]'
PANEL_URL=https://<PUBLIC_IP>
API_ORIGIN=https://<PUBLIC_IP>
API_BASE_URL=https://<PUBLIC_IP>/api/v1
FRONTEND_API_MODE=real
BOT_INTERNAL_BASE_URL=http://backend:8000
```

Замените `<PUBLIC_IP>` настоящим адресом. Задайте отдельные случайные значения
`POSTGRES_PASSWORD`, `ADMIN_PASSWORD`, `API_PASSWORD` и `BOT_INTERNAL_TOKEN`.
`ADMIN_USERNAME=admin`, а `API_USERNAME=telegram_bot` — отдельный обычный
пользователь, которого нужно создать после первого входа. Не используйте
администратора как учётную запись чтения API для бота.

Также заполните `BOT_TOKEN`, `BOT_USERNAME`, `CHAT_ID` и постоянный
`MFA_ENCRYPTION_KEY` по [инструкции безопасности](account-security.md).
Сохраните защищённую копию настроек отдельно от сервера: для восстановления
MFA нужен прежний ключ шифрования. Пароли и рабочий `.env` не коммитятся.

`API_BASE_URL` бота использует публичный HTTPS-адрес: браузерные сессии в
production имеют флаг Secure. Для настроенного IP HTTP-клиент бота принимает
cookie, сохраняя ограничения на хост и HTTPS. Приватные подтверждения оплаты
идут через Docker-сеть и отдельный `BOT_INTERNAL_TOKEN`.

## Первый запуск с новой базой

Выполняйте команды по очереди из `/opt/invoice-keeper`. Благодаря
`COMPOSE_FILE` в серверном `.env` обычный `docker compose` включает Caddy.

```sh
docker compose config --quiet
docker compose build backend worker frontend bot
docker compose pull postgres caddy
docker compose up -d --wait --wait-timeout 90 postgres
docker compose run --rm -T --no-deps backend alembic upgrade head
docker compose run --rm -T --no-deps backend alembic check
docker compose run --rm -T --no-deps backend python -m app.cli create-admin
docker compose up -d --wait --wait-timeout 90 backend frontend caddy
```

Дождитесь выпуска сертификата в `docker compose logs caddy` и проверьте сайт
без отключения проверки TLS. Войдите администратором и создайте пользователя
`telegram_bot` с паролем из `API_PASSWORD`, затем проверьте чтение:

```sh
docker compose run --rm -T --no-deps bot python smoke.py --backend --dry-run
python3 scripts/checks/check_frontend.py https://<PUBLIC_IP> --api-ready
```

Перед запуском Telegram остановите `bot` и `worker` на прежнем компьютере:
один токен должен иметь только один процесс polling. Затем на сервере:

```sh
docker compose up -d --no-deps bot worker
docker compose ps
docker compose logs --tail=50 bot worker
```

Проверьте polling, отсутствие перезапусков и `/api/v1/ready`. Проверка с
`--dry-run` не отправляет сообщения. В новой базе нет прежних расходов,
пользователей и привязок Telegram: сотрудники подключают свои аккаунты
заново. Привязка администратора по-прежнему задаётся через `ADMIN_TELEGRAM_ID`.

## Эксплуатация и возврат

- Сертификаты и ACME-аккаунт хранятся в `caddy_data`, конфигурация — в
  `caddy_config`, база — в `postgres_data`. Сервисы перезапускаются после
  перезагрузки хоста. Не используйте `docker compose down -v`.
- Для резервной копии: `umask 077; python3 scripts/ops/db_backup.py backup`.
  Создаваемые архивы находятся в `backups/`; восстановление проверяйте в
  отдельной базе по [инструкции](backups.md). Эта команда создаёт одну копию,
  а не расписание резервного копирования.
- После изменения Caddyfile выполните `docker compose exec -T caddy caddy
  validate --config /etc/caddy/Caddyfile --adapter caddyfile`, затем аналогичную
  команду с `reload` вместо `validate`.
- Для первоначального отката до начала работы с новой базой остановите
  серверные `bot worker` и только затем возобновите их на старом стенде.
  После появления новых платежей сначала сохраните обе базы: автоматического
  переноса изменений между ними нет.
- При доставке снимком исходников без `.git` сохраняйте базовую ревизию и
  SHA-256 применённых файлов в `DEPLOYMENT.json`. Обновляйте исходники вместе
  с серверной конфигурацией, сохраняя `.env` и тома. Для обновления схемы
  используйте [порядок с резервной копией и репетицией](deployment.md#обновление-рабочего-стенда-без-потери-данных).

IP-сертификат использует профиль `shortlived` и действует около шести дней;
Caddy продлевает его автоматически. Основание:
[Let's Encrypt](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability/),
[ACME profile в Caddy](https://caddyserver.com/docs/caddyfile/directives/tls#issuers).

## Ежедневные резервные копии

Для установки штатного таймера systemd на сервере:

```sh
install -m 644 docker/server/invoice-keeper-backup.service /etc/systemd/system/
install -m 644 docker/server/invoice-keeper-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now invoice-keeper-backup.timer
systemctl start invoice-keeper-backup.service
systemctl list-timers invoice-keeper-backup.timer
```

Копия создаётся ежедневно около 03:00 UTC (06:00 Europe/Moscow), с разбросом
до пяти минут. Пропущенный из-за выключения сервера запуск выполняется после
старта таймера. Автоматические архивы хранятся в `backups/daily` 14 дней;
устаревшие `postgres_*.dump` удаляются только после успешной новой копии.
Ручные архивы в `backups/` сохраняются. Каталог `daily` предназначен только
для автоматических копий. `UMask=0077` ограничивает доступ к файлам.

Проверка результата: `systemctl status invoice-keeper-backup.service` и
`journalctl -u invoice-keeper-backup.service`. При ошибке проверьте журнал и
повторите запуск; таймер не отправляет уведомления во внешние каналы.
Копии на этом VPS не защищают от потери самого VPS: внешнее хранилище
подключается отдельно. Проверять восстановление нужно в новой отдельной БД,
не поверх рабочей.

## Контроль worker

`docker compose ps` показывает health worker. Обработчик атомарно сохраняет
время последнего завершённого цикла в своём временном каталоге. Ошибка цикла
удаляет отметку; зависание обнаруживается по её возрасту. Docker проверяет
её каждые 30 секунд и после трёх неуспешных проверок показывает `unhealthy`.
В начале работы есть льготный период 60 секунд.

По умолчанию успешный цикл должен завершаться не реже раза в 300 секунд.
Для большого количества заданий/долгой отправки увеличьте
`WORKER_HEALTH_MAX_AGE_SECONDS` в `.env` и пересоздайте worker. Это контроль
завершения цикла: длительный, но работающий цикл тоже может превысить порог.
Статус health не перезапускает контейнер и не доказывает доставку каждого
сообщения. Проверяйте `failed` и `unknown` штатной CLI очереди; неизвестный
результат нельзя автоматически повторять. Публичный `/ready` по-прежнему
проверяет API/БД; состояние worker смотрите отдельно:

```sh
docker compose ps worker
docker compose exec -T worker python -m app.delivery.health
docker compose logs --tail=50 worker
```
