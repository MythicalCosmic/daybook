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
| `AI_SPEECH_URL` | where voice messages are turned into text, for voice tasks. `http://stt:8000/v1` is the server's own Whisper service (the `stt` container, no key needed; the deploy adds this line). Any OpenAI-compatible transcription endpoint works too, e.g. `https://api.openai.com/v1` with `AI_SPEECH_MODEL=gpt-4o-transcribe`, or `https://api.groq.com/openai/v1` with `whisper-large-v3`; the key goes in `AI_SPEECH_API_KEY`. Empty: no voice, typed text still becomes tasks |
| `STT_MODEL`, `STT_CPU_THREADS` | the Whisper model of the `stt` service (default `large-v3`, about 3 GB, downloaded on its first start) and how many CPU threads it may use (6) |
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
| `caddy` | HTTPS, uploaded photos at `/media/` (sandboxed: browsers never run them), AI answer streams to `stream`, the bytes of lesson videos once Django has checked their signed link (`X-Accel-Redirect`, below), everything else to Django |
| `backend` | Django with gunicorn (12 processes of 4 threads, `backend/config/gunicorn.conf.py`): API, admin, the mini app at `/app/`, the owner dashboard at `/dashboard/`, signed private file downloads. When it starts it applies migrations and fills in default rows for every company (`ensure_company_defaults`) |
| `worker` | Celery on the `celery` and `default` queues (8 processes, one job each at a time): notifications, group posts, exports, reports |
| `ai-worker` | Celery on the `ai` queue (four at a time): AI answers, receipt reading, briefings. AI calls take seconds, so they never hold up reminders |
| `media-worker` | Celery on the `media` queue, one job at a time on at most two CPUs: ffmpeg makes each uploaded lesson video into a 720p MP4 with a poster (`apps/learning/media.py`). A long video never slows the site or the other workers. In development the `worker` takes the `media` queue too |
| `stream` | uvicorn (ASGI) on port 8001: live AI answers as server-sent events at `/api/v1/owner/ai/turns/…` |
| `stt` | speech to text for voice tasks (`deploy/stt`): Whisper on the CPU behind an OpenAI-compatible endpoint, reached only by the other containers. One voice message at a time, so a burst queues instead of slowing the site; the model sits in the `stt_models` volume |
| `beat` | Celery beat: daily tasks, reminders, digests, reports and every module's schedule |
| `employee_bot` | the employee bot, polling Telegram |
| `owner_bot` | the owner bot, polling Telegram; idle when `OWNER_BOT_TOKEN` is empty |
| `db`, `redis` | PostgreSQL and Redis |
| `backup` | a compressed database dump and an archive of the private files every night |

