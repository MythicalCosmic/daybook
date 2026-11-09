# Running Davomat

For the organization's administrator: signing in, locations, Face ID terminals, employees, users,
the Telegram bot and reports. Setting up the server is in [INSTALL.md](INSTALL.md).

**Users** sign in to Davomat (owner, administrators, managers, viewers). **Employees** are the
people the terminals recognise: they never sign in, they just walk past the terminal. One person
can be both.

## 1. Signing in

Open the organization's address (e.g. `https://davomat.example.uz/`) and sign in with your
username and password. **Remember me** keeps you signed in on that browser; leave it off on a
shared computer.

- Five wrong passwords for one username in a row lock it for 15 minutes on that computer.
- A forgotten password: an administrator sets a new one (section 6). Nobody can see an existing
  password, not even the server's administrator, who can set a new one from the server
  (TROUBLESHOOTING.md, "A lost password").
- Your own password: Settings › Your account.

## 2. The setup page (once)

A new installation opens the setup page: the organization's name, time zone and language, then
the administrator's account. The organization starts with one location, "Main": rename it and add
the others (next section). Name and logo: Settings › Organization.

## 3. Locations, departments and positions

Team › **Locations**: each office, shop or site with its own terminals and its own people. Rename
"Main" to the real name, add the others. Each employee belongs to one or more locations; each
terminal to one.

Team › **Departments** and **Positions** are lists you fill once and choose from on each
employee. Reports group by department and location.

## 4. Adding a Hikvision terminal

Face ID › **Add a terminal**, three steps:

1. **Terminal**: a name ("Main entrance", shown in the feed and in Telegram), its location, and
   how it counts scans:
   - *Entrance*: every scan checks in;
   - *Exit*: every scan checks out;
   - *One door*: in, then out (the usual choice for a single terminal).
2. **On the terminal**: the values to type into it (below). Copy them from this page: every
   terminal has its own secret code in the URL.
