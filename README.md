# 911 Trello

A multi-tenant task and HR platform for companies, driven by Telegram: one Django backend with separate employee and owner bots. The full plan is in [docs/PLAN.md](docs/PLAN.md).

## Stack

Python 3.14 · Django 6.1 + DRF · PostgreSQL 18 · Redis 8 · Celery · aiogram 3 (scaffolded with [boundless-aiogram](https://pypi.org/project/boundless-aiogram/)) · uv · Docker Compose

## Layout

```
backend/        Django project: config/ (settings, urls, celery) and apps/
employee_bot/   Employee bot (boundless-aiogram structure); uses the backend's Django models directly
docs/           Plan
```

## Quick start

```bash
cp .env.example .env   # set EMPLOYEE_BOT_TOKEN and PLATFORM_ADMIN_TG_IDS
make install           # uv sync
make up                # Postgres :25432, Redis :26379
make migrate
make superuser
make run               # admin at http://127.0.0.1:28000/admin/, API docs at /api/docs/
make worker            # Celery worker, separate terminal
make bot               # employee bot, separate terminal
```

To run the whole stack in Docker (backend on :28000, worker, beat, bot), use `make stack`.

`make check` runs ruff, the Django system checks and pytest. It needs `make up` first.

The local ports (Postgres 25432, Redis 26379, Django 28000) avoid clashing with other projects' containers.
