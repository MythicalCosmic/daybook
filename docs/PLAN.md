# 911 Trello — Plan

## 1. What we're building

A multi-tenant task + HR platform for companies, driven by Telegram.

| Piece | Status |
|---|---|
| **Employee bot** (aiogram 3, scaffolded with `boundless-aiogram`) | **Now** |
| **Django backend** — single source of truth for both bots, both mini apps, the dashboard | **Now** |
| Employee mini app (frontend) | You build it, against our OpenAPI schema |
| Owner bot | Later |
| Owner dashboard + HR (salaries, debts, cashier, expenses, contracts, policies) | Later — data model leaves room for it |

Companies are added dynamically. Each company has its own members, roles, positions, tasks, reminder rules, groups.

## 2. Key decisions

| Topic | Decision | Why |
|---|---|---|
| Tenancy | One DB, shared schema, `company_id` on every tenant model, tenant-scoped querysets, isolation tests | One bot serves every company; simple migrations; easy platform super-admin |
| Bot ↔ backend | Bots use the backend's Django models and service layer directly (boundless-aiogram Django mode). Business logic lives in `apps/<app>/services.py`, shared by bot handlers, the mini app API and Celery | No duplicate internal API; one source of truth; real DB transactions |
| Bot ↔ bot | Telegram bots can't message each other. The backend is the bridge: it holds both tokens and sends through whichever bot the recipient uses | This is the "connection between the two bots" |
| Background jobs | Celery + Redis, Celery beat for scanners | Reminders, daily task generation, summaries |
| Mini app auth | Validate Telegram `initData` (HMAC with bot token) → short-lived JWT | Standard, no passwords |
| API contract | DRF + drf-spectacular (Swagger at `/api/docs`) | You build the frontend against a documented schema |
| Admin config (for now) | Django admin with Unfold theme, tenant-scoped for owners | Reminders/roles/templates configurable from day one; real dashboard later |
| Permissions | Fixed permission codenames in code; access roles are dynamic per-company bundles of them; enforced in DRF permissions + bot gate middleware | "Hard locked" |
| Tooling | uv, ruff, pytest, Docker Compose (Postgres, Redis) | |
| Time | Every company has a timezone (default `Asia/Tashkent`); all schedules computed in it | |

### Recommendation: split "Position" from "Access role"

Employees choose their role during onboarding. If that choice also grants permissions, anyone can pick "Manager" and get manager access. So:

- **Position** (Cashier, Cook, Driver…) — dynamic per company, employee picks it in the mini app. Used for task assignment, filters, reports.
- **Access role** (Employee, Team lead, Manager…) — dynamic per company, bundles permissions, **only owners assign it**. New members get the company's default role.

## 3. Core flows

### 3.1 Joining

1. Each company has an invite deep link `t.me/<employee_bot>?start=c_<code>` (+ QR). Without a code, the bot asks for the company code.
2. `/start` → backend creates `Membership(status=pending)` → bot: "Request sent, please wait."
3. Approvers get the user's info with **Approve / Reject** buttons. For now approvers = platform super-admins (you) + members with `members.approve`, notified through the employee bot. Later: through the owner bot.
4. Approved → bot sends an **Open app** WebApp button. Rejected → polite message, can retry after a configurable cooldown. Blocked → ignored.
5. A gate middleware drops every other update until the member is approved **and** onboarded.

### 3.2 Onboarding (mini app)

- Phone via Telegram contact sharing (verified, belongs to that account), first name, last name, position.
- `Membership.onboarded_at` is set → bot shows the main menu.

### 3.3 Tasks

One `Task` model with a `kind`:

- **Daily / recurring** — generated from a `TaskTemplate` (days of week, every N days, monthly; due time in company tz). Assigned to people or to a whole position; generates one task per person, so stats stay per person.
- **Assigned** — given by someone with `tasks.assign`.
- **Personal** — created by the employee for themselves; reminders optional.

Status: `todo → in_progress → done` (+ `cancelled`); "overdue" is derived from `due_at`. Per task: priority, checklist, comments, attachments, **proof required** (photo / text / location), optional **manager confirmation** of "done".

