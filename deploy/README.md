# Bot through systemd + PostgreSQL in Docker

This is a standalone deployment for this repository only.  The Telegram bot
runs as a systemd service; PostgreSQL is the sole Docker container and listens
only on `127.0.0.1:5432`.  It does not use or modify 2PAY API or any other bot
on the VPS.

## 1. Copy the project and create a service user

```bash
sudo mkdir -p /opt/appstore_bot
# Copy the repository contents to /opt/appstore_bot by git clone or SCP.
sudo useradd --system --home /opt/appstore_bot --shell /usr/sbin/nologin appstorebot
sudo chown -R appstorebot:appstorebot /opt/appstore_bot
cd /opt/appstore_bot
```

Install Python 3.10+ and the venv package if they are absent, then install the
bot's dependencies under its service user:

```bash
python3 --version
sudo -u appstorebot python3 -m venv .venv
sudo -u appstorebot .venv/bin/pip install --upgrade pip
sudo -u appstorebot .venv/bin/pip install -r requirements.txt
```

## 2. Create the two private environment files

The bot and PostgreSQL use the same password, but the database container must
not receive the bot token.  Therefore use two files:

```bash
sudo -u appstorebot cp deploy/bot.env.example .env
sudo -u appstorebot cp deploy/db.env.example .db.env
sudo -u appstorebot nano .env
sudo -u appstorebot nano .db.env
sudo chmod 600 .env .db.env
```

Set `TEST_MODE=False`, `BOT_TOKEN`, `ADMIN_CHAT_ID`, `ADMIN_IDS`, and the active
database settings in `.env`.  Leave `PAYMENT_PROVIDER=disabled` and do not add
payment-provider credentials. Generate a strong password with `openssl rand
-base64 32`, put it in `.db.env`, and copy exactly the same value to
`DB_PASSWORD` in `.env`.

## 3. Add the Google Sheets credential

```bash
sudo -u appstorebot mkdir -p secrets imports
sudo chmod 700 secrets imports
# Upload the existing service-account file as secrets/creds.json.
sudo chown appstorebot:appstorebot secrets/creds.json
sudo chmod 600 secrets/creds.json
```

The bot reads this exact file at startup.  Never add it to Git.

## 4. Start the PostgreSQL container

First make sure TCP port 5432 is unused.  A bot with only a file database does
not normally use it.

```bash
sudo ss -ltnp | grep ':5432' || true
sudo docker run -d \
  --name appstore-bot-db \
  --restart unless-stopped \
  --env-file /opt/appstore_bot/.db.env \
  -p 127.0.0.1:5432:5432 \
  -v appstore_bot_postgres_data:/var/lib/postgresql/data \
  -v /opt/appstore_bot/db/init/001_bot_schema.sql:/docker-entrypoint-initdb.d/001_bot_schema.sql:ro \
  postgres:16-alpine
```

Wait until it is ready:

```bash
sudo docker exec appstore-bot-db pg_isready -U bot -d appstore_bot
```

The SQL schema runs only on the first creation of the named Docker volume.

## 5. Import the old bot database

Upload `botdb.sql` privately to `/opt/appstore_bot/imports/botdb.sql`, grant
the service user read access, then make a dry run.  It validates the dump and
target relations, but writes nothing:

```bash
sudo chown appstorebot:appstorebot /opt/appstore_bot/imports/botdb.sql
sudo chmod 600 /opt/appstore_bot/imports/botdb.sql
```

```bash
cd /opt/appstore_bot
sudo -u appstorebot .venv/bin/python scripts/migrate_legacy_botdb.py \
  imports/botdb.sql --env-file .env
```

The expected source count is 4,945 users, 1,908 transactions, 21 invite links,
and 20 referrals.  If the old server deliberately used the Moscow timezone,
append `--source-timezone Europe/Moscow` to both commands.  Otherwise keep the
default `UTC`.

After a successful dry run, apply it:

```bash
sudo -u appstorebot .venv/bin/python scripts/migrate_legacy_botdb.py \
  imports/botdb.sql --env-file .env --apply
```

## 6. Start the systemd service

```bash
sudo cp deploy/appstore-bot.service /etc/systemd/system/appstore-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now appstore-bot.service
sudo systemctl status appstore-bot.service
sudo journalctl -u appstore-bot.service -f
```

The startup log must contain `Shared database schema verified`.  Then send
`/start` to the bot and test an admin command.  Stop any old process using this
same `BOT_TOKEN` before this step.

The bot uses long polling and deletes its old Telegram webhook at startup, so
it needs no nginx or public port. Direct payment creation and payment webhooks
are deliberately disabled; the bot only directs users to TMA and serves the
bot-side code/referral flows after a confirmed purchase.
