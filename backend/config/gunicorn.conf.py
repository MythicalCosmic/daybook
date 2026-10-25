"""gunicorn for the API, the mini app and the dashboard (docker-compose.yml `backend`).

    gunicorn -c config/gunicorn.conf.py config.wsgi

Threaded workers: Django's work is mostly waiting on Postgres and Redis, so each process serves
several requests at once, and a phone uploading a proof photo over a slow network holds one
thread rather than a whole process. The defaults suit the production server (12 vCPU, 47 GB,
shared with Postgres, Celery and the bots): 12 processes of 4 threads, 48 requests at once.
Every value can be changed in .env (GUNICORN_WORKERS, GUNICORN_THREADS, …); see docs/DEPLOY.md
"Performance". Each thread keeps its own database connection, so Postgres must allow
workers times threads plus the Celery workers, the bots and the stream (docker-compose.prod.yml).
"""

import os


def _int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")
worker_class = "gthread"
workers = _int("GUNICORN_WORKERS", min(os.cpu_count() or 1, 12))
threads = _int("GUNICORN_THREADS", 4)

# A request still running after this long is cut off (and its worker replaced).
timeout = _int("GUNICORN_TIMEOUT", 60)
# On a deploy or restart, requests in flight get this long to finish.
graceful_timeout = _int("GUNICORN_GRACEFUL_TIMEOUT", 30)
# Caddy keeps its connections to us open between requests (for up to 60 s, deploy/Caddyfile);
# we must not close them first, or a request Caddy sends on a just-closed connection fails.
keepalive = _int("GUNICORN_KEEPALIVE", 75)

# Each process is replaced after this many requests (± jitter, so they never all restart at
# once): memory growth stays bounded without anyone noticing.
max_requests = _int("GUNICORN_MAX_REQUESTS", 5000)
max_requests_jitter = _int("GUNICORN_MAX_REQUESTS_JITTER", 500)

# Connections waiting to be accepted while every thread is busy.
backlog = _int("GUNICORN_BACKLOG", 2048)

# The heartbeat file in memory: Docker's overlay filesystem can stall it under load.
worker_tmp_dir = "/dev/shm" if os.path.isdir("/dev/shm") else None

accesslog = os.environ.get("GUNICORN_ACCESS_LOG", "-") or None
errorlog = "-"
# No runtime control socket (gunicornc): nothing uses it, and two copies on one machine would
# fight over its path.
control_socket_disable = True
