# Changelog

## 0.3.0 — 2026-11-02

### New: HR and payroll
Two modules an owner switches on per company (Settings › Modules: **HR** and **Payroll**). Until then nothing
changes for anyone.
- **HR** (dashboard › HR): an overview of what needs doing (headcount and its trend, documents to renew,
  contracts ending, probations ending, birthdays this week, each with a one-tap action); every person's HR
  card (passport, PINFL and payout card stored encrypted and shown masked, opened only with the
  "sensitive" permission and audited; emergency contacts; hire date); **documents** with expiry dates, a
  check of who lacks what by position (medical book, diploma, certificates…) and private scans;
  **contracts** made from templates with placeholders (`{{employee_full_name}}`, salary, dates…) or from an
  uploaded scan, with renewals, probation, termination, a PDF and the employee's "I have read it";
  **celebrations** (birthdays and work anniversaries) posted to the team group. HR watches expiry dates and
  tells the people who manage HR ahead of time (30 days for documents and contracts, 7 for probation),
  a week before and on the day, once each.
- **Discipline** (dashboard › HR › Discipline): warnings and reprimands in pharmacy categories (storage,
  dispensing errors, prescriptions, expired sales, stock shortages…), with evidence, the employee's
  acknowledgement and explanation, a suggested next step from the last six months, and "also propose a
  fine" that goes to payroll as a proposal. Suspensions with an end date or until further notice, and
  reinstatement.
- **Payroll** (dashboard › Money › Payroll): pay setups per person (monthly, daily, hourly; changes are
  dated, months already paid are locked); a month's run worked out from attendance, leave, holidays,
  overtime and night hours, task rates, bonuses and fines, advances and the deductions cap, with every
  line explained; finalize, reopen, publish payslips (bot message with a PDF), mark paid from finance
  accounts, xlsx export. **Bonuses and fines** are proposed and approved (one or many), employees can
  dispute a fine; **rules** propose them automatically (on-time %, lateness, sales…) with a preview of
  who would get what; **advances** are requested, decided, paid and repaid over months. Finance gets the
  salary, advance and tax rows by itself. Shipped rules start switched off; taxes are off by default.
- **The HR assistant** — a fifth AI agent with its own chibi (green, in a tie, with a clipboard): the HR
  morning digest for the people who manage HR, payroll readiness before pay day, and (opt-in) monthly
  bonus suggestions that a person approves. Runs on Haiku.
- Coming next: the employee side in the mini app (my pay and payslips, my documents and contract, my record).

### Also since 0.2.0
- **Voice notes in seconds**: speech goes to OpenAI's gpt-4o-transcribe (Uzbek included), with our own
  Whisper server as the fallback.
- **Claude's little helper** on AI › Agents and a chibi for every agent: they react to what happens
  (voice notes, late and finished tasks), walk with you to every page (switch "Har sahifada"), with many
  faces and little dances. Dashboard only.
- A one-time survey in the bot let everyone pick their branch, department and job title again.

### Fixed
- **"Are you sure?" dialogs ran nothing** for actions passed through them: archiving an account, writing
  off or cancelling a debt, rejecting or voiding a transaction, locking a period, deleting a category and
  the attendance record actions now work again.
- A person's page keeps its own Suspend button for companies without HR.
- Contract and payslip PDFs show inside the dashboard's preview (they were blocked from framing).

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
  from its own picker (a forged pick showed a name from another company); voice cards, the deadline
  watcher and the morning plan write dates in the reader's language; a tap on an old message says so
  instead of "Something went wrong"; the owner bot answers /help and anything typed; "More time"
  answers and finished cards no longer repeat the whole card or squeeze three buttons in a row; My team
  shows deadlines as the cards do; Russian says "просрочено" for late work.
- **Times everywhere in 24 hours**: one date and time picker in the app's own language replaces the
  phone's (which showed "05:00 AM" and "11/04/2026" on English phones).
- **AI safety, from an independent review**: a forged button can't open someone else's voice note; the
  morning plan never names a colleague's personal tasks; a Cancel during reading is final; "+1 hour" only
  for tasks the person may change; the activity feed keeps to the reader's branches; Ask AI re-checks the
  budget before every call and never sends phone numbers or usernames; one broken agent setting can't stop
  the others; two close names ("Dilshod"/"Dilshoda") are asked about, not guessed. The speech service
  refuses audio over 5 minutes and the web server refuses uploads over 100 MB.

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
