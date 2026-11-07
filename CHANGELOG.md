# Changelog

## 0.5.0 — 2026-11-07

### New: stock and medicines (Money › Stock)
A module an owner switches on per company (Settings › Modules: **Stock**). Until then nothing changes.
- **The medicines catalogue**: name, trade name, active ingredient (INN), form and strength, parts per pack
  ("3 qadoq 1 blister"), Rx, e-prescription, controlled and cold-chain flags, MXIK and registration
  numbers, the mandatory-list and socially significant flags, the reference price; import from Excel/CSV
  with a dry run.
- **Every unit belongs to a batch** (series, expiry date, distributor, cost, retail price) and sales take
  the earliest-expiring batch first (FEFO); quarantined, recalled and expired batches are never sold.
- **Legal prices**: a prescription medicine's batch is never priced above its markup cap (20 %, 10 % for
  socially significant ones) or the reference price; pricing rules, rounding, and price tags to print.
- **Kirim (nakladnoy)**: goods received from a distributor, line by line with series and expiry (or from
  the distributor's Excel file), with warnings (short shelf life, cost jump, a recalled series, over the
  price cap, a branch not licensed for the item); posting opens the payable with the distributor's
  payment terms.
- **Transfers** between pharmacies (the same batches; a short arrival is disputed), **write-offs** with
  approval and the destruction act PDF (uz/ru, the commission, method, place), **blind counts** as tasks,
  **quarantine and recalls** (type one or import the regulator's list: every pharmacy holding the series
  gets a task to remove it).
- **Expiry board** (90 / 60 / 30 days and expired, with their value), a morning digest per step, and on
  the 1st an "Expiry shelf check" task for each pharmacy.
- **Compliance**: the mandatory assortment check, defektura (what customers asked for and you didn't
  have), the prescription log and its PDF, and the controlled-substance register at the pharmacies
  licensed for it (computed from stock movements, monthly close, a discrepancy alert with the reminder
  to report it within 3 days).
- Ask AI and your own agents read stock: find an item, analogs (same active ingredient, form and
  strength), what expires, receipts to post, stock levels, defektura.
