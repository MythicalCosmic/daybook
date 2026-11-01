# Changelog

## 0.2.0 — 2026-11-02

### New: AI that works for the team
- **Tasks by voice.** A manager or head sends the bot a voice message ("Alisher, ertaga soat 10 gacha
  muzlatgich haroratini tekshirib, rasmini yubor. Bekzod, bugun kechqurun kassani sanab qo‘y") and gets back a
  card with the tasks it understood: what, for whom, when, urgent, photo needed. One tap gives them out through
  the usual task flow. Works in the employee bot, the owner bot, the mini app's (+) sheet (a mic) and the
  dashboard's New task dialog ("Dictate"). Typed instructions work the same way ("Smart add").
- **Speech to text on our own server.** Voice is written down by a Whisper service that runs next to the app
  (no outside key). Uzbek goes to a model trained on Uzbek speech (Tashkent dialect included); Russian and
  English to Whisper large-v3. A hosted service (OpenAI, Groq) can be used instead from the settings.
- **Without a Claude key it still works**: a built-in reader finds the people, dates ("ertaga 10:00",
  "до пятницы"), urgency and photo requests. With `ANTHROPIC_API_KEY` set, Claude reads the instructions instead
  and also unlocks Ask AI and the photo checker.
- **AI agents** (dashboard › AI › Agents), each with a switch, its schedule and what it did:
  - *Voice tasks* — turns voice notes into tasks; with "auto-create" on, it gives them out at once (with Undo).
  - *Deadline watcher* — tells whoever gave late work, once per task, and never twice with the reminders.
  - *Morning plan* — on workdays, each head and manager gets their team's day.
  - *Photo checker* (opt-in, needs Claude) — reads a proof photo (a fridge thermometer, a shelf) and leaves a
    note for the reviewer.
- **Activity** shows live what the agents did; **Voice notes** keeps who said what, the recording, the transcript
  and the tasks it made; **Ask AI** answers questions about the company's own data (tasks, people, attendance,
  sales…) with links to the records, never more than the person asking may see; **Settings › AI** holds the
  owner's consent, the monthly budget and what the AI may read.

### Fixed and polished
- **Mini app**: hover colours no longer stick after a tap on phones; the offline notice no longer covers the
  title; My team, page headers and segmented controls are one consistent design; calendar days a finger wide;
  closing the till and payouts can't be sent twice; proof photos show whole; buttons follow Telegram's theme; a
  launch that fails says why; dates without a time show the right day in every time zone.
- **Dashboard (also inside Telegram)**: Telegram's Back closes the open sheet first; phone sheets keep their
  header buttons; lists turn the page again; money edits keep their description, receipts and tags, and cash
  totals add up; a new company can be created by someone with none yet; knowledge saves never overwrite a
  colleague; the Gantt chart scrolls with a finger instead of moving dates; no hover-only controls or zooming
  into fields on touch screens; exports download inside Telegram; one request per tap; searches wait for a
  pause in typing; Uzbek wording without glued case endings.
- **Bots**: titles and names with `<` or `&` no longer break messages (a proof photo caption was refused);
  texts longer than Telegram allows are cut neatly instead of lost; the bot's New task only takes a person
  from its own picker.

### Faster
- Mini app: the first screen loads about a fifth less code (entry 142 → 116 KB gzipped); screens load on demand.
- Fewer database queries per request: the dashboard's task board 50 → 22, the mini app's summary 14 → 11, a
  person's page in My team 29 → 22; the morning digest job no longer grows with the number of people.

### Under the hood
- Every API route is tested with another company's ids (nothing leaks), every owner write as someone with only
  dashboard access, every mini app write as a new employee; every message the tests send is checked against
  Telegram's rules; every scheduled job runs through a day with hostile text.
- Dead code removed; duplicated helpers merged (one error handler for both bots, shared date helpers, one
  company id helper in the dashboard, shared task form pieces in the mini app).
- The release number lives in pyproject.toml; `/health/` and the API schema report it, and the mini app shows
  it on Me.
