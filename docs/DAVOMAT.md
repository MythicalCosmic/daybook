# Davomat: the standalone Face ID attendance app (edition of Daybook)

The owner's ask (2026-11-10, night): "Tomorrow I have to install it at a fully different place, not
the whole Daybook, only the Face ID, attendance and team parts. A separate app with normal username
and password, configuration, connected to Telegram bots, manageable, and much more; a better, more
comfortable, cleaner, more beautiful UI, faster, more features. Done by morning; we'll find a server
and deploy it."

**Davomat** ("attendance" in Uzbek) is that app: the same codebase, run as its own **edition**
(`EDITION=davomat`) on its own server with its own database, its own Telegram bot and its own login.
It reuses Daybook's proven parts (Face ID terminals, attendance, team) and hides everything else.
Any business, not only pharmacies: the copy says employees, locations, departments.

## 0. Decisions

| Question | Decision |
|---|---|
| Separate app or a rewrite | An edition of the same code: `EDITION=davomat` (default `daybook`). One install = one organization (one `Company`), many branches. |
| Login | Username and password (Django auth), no Telegram needed. Lockout after 5 wrong tries per username and IP for 15 minutes. Admins create users and set their passwords; users change their own. |
| Who is who | **Users** sign in to the web app: Owner (everything), Administrator, Manager (their branches), Viewer (read only). **Employees** are people who scan at terminals: they never sign in; an employee may also be a user. |
| Employees without Telegram | Admins add employees by hand or import a list (CSV/XLSX), and the terminals' unknown numbers become employees automatically (`auto_create_employees`, on): the admin only fixes names and positions. |
| Telegram | One bot per install, the organization's own (BotFather token pasted in Settings, stored encrypted, checked at once). Users and employees link their Telegram with a one-time link or QR. Messages: arrivals with the photo, lateness, the daily summary, unknown faces (optional), each employee's own in and out. Bot commands: `/today` (managers: who's in, late, absent), `/me` (employees: today and this month). |
| Attendance | Daybook's: schedules, shifts, roster, check-in/out from scans, lateness, early leave, overtime, corrections, leave, timesheet (Excel, T-13). No GPS or mini app in this edition (`require_location` off). |
| Face ID | Daybook's 0.5.2 (terminals, setup wizard, live feed with snapshots, people and links, history skipping, plain HTTP for old firmware). |
| Reports | Monthly per person, department and branch (days, hours, late count and minutes, early leaves, absences, overtime), punctuality ranking, trends; Excel and PDF. |
| UI | The Daybook dashboard's design system, run in edition mode: only Overview, Face ID, Attendance, Team, Reports and Settings; product name and logo from Settings; a first-run setup wizard; a password login page. Premium bar (see `feedback-premium-ui`): beat PayDay (payday.uz) visibly. |
| Install | `deploy/davomat/install.sh` on a fresh Ubuntu server: asks the domain (or uses `<ip>.nip.io`), creates secrets, starts the Docker Compose stack (caddy, db, redis, backend, worker, beat, bot, backup), and the browser opens the setup wizard. `update.sh`, `backup.sh`, `restore.sh`. |
| Not now | The mini app, money, tasks, HR records, learning, AI; enrolling faces from the app (needs an on-site bridge, next). |

## 1. Contract between the packages (backend D1 → frontend D2, bot/reports D4, deploy D3)

All under `/api/v1/owner/` (the dashboard's API, cookie session as today). JSON, times in UTC.

### 1.1 Edition and first run (D1)
- `GET edition/` (public) → `{edition: "davomat"|"daybook", product: "Davomat", organization: {name, logo_url}|null, needs_setup: bool, default_language: "uz", languages: ["uz","ru","en"], telegram: {configured: bool, bot_username: string|null}}`.
- `POST edition/setup/` (public, only while `needs_setup`; once) `{organization: string, timezone: "Asia/Tashkent", language: "uz", admin: {username, password, first_name, last_name}}` → the same session response as a login (cookie + access), the organization created with its defaults (one branch "Main" renamed later, roles, the `face_id` and `attendance` modules on, `require_location` off).
- `manage.py davomat_init --organization ... --admin-username ... --admin-password ... [--timezone] [--language]` does the same from the shell (installer, tests).

### 1.2 Password sign-in (D1)
- `POST auth/password/` `{username, password}` → session response (as `TelegramLoginView`/`DevLoginView` give: `services.session_response(user, request)`), 400 `{detail: "Wrong username or password."}` (same for unknown users), 429 after 5 failures per username+IP in 15 minutes. Works in both editions (Daybook users may set a password later).
- `POST auth/password/change/` `{current, new}` → 204 (new ≥ 8 characters, not too common: Django's validators).
- In the davomat edition the Telegram login endpoints answer 404.

### 1.3 Users (D1) — `companies/{c}/users/`
- List/create/retrieve/update/deactivate; `POST users/{id}/password/` `{password}` (admin sets one).
- Shape: `{id (membership id), username, first_name, last_name, role: {id, name, kind: "owner"|"admin"|"manager"|"viewer"}, branch_ids, is_active, last_login, telegram_linked}`. Perm `roles.manage` (Owner, Administrator). Managers see only their branches' people and data (branch scope, as Daybook).
- Roles made at setup: Owner (is_owner), Administrator (all dashboard perms except roles of the owner), Manager (attendance.view/manage, members.view/manage/approve, reports.view, dashboard.access; branch scoped), Viewer (attendance.view, members.view, reports.view, dashboard.access).

### 1.4 Employees (D1) — `companies/{c}/employees/`
- List (search, branch, department, position, status, linked/not linked), create, retrieve, update, `POST {id}/photo/` (image), `POST {id}/leave/` (left on a date), `POST {id}/return/`, `POST import/` (CSV/XLSX: first name, last name, phone, position, department, branch, face number; dry run with `?dry_run=1`), `GET export/`.
- Shape: `{id, first_name, last_name, full_name, photo_url, phone, position: {id,name}|null, department: {id,name}|null, branch_ids, face_numbers: ["00000002"], status: "active"|"left", hire_date, left_on, schedule: {id,name}|null, telegram_linked, is_user, today: {state: "in"|"out"|"not_in"|"off"|"leave", since}|null}`.
- Face numbers are the FaceLink numbers (edit them here); an employee is a `Membership` (approved, role Employee, a `User` with an unusable password and a generated username).
- `auto_create_employees`: a terminal scan with an unknown number creates the employee (name from the terminal, the number linked) and processes the scan as linked.

### 1.5 Telegram (D1 backend, D4 bot)
- `GET/PUT companies/{c}/telegram/` `{token (write only), configured, bot_username, bot_name, status: "ok"|"invalid"|"not_set", checked_at}`: PUT checks the token with `getMe` before saving (encrypted at rest).
- `POST companies/{c}/telegram/test/` → sends "Test message from Davomat" to the caller if linked (400 otherwise).
- `POST companies/{c}/employees/{id}/telegram-link/` and `POST companies/{c}/users/{id}/telegram-link/` → `{url: "https://t.me/<bot>?start=link_<code>", code, expires_at}` (24 h, one use); `DELETE` unlinks.
- In the davomat edition every notification goes through the one bot (`apps.notifications.telegram._token` returns the organization's token for both bot names; `inbox.delivery.bots_for` → `[OWNER]`), to whoever linked their Telegram.

### 1.6 Reports (D4) — `companies/{c}/attendance/reports/`
- `GET summary/?from&to&branch&department` → per person rows `{employee, days_scheduled, days_present, days_absent, days_leave, worked_minutes, late_count, late_minutes, early_leave_count, overtime_minutes, punctuality_percent}` + totals; `GET departments/`, `GET branches/` (the same, grouped); `GET trend/?from&to` (per day: present, late, absent); `GET punctuality/?from&to` (ranking). `?format=xlsx|pdf` exports (the exports registry).

## 2. Packages (tonight, in parallel worktrees from `main` 8ace5fc)

| Package | Branch | Letter | Owns |
|---|---|---|---|
| **D1** edition core (backend) | `v9/davomat-core` | k | `apps/davomat/**` (new app: edition, setup, password auth, users, employees, telegram token and link codes), the `EDITION` setting and gating, small edits in signin/members/faceid/attendance/notifications/inbox for the edition |
| **D2** edition UI (dashboard) | `v9/davomat-ui` | q | dashboard: edition mode in the shell and registry, login and setup pages, Overview board, Team (employees, departments, positions, branches), Settings (organization, users and roles, Telegram), branding; visual polish |
| **D3** deploy, installer, docs | `v9/davomat-deploy` | r | `deploy/davomat/**`, `docker-compose.davomat.yml`, the bot container, `docs/davomat/**` (install and admin guides, uz/ru/en), a local end-to-end smoke test of the stack |
| **D4** bot and reports | `v9/davomat-bot` | f | `davomat_bot/**` (new aiogram app: link, /today, /me, inbox actions, token from the database, restart on change), attendance reports (backend + the Reports page in `dashboard/src/modules/attendance`) |

Rules: `briefs/v9-common.md`. The contract above is fixed; a package that needs it changed says so
in its hand-off and the lead decides at integration.