### 3.4 Reminder engine (the annoying part)

`ReminderPolicy` per company (company default + override per template/task), all editable in admin:

- pre-due nudge (e.g. 30 min before)
- overdue repeat interval (default **20 min**)
- max reminders / stop after X hours
- escalation: after N reminders notify the assigner/owners and the escalation group
- quiet hours + working days (no 3 a.m. pings)
- snooze: allowed or not, length, max count
- message templates per step with placeholders `{first_name} {task} {due} {overdue}`; tone escalates (step 1 polite → step 5 aggressive)
- delete previous reminder before sending the next (clean chat) or stack them (more annoying)

Every reminder has inline buttons: ✅ Done · ⏰ Snooze · 💬 Comment · 📷 Proof.

Implementation: indexed `Task.next_reminder_at`. A Celery beat job runs every minute, picks `next_reminder_at <= now`, sends, writes `ReminderLog`, schedules the next one. If Telegram returns 403 (user blocked the bot), mark `bot_blocked_at` and escalate to owners immediately.

### 3.5 Groups

1. An owner/manager generates a one-time link code (admin or bot), adds the bot to the group, sends `/connect <code>`.
2. Bot checks the code and that the sender has `groups.manage` → group is linked to the company.
3. Pick event types with an inline keyboard: daily tasks done, overdue/escalations, new members, morning plan, end-of-day summary. Optional filter by position.
4. Events fan out to subscribed groups **and** owners' private chats (through the owner bot once it exists).

Edge cases handled: bot removed from group (`my_chat_member`), group → supergroup migration (chat_id changes), Telegram limits (≈20 msg/min per group, ≈30 msg/s global) via a throttled outbox.

## 4. Extra features (proposed — keep, drop, or reorder)

- Morning digest ("your 6 tasks today") + end-of-day summary per employee and per company
- Kanban board in the mini app (the Trello part): columns per company/team, drag between statuses
- Checklists, comments, attachments, @mentions on tasks
- Manager confirmation of "done" + proof photo
- Snooze with limits
- Leave / day-off requests with approval — pauses that person's reminders and daily tasks
- Company holiday calendar — no daily tasks generated on holidays
- Attendance check-in/out with location from the mini app (feeds HR later)
- KPIs per employee: on-time %, overdue count, avg delay; weekly report to owners
- Bonus / fine rules tied to task performance (hooks into salaries in the HR phase)
- Streaks + leaderboard (optional gamification)
- Announcements from owners to everyone or a position, with a "I've read it" button + read tracking
- Offboarding: deactivate a member → access cut instantly, open tasks reassigned
- Blocked-bot detection → owners alerted
- Audit log of every approval and admin action
- Multi-language: uz (latin), ru, en
- Multiple companies per person: one Telegram user can belong to several companies and switch in the bot

## 5. Data model

| App | Models |
|---|---|
| `companies` | `Company` (name, slug, timezone, default_language, invite_code, is_active) |
| `accounts` | `User` (custom `AbstractUser` + telegram_id, telegram_username, language). Every Telegram user is a `User`, so mini app auth, audit actors and the owner dashboard share one model |
| `members` | `Position` (company, name, order, is_active); `AccessRole` (company, name, permissions[], is_owner, is_default); `Membership` (company, user, status pending/approved/rejected/blocked/left, first_name, last_name, phone, position, role, decided_by, decided_at, onboarded_at), unique (company, user); permission registry `Perm` in code |
| `tasks` | `TaskTemplate` (company, title, description, rrule, due_time, assignee memberships/positions, requires_proof, reminder_policy, is_active); `Task` (company, kind, template, created_by, assignee, title, description, priority, due_at, status, requires_proof, needs_confirmation, completed_at, proof, reminder_policy, next_reminder_at, reminders_sent, escalated_at, snoozed_until, snooze_count); `ChecklistItem`, `TaskComment`, `TaskAttachment`, `TaskActivity` |
| `reminders` | `ReminderPolicy` (fields from 3.4); `ReminderMessageTemplate` (policy, step, language, text); `ReminderLog` (task, step, chat_id, message_id, sent_at, error) |
| `groups` | `TelegramGroup` (company, chat_id, title, bot, linked_by, is_active); `GroupSubscription` (group, event_type, positions filter); `GroupLinkCode` (company, code, expires_at, created_by) |
| `notifications` | `Outbox` (bot employee/owner, chat_id, payload, status, attempts, send_after) — reliable, rate-limited delivery for both bots |
| `audit` | `AuditLog` (company, actor, action, target, diff, created_at) |