Uploads live in three volumes: `trello911_media` (proof photos, logos, avatars: public at unguessable addresses), `trello911_private_media` (receipts, Z-reports, documents, contracts, payslips and exports: never served by Caddy, only through short-lived signed links that re-check the person's access) and `trello911_learning_media` (lesson videos and posters, private too).

### Lesson videos

Training (docs/PLAN-LEARNING.md §5) takes videos of up to 2 GB and 3 hours, in 8 MB pieces that resume after a dropped connection. The `media-worker` checks each upload's first bytes (only MP4/MOV/3GP and MKV/WebM are read, AVI and anything else is refused before ffmpeg sees it), then makes a 720p H.264 MP4 with AAC sound and a poster; the original is deleted. ffmpeg and ffprobe run with an explicit demuxer, `-protocol_whitelist file` and an empty environment, so a crafted file can't make them read other files.

- **Where they are**: the `learning_media` volume, mounted read-write in the app containers (`backend`, `worker`, `media-worker`, and the `ai-worker`, which reads it for transcripts) and read-only in `caddy` at `/srv/learning`. `LEARNING_MEDIA_ROOT` moves it outside containers.
- **Transcripts**: a manager can have an uploaded video written down (the lesson editor's "Write down from the video"). The `ai-worker` cuts 30-second pieces of the MP4's sound into mono Opus with the same hardened ffmpeg call and sends them, one task per piece, to the speech service voice drafts use (`AI_SPEECH_URL`), so voice drafts never wait behind a long lesson. The company's AI switch must be on; videos over an hour aren't written down. On the server's own CPU Whisper a 20-minute lesson takes roughly 20 to 50 minutes of one ai-worker process.
- **Serving**: a video link is a signed `/api/v1/files/…` link like any private file. In production `LEARNING_MEDIA_ACCEL=/_learning/` (set in `docker-compose.prod.yml`): Django checks the signature, the expiry and the person's access right now, then answers an empty `X-Accel-Redirect: /_learning/<path>`; Caddy's `handle_response` (`deploy/Caddyfile`) sends the file from its mount with Range requests (206), so seeking works and no gunicorn thread is held by a 2 GB download. Without the setting (development) Django streams the bytes itself, with Range requests too.
- **Limits**: each company may keep `storage_limit_mb` of video (10 GB by default; Settings › Training). Uploads nobody finished within a day, and videos no lesson took up within a week, are deleted every night (`learning-clean-uploads`).
- **Checking it**: `docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile app logs media-worker` shows each video made or refused; the lesson shows the same in the dashboard.

## Face ID terminals

A Hikvision face recognition terminal (MinMoe: DS-K1T341AMF, DS-K1T341, DS-K1T342, DS-K1T343, DS-K1T671, DS-K1T804…) at the staff door recognises people itself, against its own list (Employee No, name, face, finger, card), and posts each event with its snapshot to us. Faces and templates stay on the terminal. Each terminal has its own code in the address; anyone who knows the code can post events as that terminal, so treat the address like a password (a new code is one click in Attendance › Face ID, or the admin action "Give the selected terminals new codes").

**Add the terminal** in the dashboard (Attendance › Face ID › Add a terminal: name, branch, direction), or in the Django admin (Attendance › Face ID terminals › Add). The terminal's page shows the values below with its own code.

**On the terminal** (a browser on the pharmacy's network at the terminal's address, e.g. `http://192.168.1.250`, signed in as `admin`): Configuration › Network › Advanced Settings › HTTP Listening (on some firmware: Event › Alarm Server, or Platform Access):

| Field | Value |
|---|---|
| Destination IP or Host Name | `PUBLIC_DEVICE_HOST`, else the host of `DASHBOARD_URL` (e.g. `144.91.81.29.nip.io`, or `144.91.81.29` when the firmware takes only an address) |
| URL | `/api/v1/devices/hik/<code>/` |
| Port | `80` with protocol HTTP (DS-K1T341AMF firmware V3.2.x offers only HTTP); `443` with HTTPS where the firmware offers it |

Save, then press Test if the page has one (it answers 200). Then check:

- Each person on the terminal has the Employee No the dashboard shows for them (Attendance › Face ID › Not linked links the numbers it hasn't seen before; a number whose name on the terminal is exactly one person's full name links itself).
- The terminal's time is right (Configuration › System › Time Settings: NTP, or the right time zone, GMT+05:00 for Tashkent). A terminal whose clock is more than 10 minutes off is shown as such, and its scans get the time they arrived.
- To get a snapshot with each event, switch on uploading the captured picture in the terminal's access control or picture settings (the name differs by firmware).

**How it reaches Django**: Caddy proxies `/api/v1/devices/*` over HTTPS (`{$DOMAIN}`), over plain HTTP for the same name (`http://{$DOMAIN}`) and on the bare IP (`:80`, sent on as `{$DOMAIN}`); everything else on port 80 still redirects to HTTPS. Bodies are at most 8 MB. Django never redirects that path to HTTPS (`SECURE_REDIRECT_EXEMPT`), answers 200 to every request with a known code (even an event it ignores or can't read, so the terminal never retries it forever), 404 to an unknown one, and allows 1200 requests a minute per code. Port 80 must be open on the server's firewall.

## Performance

The defaults are sized for one server with 12 vCPU and 47 GB of memory serving a few hundred people at once, where a whole shift opens the mini app in the same minute from mobile networks (carrier-grade NAT puts hundreds of them behind one public address).

- **gunicorn** runs threaded workers: `GUNICORN_WORKERS` (default: the CPU count, at most 12) processes of `GUNICORN_THREADS` (4) threads. Also `GUNICORN_TIMEOUT` (60 s), `GUNICORN_KEEPALIVE` (75 s, longer than Caddy keeps an idle connection to it), `GUNICORN_MAX_REQUESTS` (5000, with jitter, so processes are replaced now and then) and `GUNICORN_ACCESS_LOG` (`-`, the container log). All go in `.env`.
- **Database connections.** Every gunicorn thread, Celery process and bot thread keeps one connection (`DB_CONN_MAX_AGE`, 60 s, with health checks). Production Postgres allows `POSTGRES_MAX_CONNECTIONS` (200): 48 for gunicorn, 12 for the Celery workers, 32 for the two bots, a few for the stream and beat, and room for a deploy, when the old and new backend overlap. Raise it together with workers or threads. psycopg's connection pool was measured too and was slower than persistent connections here, so it isn't used.
- **Postgres** also gets `POSTGRES_SHARED_BUFFERS` (2GB) and `POSTGRES_EFFECTIVE_CACHE_SIZE` (16GB), SSD costs and no JIT (docker-compose.prod.yml).
- **The bots** run each update's database calls on a pool of `BOT_DB_THREADS` (16) threads per bot, so many people are served at once; one person's updates are still handled in order (`apps/core/bot_runtime.py`).
- **Celery**: `CELERY_CONCURRENCY` (8 processes), `CELERY_PREFETCH` (1: a long export never holds reminders queued behind it), `CELERY_MAX_TASKS_PER_CHILD` (1000). Digests are sent at about 25 a second, under Telegram's limit of 30 a second per bot.
- **Rate limits** count per person once the server knows who it is (the Telegram signature or the session token checked out): mini app sign-in 60 a minute per Telegram user, the dashboard inside Telegram 60, dashboard refreshes 60 per session. Per address there is only a ceiling against floods, sized for a whole shift behind one mobile operator's address: 1200 sign-ins a minute, 300 desktop sign-in links. Override any of them with `THROTTLE_RATES`, e.g. `THROTTLE_RATES=telegram_auth_address=2000/min,login_link=600/min` (names in `backend/config/settings/base.py`). Behind Caddy alone the client address is the last `X-Forwarded-For` hop (`NUM_PROXIES=1`); put a CDN in front and raise it to 2 (and make Caddy trust the CDN).
- **The apps' files** are served by WhiteNoise, compressed. Fingerprinted assets are cached for a year (`immutable`); the mini app's page is checked again on every open, so a phone never asks for the assets of an older deploy.

## Load test

`scripts/loadtest/loadtest.py` plays N people opening the mini app at once (sign in with Telegram launch data → me, the day's numbers and their board → open a task and its comments → finish it → board and numbers again → a comment) and M managers in the dashboard (sign in inside Telegram → pulse, task list and numbers → reviews → overview, three rounds). It reports p50/p95/p99 per endpoint, throughput and failures; any 429, 5xx, timeout or connection error is a failure and makes it exit with 1. It needs only aiohttp, which the app already has.

The people come from a company of their own, made by `manage.py loadtest_people` (300 workers and 20 managers by default, Telegram ids from 990 000 000 001, which Telegram never gives anyone). Run it again before every run: it gives everyone fresh open tasks. Nothing is sent to them (no notifications are made when it writes the rows, and they are marked as having blocked both bots); `--delete` removes them afterwards and switches the company off.

Against the server, from any machine with Python and aiohttp (the token is read from the environment and never printed):

```bash
make prod-manage cmd="loadtest_people --people 300 --managers 20"
EMPLOYEE_BOT_TOKEN=<the employee bot's token> python3 scripts/loadtest/loadtest.py \
    --base-url https://<your domain> --users 300 --dashboard-users 20 --ramp 60 --json result.json
make prod-manage cmd="loadtest_people --delete"
```

`--ramp` is how many seconds the people take to arrive (60: a shift opening the app in the same minute; 10: a stress test), `--think` the pause between their steps, `--max-seconds` cuts the run off. Run it in a quiet hour: it is real load, and the few notifications it causes go to chats that don't exist, which Telegram refuses. Locally, against gunicorn without Caddy, `--distinct-ips` gives each person an address of their own.

`scripts/loadtest/bot_burst.py` sends the employee bot's real dispatcher one update from each of N people at once (Telegram replaced by a stand-in with a 40 ms round trip) and reports how long they took; use a development database, never production.

Measured on 2026-10-26 on a laptop (Intel i5-13420H, 12 threads, 15 GB, shared with the desktop; the load test ran on the same machine), production settings with `DJANGO_DEBUG=false`, package a's Postgres and Redis. Before is `main` at 3d6e45c as it ran then (3 sync gunicorn workers); after is this setup. 3400 requests per run.

| 300 app users + 20 dashboard users | Before | After |
|---|---|---|
| A shift arriving over 60 s, all behind one address | 270 of 300 sign-ins refused (429) | 0 failed; p50 63 ms, p95 210 ms, p99 406 ms; opening the app p50 0.12 s, p95 0.51 s |
| The same, each person on their own address | p50 1.8 s, p95 3.1 s, p99 3.3 s; opening the app p50 4.4 s, p95 8.8 s | (as above: the address no longer matters) |
| Everyone within 10 s (stress), each on their own address | 42.7 requests/s; p50 7.4 s, p95 14.6 s, p99 14.9 s; opening the app p50 13.7 s, p95 26.8 s | 116.9 requests/s; p50 1.6 s, p95 3.4 s, p99 4.1 s; opening the app p50 3.8 s, p95 8.7 s |
| Everyone within 10 s, all behind one address | 270 of 300 sign-ins refused | 101.9 requests/s, 0 failed; p50 2.4 s, p95 4.3 s, p99 5.3 s |

The employee bot, 300 people sending /tasks at the same moment: 14.9 s for all of them before (one thread for every database call; p50 10.5 s, p99 14.5 s), 11.0 s after (p50 6.8 s, p99 10.5 s). What is left is Python's own work in the one bot process.

## Updating

```bash
git pull
make prod-up
```

Migrations and company defaults run when the backend starts.

## Logs

`make prod-logs` follows every service. For one of them: `docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f backend`.

## Backups

- **Database and private files.** The `backup` service writes `backups/trello-<date>.sql.gz` and `backups/private-media-<date>.tgz` every night and keeps 14 days of each. `make prod-backup` dumps the database right away. Only root can read these files (they include contracts, ID scans and salaries), so use `sudo` to copy them. Copy the `backups` folder off the server regularly and store the copies encrypted.
- **Lesson videos.** They are big and can be uploaded again, so the nightly archive leaves the `trello911_learning_media` volume out; every Sunday the `backup` service copies it to `backups/learning-media-<date>.tar` and keeps the newest two. Restore one with the stack stopped:

  ```bash
  docker run --rm -v trello911_learning_media:/learning_media -v "$PWD/backups":/backups alpine \
    sh -c 'tar xf /backups/learning-media-<date>.tar -C /learning_media && chown -R 10001 /learning_media'
  ```

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
  sudo gunzip -c backups/trello-<date>.sql.gz | $P exec -T db psql -U trello trello
  make prod-up
  ```

- **Restoring the private files** (with the stack stopped):

  ```bash
  docker run --rm -v trello911_private_media:/private_media -v "$PWD/backups":/backups alpine \
    sh -c 'tar xzf /backups/private-media-<date>.tgz -C /private_media && chown -R 10001 /private_media'
  ```

  Restore the database and the private files from the same night, and keep the same `FIELD_ENCRYPTION_KEY` and `FIELD_HASH_KEY`.