- **The pharmacist's screens in the mini app** (Me › Stock, the Home cards, the (+) button): look a
  medicine up by name, active ingredient or barcode (the phone's camera reads barcodes where it can),
  see its batches here, at the other pharmacies and its analogs; the expiry check (mark a batch as on
  the near-expiry shelf, propose a write-off with a photo); incoming transfers ("Received"); the blind
  count; receiving goods from a distributor; defektura; prescription entries.

### New: sales lines from your cash-register software (Money › Sales)
- **Import** the receipts' lines your cash-register program exports (CSV/XLSX), with a saved column map
  per program: matched to the catalogue, taken from stock by FEFO, never counted as money twice (the
  tills stay the money truth), and checked against the tills day by day.
- **The legal price check**: a prescription medicine sold above its cap or the reference price is listed
  and the pharmacy's managers hear about it once a day.
- **24-hour pharmacies**: no "not opened" alerts and no closing time; a till open more than 26 hours alerts.
- **Customers and nasiya**: find a regular by phone at the till, sell on credit or take a payment; at the
  close the nasiya total must match the credit sales; receivables by age (0–30, 31–60, 60+) and morning
  reminders.
- **Invoices** for distributors and sales to clinics: product lines by batch with series and expiry, the
  wholesale price-cap warning, partial payments, void before payment, the PDF (MXIK, VAT, "not an
  electronic invoice") and sending it to the customer's Telegram or as a link.

### New: a qualified pharmacist whenever a pharmacy is open (People › HR › Coverage)
- Choose which positions are pharmacists and the diplomas and certificates they need; Coverage shows
  each pharmacy's week, gaps in red, "Fix in roster"; the roster shows the week's gaps too.
- The pharmacy's head and the owners hear at once when an open pharmacy has no qualified pharmacist
  checked in, or when someone unqualified opens a till; planned gaps two weeks ahead.
- A warning when a pharmacy is marked licensed for controlled substances without that licence on file;
  "Upload my renewed certificate" in the mini app. Runs once HR is on and pharmacist positions are chosen.

### New
- **A recurring bill can give its payer a task** (Finance › Recurring › More: "Also give them a task"):
  one task per bill, due on its day, closed by itself when the bill is paid or skipped.

## 0.4.4 — 2026-11-07

### Fixed
- **Someone who left now gets their final payslip**: publishing it sends the PDF to them in the employee
  bot, with the company, the month and the amount (the app and its notifications are for working
  members only, so it used to reach nobody).
- **An expense claim still waiting when its day's books were closed** can be approved: it is booked on
  the first open day, like depreciation, and keeps the day the money was spent (it could only be
  rejected).
- **The cash forecast** no longer drops the usual distributor payments because of a bank loan or a
  bill due later: only goods and services on credit hold them back.
- **/expense in the bot** shows every category, ten at a time with "More ›" and "‹ Back" (it showed the
  first 12, so categories an owner added never appeared).

## 0.4.3 — 2026-11-07

### New
- **Tell us about your business** (Settings › Company, and a Get started step): a pharmacy, a distributor
  or both, and who you sell to (walk-in customers, clinics, other pharmacies, companies). Modules take
  their defaults from it; it switches nothing on.
- **What each branch is** (Settings › Branches): a pharmacy, a warehouse or an office, and its pharmacy
  facts: open 24 hours, licensed for narcotics and psychotropics, a social pharmacy, in the
  e-prescription area. A 24-hour pharmacy is never "closed" or "day off" on the Overview; it shows
  "Open 24 hours" and is open once a till or a check-in opens it.
- Two new permissions for pharmacy stock: **Look up stock, count, receive goods…** (given to the
  Pharmacist and Cashier roles) and **Keep the controlled-substance register and the prescription log**.
  The stock module itself comes in the next release.

### Fixed (three independent money reviews)
- **Final payslip**: a bonus could be paid twice after a reopened month; a later month that paid a
  leaver in full went unflagged; a dollar salary took the month-end rate instead of the last day's; the
  payroll spreadsheet had no column for unused leave paid out; day counts of 10, 20, 30 printed as
  "1E+1"; the month's payroll figures (Overview, /today, Ask AI) left out people paid by a final
  payslip; the warning about pay for days after the last day now says how to take it back.
- **Fixed assets** (16 fixes): an expense could be capitalized twice; a moved asset's late month never
  reached the P&L; an asset already written down could be deleted; turning depreciation booking off
  still took the purchase out of the P&L; low-value items booked their cost twice; an asset's cost
  could drift from its purchase; a sale's money was dropped when nothing was booked yet; a sale could
  go to any account without Finance rights; an improvement could use another branch's expense; "Turn
  into an asset" showed salaries to people without payroll rights; units-of-output assets without a
  life never depreciated; the tax book kept depreciating sold assets; a capitalized pending expense
  could be rejected; a void could race the asset made from it; writing off lost equipment at offboarding
  could fail silently; declining balance nearly doubled after a pause or an improvement.
- **Money planning** (9 fixes): pressing Pay twice on a recurring bill (two people, a stale dialog or the
  bot's button) paid the next month too; paying the VAT or turnover tax bill paid payroll's withheld
  income tax first; merging a category used by a bill, budget or claim failed; a budget at 99.5 % read
  "over"; a claim paid from company cash someone holds was always booked in so‘m; the depreciation
  categories were offered for expense claims; voiding a claim's waiting entry left the claim stuck; a
  so‘m bill paid from the dollar safe was booked in dollars (now refused); a branch head could read
  another branch's recurring payment in History.
- The payslip table's money columns fit their amounts (a prorated amount ran into the next column).
- Licences ending within their warning days show an amber pill under "ending soon".
- In the demo, the person who left is hired on the day they joined, not the day they left, so the
  final payslip pays their October days.

## 0.4.2 — 2026-11-07

### New: the final payslip for someone who leaves (Payroll)
- The offboarding wizard has a **Final payslip** step (for people who manage payroll): a preview of the
  last pay (the days worked through the last working day, other pay, fines, advances deducted in full,
  the net or what the person would still owe) and two answers: "Prepare the final payslip" and "Unused
  leave days to pay out".
- When the person leaves, a **draft final run** is made for the leaving month and payroll managers hear
  about it in the owner bot. Unused leave is paid at the average day of the last months' regular pay
  (12 months and calendar days by default: Settings › Payroll › Leaving, to confirm with your accountant).
  It is finalized, published and paid like any run; its PDF says "Final payslip".
- The month's regular run skips the person (a draft moves their payslip over; an already finalized one
  leaves only the payout and what is still open). When the pay can't cover the advances, the rest stays
  as money the person owes in Finance.

## 0.4.1 — 2026-11-07

### New
- **Licences and permits** (Money › Assets › Licences): the pharmacy licence, the controlled-substances
  licence, the lease, fire safety and sanitary approvals, the cash register's registration, insurance,
  each with its branch, number, issuer, end date, the scan and who is responsible. The owner bot warns
  from its warning days ahead (60 by default), a week before and when one has expired.
- **Jihozlarim (My equipment)** in the mini app: what the company gave you, with "Qabul qildim" to confirm
  you have it, a card on Home while something waits, and the bot's "you were given…" message opens it.
- **Ask AI and your own agents read fixed assets**: how much depreciation this year, what needs a service
  or an instrument check, what to replace soon, which repairs approach a new one's price.
- `/today` in the owner bot says what the equipment needs: services and instrument checks due, warranties
  and insurance ending.

## 0.4.0 — 2026-11-07

### New: fixed assets and depreciation (Asosiy vositalar va amortizatsiya)
A module an owner switches on per company (Settings › Modules: **Assets and equipment**). Until then
nothing changes for anyone.
- **The register** (Money › Assets): every fridge, air conditioner, shelf, till, thermometer, the courier's
  scooter and the renovation of a rented pharmacy, with its inventory number (AV-0001), branch, who holds
  it, its cost, what it is worth today and last month's depreciation; the totals on top, an Excel export,
  search in the command palette.
- **Depreciation month by month** by the four methods of NSBU No. 5 (straight line, double declining
  balance, sum of the years' digits, units of output), from the 1st of the next month or from the day it
  is put into service (the company's policy). An improvement added to the cost, a write-down, a new
  useful life or residual value, and mothballing apply from the first month not posted yet; posted months
  never change.
- **Profit tells the truth**: an expense that bought equipment ("Turn into an asset") leaves the P&L, and
  its depreciation comes back month by month as a cost that moves no money (one Finance row per month
  and branch). Selling or writing an asset off books what it was still worth and the money of a sale, so
  the P&L shows the gain or the loss. Equipment bought before the app keeps its earlier months in the
  old books, or takes their sum.
- **Each asset's page**: its value over its whole life (posted and planned), the schedule by year, the
  **tax book** (straight line at the Tax Code's annual maximum rates, art. 306) and its difference from
  the books, upkeep with days left, who held it when (confirmed by them in the app), photos and documents,
  the timeline, and a **QR label** to stick on it.
- **Reports**: depreciation by category or branch for any year, and the movement of fixed assets
  (at the start, in, out, depreciation, write-downs, at the end).
- **Planning**: replacements due in the next three years by quarter, at today's prices grown by
  inflation; "repair or replace?" when repairs near a new one's price; money sitting idle in storage or
  mothballed; old assets still working for free; upkeep coming up; things given out that nobody confirmed.
- **Upkeep reminders** in the owner bot (a warranty ending, a service due, an instrument check due or
  overdue, insurance ending), **inventory counts** per branch (found, damaged, missing), and an
  **offboarding** step: what the leaver holds is handed back, written off as lost or left with them.
- Starter categories for a pharmacy with their useful lives, Tax Code groups and rates (to be confirmed
  by the company's accountant).

### New: your own AI agents
- **New agent** on AI › Agents: start from one of eight examples ("Kechki hisobot", Monday's best of the
  week, daily attendance at 10:00, the week's biggest expenses, documents running out…) or write in your
  own words what it should do; pick when it runs, who gets it and what it may read. It runs on Haiku with
  its owner's rights and branches, and sends one short message per person in their language (or to a
  group).
- Each has its own page like the built-in agents (its chibi in the colour you pick), Run now (10 a day),
  pause, edit and delete; at most 10 per company. Nothing is sent when AI is off or the budget is spent, and
  an agent whose owner left or lost access pauses itself and says why.

### New: money planning (Finance)
- **The tax regime** (turnover tax, VAT 12 %, simplified VAT 6 %) with the turnover-tax threshold tile,
  and a **tax calendar** per regime (due days to confirm with your accountant).
- **Recurring payments**: rent, utilities and the like as reminders or booked by themselves, moved off
  holidays, each due date once. **Upcoming payments** in one calendar.
- **Budgets** per category and month with alerts at 80 % and 100 % and "copy last month".
- **Payables**: pay several distributors' debts at once; credit notes on a debt.
- **Expense claims**: staff send a receipt with `/expense` or a `#xarajat` photo in the bot or from the
  mini app's (+); approved claims are paid back through payroll or in cash.
- **Cash forecast** for 30, 60 or 90 days with its low point and the first day below zero.
- Five pharmacy categories for every company with Finance (marketing bonuses, insurance fund
  reimbursements, licences and certificates, destruction services, instrument checks).

### New: storage readings and the temperature log
- A routine can ask for readings (fridge and room temperature, humidity) within an allowed range: staff
  type them in the bot or the mini app; a value out of range needs a note and alerts the people who check
  it at once, and a recheck within two hours closes the alert. "One of us does it" routines close their
  colleagues' copies.
- **Set up storage readings** for a branch in one go (fridges 2–8 °C, the room 15–25 °C, humidity ≤ 60 %,
  at 09:00 and 20:00 by default), each routine's journal with a chart of the allowed band, and the branch's
  **monthly temperature and humidity log as a PDF** for inspectors. `/today` in the owner bot lists what was
  out of range and what nobody took.

## 0.3.2 — 2026-11-03

### New: every AI agent gets its own page
- A tap on an agent (AI › Agentlar) opens its page instead of a side panel. At the top, its chibi sits at
  a desk in a little pixel room: it types while the agent works (its screen fills with what it did), watches
  the screen while it waits, and sleeps on the desk when the agent is off. The window shows day or night by
  the company's clock; a tap on the chibi makes it send hearts.
- Below: the last and next run, tokens and cost this month, then **Nima qildi** (its activity),
  **Ichki jurnal** (every run with its time, result, tokens and cost, and every Claude call), **Tokenlar**
  (30 days of input and output tokens and its share of the company's AI spend), **Keyingi ishlar** (its next
  runs and what it expects) and **Sozlamalar**. Costs and error texts are shown only to people who manage AI.
- Every scheduled run is now logged (the newest 200 per agent).

## 0.3.1 — 2026-11-03

### New: the employee side of HR and payroll (mini app)
- **Maoshim (My pay)**: this month's pay so far and the month's estimate with its parts, the bonus rules'
  progress ("2 ta kechikish qoldi — bonus saqlanadi"), payslips with every line, the PDF and "Oldim" once paid,
  bonuses and fines with their reasons (a fine can be disputed once, and the answer shows), and advances
  (asked for within the allowed amount, cancelled while undecided, repaid month by month).
- **Hujjatlarim (My documents)**: the contract with its PDF and "Tanishdim", documents with their end dates
  (a scan can be uploaded), one's own details (pay card and IDs shown masked) and up to three emergency
  contacts.
- **Intizom (My record)**: warnings and reprimands in a calm tone: read, acknowledge, explain once.
- The bot's notices about payslips, pay and records open the right screen.

### Changed
- The HR assistant shows, and comes on, where the company has HR or Payroll: its payroll check before pay
  day and its bonus suggestions are payroll's.
- The bot's /pay says "Hozircha qo‘lga tegadi", the app's word for the same number.

### Fixed
- Dates in another year show their year in the mini app.

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
- Payroll's money logic went through an independent review before release (ten fixes, each with a test).
  Not in this release: the final settlement for someone who leaves (last pay with unused leave paid out),
  which is still done by hand.
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