HR later extends `Membership` (or a 1-1 `EmployeeProfile`) — nothing here blocks it.

## 6. APIs

**Bots** don't go through HTTP. Handlers call backend services directly (e.g. `members.services.request_access`, `members.services.decide`, `tasks.services.complete`, `groups.services.connect`) via `sync_to_async`. The gate middleware caches membership state in Redis.

**Mini app (JWT)**

- `POST /api/v1/auth/telegram` — `initData` → JWT
- `GET|PATCH /api/v1/me`, `POST /api/v1/me/onboarding`
- `GET /api/v1/positions`
- `GET|POST /api/v1/tasks`, `GET|PATCH|DELETE /api/v1/tasks/{id}`, `POST …/complete`, `…/comments`, `…/attachments`, `…/checklist`
- `GET /api/v1/stats/me`
- Swagger UI: `/api/docs`

## 7. Repo layout

```
911_trello/
├── backend/                # Django project
│   ├── config/             # settings (base/dev/test/prod), urls, celery, asgi/wsgi
│   └── apps/
│       ├── core/           # health check, shared bits
│       ├── companies/
│       ├── accounts/
│       ├── members/
│       ├── tasks/
│       ├── reminders/
│       ├── groups/
│       ├── notifications/  # Outbox + Telegram senders for both bots
│       ├── audit/
│       └── api/            # v1/ for the mini app
├── employee_bot/           # `boundless new` (Django ORM mode); imports the backend's models
├── owner_bot/              # later
├── pyproject.toml          # one uv environment for backend and bots
├── Dockerfile              # one image; compose picks the command per service
├── docker-compose.yml      # db, redis + (profile "app") backend, worker, beat, employee_bot
├── Makefile
└── docs/PLAN.md
```

## 8. Milestones

| # | Milestone | Done when |
|---|---|---|
| M0 ✅ | Scaffolding (done 2026-10-19) | git, uv, Docker Compose (Postgres, Redis), Django settings split, ruff + pytest + CI, bot scaffolded with boundless-aiogram, whole stack starts with `make stack` |
| M1 ✅ | Tenancy + members (done 2026-10-19) | Company, User, Membership, Position, AccessRole, permission registry; super-admin creates companies + invite links in admin (Unfold); approve/reject/block services; isolation tests pass |
| M2 ✅ | Access flow (done 2026-10-19) | `/start` with deep link → pending → approver gets Approve/Reject → approved user unlocked; gate middleware blocks everything else; rejection cooldown per company; approvals from the admin notify people too |
| M3 ✅ | Mini app auth + onboarding (done 2026-10-19) | `initData` validation, JWT, `/me`, positions and onboarding endpoints, verified phone from Telegram contact sharing, Swagger published for you |
| M4 | Tasks core | personal + assigned + daily templates and generation; bot menus (today / assigned / daily / new task); complete with proof |
| M5 | Reminder engine | policies, repeat every N min, escalation, quiet hours, snooze, templates, logs, blocked-bot detection — all configurable in admin |
| M6 | Groups | `/connect` flow, subscriptions, event fan-out, morning/evening summaries, throttled outbox |
| M7 | Polish | KPIs/stats, i18n (uz/ru/en), audit log, chosen extras from §4, deploy |

## 9. Questions (answered with "go" on 2026-10-19, so the defaults in brackets stand)

1. Before the owner bot exists, approvals go through the employee bot to you + company approvers? [yes]
2. Position / access-role split OK? [yes]
3. Can one person belong to several companies? [yes]
4. Which bot gets added to groups — employee, owner, or both? [employee bot for now; owner bot too later]
5. Languages? [uz latin, ru, en]
6. Where will it run? [VPS + Docker; mini app needs an HTTPS domain — tunnel for dev]
