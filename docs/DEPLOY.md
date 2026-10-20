# Deploying

Everything runs with Docker Compose on one Linux server. Caddy sits in front and gets the HTTPS certificate by itself, which matters because Telegram only opens mini apps over HTTPS.

You need:

- a server with Docker and Compose v2.24 or newer (2 GB of memory is plenty to start)
- a domain or subdomain whose DNS `A` record points at the server, for example `tasks.example.com`
- ports 80 and 443 open to the internet

## 1. Set up the bot in @BotFather

1. `/newbot` creates the employee bot. Keep the token, and note the username without the `@`.
2. Leave **Allow groups** on (it is by default), so the bot can be added to company groups. Group privacy can stay on: commands and replies to the bot still reach it.
3. Optional: `/setmenubutton` with the URL `https://<your domain>/app/` puts the app on the chat's menu button. The bot also shows an "Open app" button by itself.

## 2. Get the code and fill in `.env`

```bash
git clone <repository> 911_trello
cd 911_trello
cp .env.example .env
```

In `.env`, set:

| Setting | Value |
|---|---|
| `DJANGO_SECRET_KEY` | a long random string: `python3 -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DJANGO_DEBUG` | `false` |
| `DOMAIN` | your domain, e.g. `tasks.example.com` |
| `DJANGO_ALLOWED_HOSTS` | the same domain |
| `POSTGRES_PASSWORD` | another long random string |
| `EMPLOYEE_BOT_TOKEN`, `EMPLOYEE_BOT_USERNAME` | from BotFather |
| `EMPLOYEE_MINIAPP_URL` | `https://<your domain>/app/` |
| `PLATFORM_ADMIN_TG_IDS` | your Telegram id (@userinfobot tells you) |
| `TELEGRAM_DRY_RUN` | `false` |

The `DATABASE_URL` and `REDIS_URL` lines are for local development; the containers use their own. `POSTGRES_PASSWORD` only takes effect when the database is first created.

## 3. Start it

```bash
make prod-up                              # build and start everything
make prod-manage cmd=createsuperuser      # your admin login
```

Then:

1. `https://<your domain>/health/` should say `"status": "ok"`.
2. Sign in at `https://<your domain>/admin/`, create the company and copy its invite link from the company page.
3. Send `/start` to the bot from your own account, then open the invite link from someone else's to try the join flow.

When HTTPS works, set `DJANGO_SECURE_HSTS_SECONDS=31536000` in `.env` and run `make prod-up` again.

## What runs

| Service | What it does |
|---|---|
| `caddy` | HTTPS, uploaded photos at `/media/`, everything else to Django |
| `backend` | Django with gunicorn: API, admin, the mini app at `/app/`. Applies migrations when it starts |
| `worker` | Celery: sends notifications and group posts |
| `beat` | Celery beat: daily tasks, reminders, digests and reports on schedule |
| `employee_bot` | the employee bot, polling Telegram |
| `db`, `redis` | PostgreSQL and Redis |
| `backup` | a compressed database dump every night |

Run only one copy of the bot for a token: two bots polling with the same token keep interrupting each other.

## Updating

```bash
git pull
make prod-up
```

Migrations run when the backend starts.

## Logs

`make prod-logs` follows every service. For one of them: `docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f backend`.

## Backups

- **Database.** The `backup` service writes `backups/trello-<date>.sql.gz` every night and keeps 14 days. `make prod-backup` makes one right away. Copy the `backups` folder off the server regularly.
- **Uploaded photos.** They live in the `trello911_media` volume:

  ```bash
  docker run --rm -v trello911_media:/media -v "$PWD/backups":/backups alpine \
    tar czf /backups/media-$(date +%F).tgz -C /media .
  ```

- **Restoring the database** into a fresh one:

  ```bash
  P="docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile app"
  $P down
  docker volume rm trello911_pgdata
  $P up -d db
  gunzip -c backups/trello-<date>.sql.gz | $P exec -T db psql -U trello trello
  make prod-up
  ```
