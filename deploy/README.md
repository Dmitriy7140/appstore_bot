# Развёртывание бота на отдельной VPS

Бот не подключается к PostgreSQL, не запускает Docker и не хранит клиентскую
базу. API на другой VPS хранит пользователей, платежи, транзакции, рефералов и
атрибуцию ссылок. Локальная SQLite нужна только для FSM, расписаний, Telegram
`file_id`, квитанций доставки API-событий и служебных флагов.

## 1. Установить бота

```bash
mkdir -p /opt/appstore_bot
cd /opt/appstore_bot
# Загрузить исходники сюда через git clone или SCP.
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
cp deploy/bot.env.example .env
nano .env
chmod 600 .env
```

Команды рассчитаны на вход под `root`; отдельный системный пользователь не
создаётся. Unit systemd также явно запускает процесс от `root`.

Нужны `BOT_TOKEN`, `ADMIN_CHAT_ID`, `ADMIN_IDS` и три секрета API:

- `TWO_PAY_API_WEBHOOK_TOKEN` = `BOT_WEBHOOK_TOKEN` на API;
- `TWO_PAY_API_INGEST_TOKEN` = `BOT_INGEST_API_TOKEN` на API;
- `TWO_PAY_API_AUDIENCE_TOKEN` = `BOT_AUDIENCE_API_TOKEN` на API;
- `TWO_PAY_API_BASE_URL=https://api.2pay.money`.
- `TWO_PAY_API_START_TIMEOUT_SECONDS=3` ограничивает ожидание регистрации
  пользователя при `/start`; при сбое меню всё равно откроется, а следующий
  `/start` безопасно повторит upsert.
- `TWO_PAY_API_INVENTORY_REFRESH_TIMEOUT_SECONDS=120` даёт административной
  команде обновления кодов достаточно времени на последовательные запросы к
  Google Sheets.
- `DAILY_SALES_REPORT_CHAT_ID=-1004486126389` — группа для ежедневной сводки
  продаж сайта. Отчёт уходит в `00:21` по Москве за предыдущий закрытый
  интервал API `[00:20; 00:20)`. Оставьте значение пустым, чтобы отключить
  публикацию.

`TWO_PAY_API_WEBHOOK_TOKEN` и токены API не являются Telegram-токеном.
SQLite по умолчанию находится в
`/var/lib/appstore-bot/appstore_bot.sqlite3`; каталог создаёт systemd через
`StateDirectory=appstore-bot`.

Кнопки App Store открывают `https://testamos.2pay.money?s=appstore`. Кнопки
PlayStation открывают секцию `?s=ps`; её старый `ps.html` продолжает читать
каталог и создавать заказы через PayZone, поэтому новый 2PAY API в
PlayStation-платежах не участвует.

## 2. Открыть только webhook API

Бот слушает `127.0.0.1:8081`. Проксируйте единственный путь через HTTPS, например
в Caddy:

```caddy
bot-api.example.com {
    reverse_proxy /internal/2pay/events 127.0.0.1:8081
}
```

На API установите:

```env
BOT_WEBHOOK_URL=https://bot-api.example.com/internal/2pay/events
BOT_WEBHOOK_TOKEN=<TWO_PAY_API_WEBHOOK_TOKEN>
BOT_INGEST_API_TOKEN=<TWO_PAY_API_INGEST_TOKEN>
BOT_AUDIENCE_API_TOKEN=<TWO_PAY_API_AUDIENCE_TOKEN>
```

Ограничьте этот URL firewall/IP allowlist, если у API статический IP.

## 3. Запустить systemd

```bash
cp deploy/appstore-bot.service /etc/systemd/system/appstore-bot.service
systemctl daemon-reload
systemctl enable --now appstore-bot.service
journalctl -u appstore-bot.service -f
```

Проверка: отправьте `/start`, выполните `/allusers` из админ-аккаунта и
`/announce`. Команда `/codes` показывает рабочий остаток кодов в PostgreSQL,
а `/refreshcodes` дозаполняет его из Google Sheets; обе доступны только
Telegram ID из `ADMIN_IDS`. В логе должны появиться запуск SQLite и API webhook.

## Резервная копия SQLite

Онлайн-копию можно сделать штатной командой SQLite:

```bash
mkdir -p /var/backups/appstore-bot
sqlite3 /var/lib/appstore-bot/appstore_bot.sqlite3 \
  ".backup '/var/backups/appstore-bot/appstore_bot.sqlite3'"
```

Не копируйте только основной файл обычным `cp`, пока сервис работает: в режиме
WAL часть последних записей может находиться в соседнем `-wal` файле.

## Ресурсы

Для обычной нагрузки достаточно 1 vCPU и 1 GB RAM: бот работает long polling,
aiohttp-webhook и короткими запросами к API. Добавьте 1 GB swap как защиту от
пиков при рассылках. При одновременных больших рассылках лучше 2 GB RAM, но
PostgreSQL на этой VPS не нужен.
