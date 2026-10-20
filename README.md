# 911 Trello

A multi-tenant task and HR platform for companies, driven by Telegram: one Django backend with separate employee and owner bots, and the employee mini app ("Daybook"). The full plan is in [docs/PLAN.md](docs/PLAN.md).

## Stack

Python 3.14 · Django 6.1 + DRF · PostgreSQL 18 · Redis 8 · Celery · aiogram 3 (scaffolded with [boundless-aiogram](https://pypi.org/project/boundless-aiogram/)) · React 19 + TypeScript + Vite · uv · Docker Compose

## Layout

```
backend/        Django project: config/ (settings, urls, celery) and apps/
employee_bot/   Employee bot (boundless-aiogram structure); uses the backend's Django models directly
miniapp/        Employee mini app: React + TypeScript, served by Django at /app/ in production
docs/           Plan
```

## Quick start

```bash
cp .env.example .env   # set EMPLOYEE_BOT_TOKEN and PLATFORM_ADMIN_TG_IDS
make install           # Python and mini app dependencies
make up                # Postgres :25432, Redis :26379
make migrate
make superuser
make run               # admin at http://127.0.0.1:28000/admin/, API docs at /api/docs/
make worker            # Celery worker, separate terminal
make beat              # Celery beat (daily tasks, reminders, group reports), separate terminal
make bot               # employee bot, separate terminal
make app               # mini app at http://127.0.0.1:28173/app/, separate terminal
```

`make demo` builds a Demo Shop company with people and tasks in every state, so the bot and the app have something to show.

To run the whole stack in Docker (backend and mini app on :28000, worker, beat, bot), use `make stack`.

## The mini app

The app runs inside Telegram, which signs the person in: there are no passwords. It follows the "Daybook" design: create account, waiting for approval, home, tasks, task detail, activity and profile, in Uzbek, Russian and English, with light and dark themes that follow Telegram.

- **Developing.** `make app` serves it with hot reload and proxies `/api` and `/media` to the backend on :28000, so it is one origin like in production. API types come from the backend schema: after changing the API, run `make api-types`.
- **Trying it in Telegram.** Telegram only opens HTTPS pages. Point a tunnel (for example `cloudflared tunnel --url http://127.0.0.1:28173`) at the dev server, set `EMPLOYEE_MINIAPP_URL=https://<tunnel>/app/` in `.env`, and restart the bot. The bot's buttons then open the app.
- **In production.** The Docker image builds the app and Django serves it at `/app/` next to the API. Set `EMPLOYEE_MINIAPP_URL` to `https://<your domain>/app/`.

### API

Interactive docs are at `/api/docs/` and the raw OpenAPI schema is at `/api/schema/`. If the app is ever served from another origin, add that origin to `CORS_ALLOWED_ORIGINS`.

1. **Log in.** `POST /api/v1/auth/telegram/` with `{"init_data": Telegram.WebApp.initData}` returns `{access, refresh}`. Send `Authorization: Bearer <access>` on every other call. When the token expires, log in again with fresh init data or use `POST /api/v1/auth/refresh/`.
2. **Pick the company.** `GET /api/v1/me/` returns the person and their memberships. Use an `approved` one, and if there are several, let the person choose.
3. **Create the account** while `is_onboarded` is false:
   1. If `me.phone` is empty, call `Telegram.WebApp.requestContact()`. Telegram sends the contact to the bot, which saves it as a verified number. Re-fetch `/me` until `phone` appears.
   2. `GET /api/v1/companies/{id}/positions/` lists the positions to choose from.
   3. `POST /api/v1/companies/{id}/onboarding/` with `{first_name, last_name, position_id}` sends a pending request to the approvers, or finishes registration for someone already approved.
4. **Work.** `summary/` has the home screen numbers, `tasks/?scope=board` the person's tasks, `activity/` their feed. Every task lists the `actions` the caller may take.

When a business rule is broken, the API returns `400 {"detail": "<message safe to show>"}`. Field validation errors come back as `{"field": ["..."]}`. A company the person doesn't belong to returns 404.

## Try the join flow

1. In `.env`, set `EMPLOYEE_BOT_TOKEN`, `EMPLOYEE_BOT_USERNAME`, `EMPLOYEE_MINIAPP_URL` and your Telegram id in `PLATFORM_ADMIN_TG_IDS`.
2. Run `make run`, `make worker`, `make bot` and `make app`, then send `/start` to the bot once yourself so it's allowed to message you.
3. Create a company in the admin and copy its invite link from the company page.
4. Open the link from another Telegram account and create the account in the app. You get the request with the person's details and Approve and Reject buttons, and the other account hears the decision.

## Group chats

1. Add the bot to a Telegram group. If you can manage groups (owners and managers can, by default), the group is linked to your company straight away. Otherwise a manager sends `/connect` in the group.
2. The bot posts the group's settings. Tap what the group should get: finished daily tasks (with the proof photo), finished assigned tasks, late tasks, new people, the morning plan and the end-of-day summary. "Whose news" narrows it to some positions, for example a group for the kitchen. `/settings` brings the buttons back and `/disconnect` stops the posts.
3. A late task is posted once, when the reminders reach the manager. The morning and evening reports go out at the company's report times, set on the company page in the admin; a day with nothing to report gets no post.

The bot keeps the link when a group becomes a supergroup, and switches the group off when it's removed. Posts to one group are spaced 3 seconds apart, under Telegram's limit of about 20 a minute.

## Announcements

Managers send `/announce` to the bot, write the message (formatting is kept), pick everyone or some positions, and send it. Each person gets it with an "I've read it" button, and the author can tap "Who has read it?" any time. Anyone who hasn't read it after 3 hours gets one reminder, and a day later the author hears who still hasn't. Announcements and their read receipts are listed in the admin.

## Morning digest

At the company's morning report time, everyone working that day gets their open tasks from the bot, overdue ones first, one tap from each task's card. Nobody gets one on a holiday or a day off, or with nothing open. It can be switched off on the company page in the admin.

## Time off

People ask for days off in the app (Profile → Time off). Everyone who can approve time off (owners and managers, by default) gets the request in the bot with Approve and Reject buttons, and the person hears the answer. Owners and managers who ask just take the days. Company holidays are set on the company page in the admin.

On a holiday nobody gets daily tasks; on approved days off that person doesn't. Reminders wait until the days off are over, and approving time off that starts today takes today's daily tasks off the list. Assigned tasks stay for the manager to move.

## Team results

People who may see reports (owners and managers, by default) find **Team results** in the app's profile: each person's on-time rate, late and unfinished work for this week, last week or this month, and who is late right now. Personal tasks don't count. On Monday mornings, at the company's morning report time, the bot also sends them last week's numbers.

## Translations

The bots, their notifications and the API's messages come in Uzbek, Russian and English. Each person gets their own language (taken from Telegram at first, then whatever they pick in the app), and groups get the company's default language. The mini app has its own texts in `miniapp/src/i18n/`.

After adding or changing a text in the Python code, run `make messages`, fill in the new entries in `backend/locale/uz/LC_MESSAGES/django.po` and `backend/locale/ru/LC_MESSAGES/django.po`, and run `make messages` again to compile them. The tests fail while a text is missing or untranslated.

`make check` runs ruff, the Django system checks, the type check and all tests. It needs `make up` first.

Set `TELEGRAM_DRY_RUN=true` to log bot messages instead of sending them, for example when running locally without a real bot token.

The local ports (Postgres 25432, Redis 26379, Django 28000, mini app 28173) avoid clashing with other projects' containers.
