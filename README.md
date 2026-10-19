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

## Mini app API

Interactive docs are at `/api/docs/` and the raw OpenAPI schema is at `/api/schema/`. Put the mini app's origin in `CORS_ALLOWED_ORIGINS`.

1. **Log in.** `POST /api/v1/auth/telegram/` with `{"init_data": Telegram.WebApp.initData}` returns `{access, refresh}`. Send `Authorization: Bearer <access>` on every other call. When the token expires, log in again with fresh init data or use `POST /api/v1/auth/refresh/`.
2. **Pick the company.** `GET /api/v1/me/` returns the person and their memberships. Use an `approved` one, and if there are several, let the person choose.
3. **Register** while `is_onboarded` is false:
   1. If `me.phone` is empty, call `Telegram.WebApp.requestContact()`. Telegram sends the contact to the bot, which saves it as a verified number. Re-fetch `/me` until `phone` appears.
   2. `GET /api/v1/companies/{id}/positions/` lists the positions to choose from.
   3. `POST /api/v1/companies/{id}/onboarding/` with `{first_name, last_name, position_id}` finishes registration.

When a business rule is broken, the API returns `400 {"detail": "<message safe to show>"}`. Field validation errors come back as `{"field": ["..."]}`. A company the person doesn't belong to returns 404.

## Try the join flow

1. In `.env`, set `EMPLOYEE_BOT_TOKEN`, `EMPLOYEE_BOT_USERNAME` and your Telegram id in `PLATFORM_ADMIN_TG_IDS`.
2. Run `make run`, `make worker` and `make bot`, then send `/start` to the bot once yourself so it's allowed to message you.
3. Create a company in the admin and copy its invite link from the company page.
4. Open the link from another Telegram account. You get the request with Approve and Reject buttons, and the other account hears the decision.

`make check` runs ruff, the Django system checks and pytest. It needs `make up` first.

The local ports (Postgres 25432, Redis 26379, Django 28000) avoid clashing with other projects' containers.