3. **First scan**: scan a face at the terminal. The page turns green the moment its first event
   arrives. ("Simulate a face" shows how a scan looks without a terminal; it doesn't count.)

### On the terminal's web page

1. On a computer **on the same network as the terminal**, open the terminal's address in a
   browser, e.g. `http://192.168.1.250` (the terminal shows it under Menu › Communication ›
   Network; or find it with Hikvision's SADP tool). Sign in as `admin`.
2. Go to **Configuration › Network › Advanced Settings › HTTP Listening** (some firmware calls it
   Event › Alarm Server, or Platform Access).
3. Fill in the first free slot exactly as Davomat's setup page shows, then **Save**:

   | Field | Value |
   |---|---|
   | Destination IP or Host Name | the server's address from the setup page (e.g. `203.0.113.10`) |
   | URL | `/api/v1/devices/hik/<code>/` (with both slashes) |
   | Port | `80` |
   | Protocol | `HTTP` |

   HTTPS (port 443) only where the terminal's HTTPS really works: the DS-K1T341AMF with firmware
   V3.2.x can't, so it uses HTTP on port 80. Davomat accepts both.
4. Press **Test** if the page has one: it answers OK.
5. If there is a **heartbeat** setting, switch it on, every 5 minutes: the terminal's status in
   Davomat stays fresh even when nobody walks past.
6. To get a photo with each scan, switch on uploading the captured picture (in the access
   control or event settings; the name differs by firmware).

### The terminal's clock

Configuration › System › System Settings › **Time Settings**:

- **Time zone**: `(GMT+05:00)` Tashkent (or the organization's zone);
- **NTP**: on, server `pool.ntp.org`, every 60 minutes; Save.

A terminal set by hand drifts by minutes a month. Davomat trusts a scan's time within 10 minutes;
a terminal further ahead gets its scans timed on arrival, and its card says the clock is off.

### The history the terminal sends first

The first time it connects, a terminal sends **everything it ever stored**, oldest first: often
tens of thousands of old scans, about one or two a second, which can take hours. Davomat skips
every scan older than a day or from before the terminal was added: none of them becomes an
arrival or a message. The terminal's card says "The terminal is sending its old history first"
with the count, and live scans start when it's done.

So connect a terminal **the day before** it counts for real (in the evening, say), and never
factory-reset a terminal: that deletes the enrolled faces.

### Employee numbers

Every person enrolled on the terminal has an **Employee No** (e.g. `00000002`). Davomat knows
people by that number (Team › the employee › **Face numbers**; `2` and `00000002` are the same
number). A number Davomat hasn't seen becomes a new employee by itself, named as on the terminal:
you only fix the name, position, department and location. Faces stay on the terminal: enrol new
people there as usual.

## 5. Employees

Team › **Employees**: photo, position, department, location, today's state (in, out, not in,
off, on leave), face numbers and whether their Telegram is linked. Search and filters at the top.

- **Add an employee**: name, phone, position, department, locations, schedule, face numbers and a
  photo.
- **Import** from Excel or CSV: columns first name, last name, phone, position, department,
  location, face number. The preview shows what will be created and every row with a problem
  before anything is saved.
- **Export**: the list as a spreadsheet.
- Someone who **left**: open them › Left (on a date). Their history stays in the reports; their
  scans no longer count. **Return** brings them back.

The employee's page shows this month's attendance as a calendar, their scans with the photos and
the Telegram link.

## 6. Users and roles

Settings › **Users and roles**: who signs in, and what they may do.

| Role | May |
|---|---|
| Owner | everything |
| Administrator | everything except changing the owner |
| Manager | attendance, employees and reports of **their locations** |
| Viewer | look only: attendance, employees and reports |

Add a user with a username, a password and a role (and locations for a manager). **Set a new
password** gives them a new one; **Deactivate** stops the sign-in at once (their history stays).
The list shows when each user last signed in.

## 7. The Telegram bot

Davomat sends its messages through the organization's own bot:

1. In Telegram, open **@BotFather**, send `/newbot`, give it a name ("Namuna Davomat") and a
   username ending in `bot` (`namuna_davomat_bot`). BotFather replies with a **token** like
   `7123456789:AAH…`.
2. Settings › **Telegram** › paste the token › Save. Davomat checks it with Telegram at once and
   shows the bot's name. The bot starts by itself within a minute.
3. **Link people**: on an employee's or a user's page, **Link Telegram** gives a one-time link and
   a QR code (valid 24 hours, used once). They open it on their phone and press **Start**.
   Settings › Telegram › **Send a test** messages you.

Who gets what:

- managers who see the location: arrivals with the photo, lateness, the daily summary, unknown
  faces (when switched on);
- employees: their own check-in and check-out (when switched on).

The bot's commands: `/today` (managers: who's in, late, not in yet, on leave), `/me` (employees:
today and this month), `/language`, `/help`. A new token (pasted the same way) replaces the old
one; the bot restarts with it by itself.

What the terminals send to Telegram is set in Face ID › Settings: nothing, each person's first
scan of the day, or every scan; unknown-face alerts; each employee's own message; how long
photos are kept (snapshots are deleted after that many days; 0 keeps none).

## 8. Attendance

Attendance holds the rules and the day-to-day:

- **Today**: who is in now, who is late and by how much, who isn't in yet.
- **Schedules** and **Roster**: when each person is expected (their shifts); lateness and early
  leaving are measured against them. **Swaps**: shifts people trade or leave open.
- **Corrections**: a forgotten check-out or a wrong scan, fixed by a manager and kept with who
  fixed it; overtime waiting for approval.
- **Timesheet**: the month, in Excel (including the T-13 form).

Approved leave counts as leave, not as absence. A scan within a few minutes of the person's last
one changes nothing (a repeat).

## 9. Reports

Attendance › **Reports**: pick the period (this month by default), a location and a department:

- per person: days scheduled, present, absent, on leave; hours worked; late count and minutes;
  early leaves; overtime; punctuality;
- per department and per location: the same, added up;
- the trend by day (present, late, absent) and the punctuality ranking.

Every table exports to Excel or PDF.

## 10. Privacy

Faces never leave the terminal: Davomat keeps each scan's time, the terminal's number and name,
and the snapshot, deleted after the days set in Face ID › Settings. Ask employees to agree to
Face ID attendance in writing.
