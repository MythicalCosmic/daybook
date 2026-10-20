# Deploying

Everything runs with Docker Compose on one Linux server. Caddy sits in front and gets the HTTPS certificate by itself, which matters because Telegram only opens mini apps over HTTPS.

You need:

- a server with Docker and Compose v2.24 or newer (2 GB of memory is enough to start; 4 GB once AI and PDFs are in use)
- a domain or subdomain whose DNS `A` record points at the server, for example `tasks.example.com`
- ports 80 and 443 open to the internet

The examples below use the production bots **@daily_taskmanagment_bot** (employees) and **@owner_taskmanagment_bot** (owners).

## 1. Set up the bots in @BotFather

**The employee bot** (for example @daily_taskmanagment_bot):

1. `/newbot` creates it. Keep the token, and note the username without the `@`.
2. Leave **Allow groups** on (it is by default), so the bot can be added to company groups. Group privacy can stay on: commands and replies to the bot still reach it.
3. Optional: `/setmenubutton` with the URL `https://<your domain>/app/` puts the mini app on the chat's menu button. The bot also shows an "Open app" button by itself.

**The owner bot** (for example @owner_taskmanagment_bot). Owners create their company here, confirm dashboard sign-ins, and get briefings and approvals. It is optional: without it, the employee bot confirms sign-ins and delivers owner notifications.

1. `/newbot` creates it. Keep the token and the username.
2. `/setmenubutton`, pick the owner bot, send the URL `https://<your domain>/dashboard/` and the title `Dashboard`. The dashboard then opens inside Telegram, signed in.
3. `/setjoingroups` → **Disable**: the owner bot only works in private chats.

The bots set their own command menus when they start. Run only one copy of each bot per token: two copies polling with the same token keep interrupting each other.

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
| `EMPLOYEE_BOT_TOKEN`, `EMPLOYEE_BOT_USERNAME` | from BotFather, e.g. `daily_taskmanagment_bot` |
| `OWNER_BOT_TOKEN`, `OWNER_BOT_USERNAME` | from BotFather, e.g. `owner_taskmanagment_bot` (leave empty to run without the owner bot) |
| `EMPLOYEE_MINIAPP_URL` | `https://<your domain>/app/` |
| `DASHBOARD_URL` | `https://<your domain>/dashboard/` |
| `PLATFORM_ADMIN_TG_IDS` | your Telegram id (@userinfobot tells you) |
| `TELEGRAM_DRY_RUN` | `false` |
| `FIELD_ENCRYPTION_KEY` | a Fernet key: `python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"` |
| `FIELD_HASH_KEY` | another long random string |
| `COMPANY_SIGNUP` | `code` (default: a new owner needs a signup code from you), `open` (anyone may create a company in the owner bot) or `off` |

Optional:

| Setting | Value |
|---|---|
| `ANTHROPIC_API_KEY` | turns on the AI features. Each company still opts in under Settings → AI. Without a key everything else works and briefings use templates |
| `AI_GLOBAL_MONTHLY_CAP_USD` | what all companies together may spend on AI in a month (default 200). Also set a spend limit in the Anthropic Console as a backstop |
| `OWNER_ACCESS_TOKEN_MINUTES`, `OWNER_INIT_DATA_MAX_AGE` | dashboard session lengths (defaults 15 minutes and an hour) |

**Keep `FIELD_ENCRYPTION_KEY` and `FIELD_HASH_KEY` safe and never change them once people's data is stored**: passport, PINFL and card numbers are encrypted with them, and a lost key means those values are gone. To rotate the encryption key, put the new key first and keep the old one after a comma.

The `DATABASE_URL` and `REDIS_URL` lines are for local development; the containers use their own. `POSTGRES_PASSWORD` only takes effect when the database is first created.

## 3. Start it

```bash
make prod-up                              # build and start everything
make prod-manage cmd=createsuperuser      # your admin login
```

Then:

1. `https://<your domain>/health/` should say `"status": "ok"`.
2. **A company.** With the owner bot: send it `/new` (with `COMPANY_SIGNUP=code`, first create a signup code in Django admin and open the link it gives). Without it: sign in at `https://<your domain>/admin/`, create the company and add yourself as its Owner.
3. Open `https://<your domain>/dashboard/` and sign in with Telegram, or tap the owner bot's **Dashboard** button.
4. Copy the employee invite link from the dashboard (or the company page in Django admin), send `/start` to the employee bot from your own account, then open the link from someone else's to try the join flow.

When HTTPS works, set `DJANGO_SECURE_HSTS_SECONDS=31536000` in `.env` and run `make prod-up` again.

**Upgrading from a version without the owner dashboard:** run `make prod-manage cmd=sanitize_media` once. It re-encodes the proof photos uploaded before uploads were sanitized and moves aside anything that isn't a real image.

## What runs

| Service | What it does |
|---|---|
| `caddy` | HTTPS, uploaded photos at `/media/` (sandboxed: browsers never run them), AI answer streams to `stream`, everything else to Django |
| `backend` | Django with gunicorn: API, admin, the mini app at `/app/`, the owner dashboard at `/dashboard/`, signed private file downloads. When it starts it applies migrations and fills in default rows for every company (`ensure_company_defaults`) |
| `worker` | Celery on the `celery` and `default` queues: notifications, group posts, exports, reports |
| `ai-worker` | Celery on the `ai` queue (four at a time): AI answers, receipt reading, briefings. AI calls take seconds, so they never hold up reminders |
| `stream` | uvicorn (ASGI) on port 8001: live AI answers as server-sent events at `/api/v1/owner/ai/turns/…` |
| `beat` | Celery beat: daily tasks, reminders, digests, reports and every module's schedule |
| `employee_bot` | the employee bot, polling Telegram |
| `owner_bot` | the owner bot, polling Telegram; idle when `OWNER_BOT_TOKEN` is empty |
| `db`, `redis` | PostgreSQL and Redis |
| `backup` | a compressed database dump and an archive of the private files every night |

Uploads live in two volumes: `trello911_media` (proof photos, logos, avatars: public at unguessable addresses) and `trello911_private_media` (receipts, Z-reports, documents, contracts, payslips and exports: never served by Caddy, only through short-lived signed links that re-check the person's access).

## Updating

```bash
git pull
make prod-up
```

Migrations and company defaults run when the backend starts.

## Logs

`make prod-logs` follows every service. For one of them: `docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f backend`.

## Backups

- **Database and private files.** The `backup` service writes `backups/trello-<date>.sql.gz` and `backups/private-media-<date>.tgz` every night and keeps 14 days of each. `make prod-backup` dumps the database right away. Copy the `backups` folder off the server regularly: the private files include contracts and ID scans, so store the copies encrypted.
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

- **Restoring the private files** (with the stack stopped):

  ```bash
  docker run --rm -v trello911_private_media:/private_media -v "$PWD/backups":/backups alpine \
    sh -c 'tar xzf /backups/private-media-<date>.tgz -C /private_media && chown -R 10001 /private_media'
  ```

  Restore the database and the private files from the same night, and keep the same `FIELD_ENCRYPTION_KEY` and `FIELD_HASH_KEY`.
