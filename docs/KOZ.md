# Ko‘z: the pharmacy's cameras start thinking

Ko‘z ("eye") turns the cameras a pharmacy already has into a sensor for Daybook. A small agent on a
PC at the pharmacy reads the camera streams, finds people with a local detector, and sends Daybook
only numbers, alerts and, on request, pictures and short clips. Daybook joins that with what only
it knows: who is on shift (attendance, Face ID) and what was sold (sales). Then it alerts the right
person and shows the owner things no camera system can show on its own:

> 18:00–19:00: 61 people came in and 34 bought. The queue reached 6 while only one pharmacist was
> at the counter: 27 left without buying.

This file is the contract between the three parts. The backend, the agent and the dashboard
follow it exactly; anything not written here is each part's own business.

## 1. Pieces

```
cameras ──RTSP──▶ NVR ──RTSP / ISAPI──▶ Ko‘z agent (Windows or Linux PC at the pharmacy)
                                          │ detector (YOLOX, ONNX, CPU), tracker, zones
                                          │ local status page http://127.0.0.1:8737
                                          │ rolling recorder of counter cameras
                                          └──HTTPS──▶ Daybook  /api/v1/devices/koz/…
                                                        │  apps/vision: stats, alerts, clips
                                                        ├──▶ employee and owner bots (alerts with a photo)
                                                        └──▶ dashboard  /c/<id>/vision…
```

- **Agent**: `edge/koz/` in this repo, its own Python project (Python 3.12–3.13, uv), command
  `koz-agent`. One agent per pharmacy (branch). It never sends video continuously.
- **Backend**: the Django app `apps/vision` (label `vision`).
- **Dashboard**: the module `dashboard/src/modules/vision`, sidebar entry **Ko‘z**.

## 2. Names

- Product name: **Ko‘z** in every language (U+2018 in o‘). Subtitle: uz "Kamera tahlili",
  ru "Аналитика камер", en "Camera insights".
- Company feature (module switch): `vision`, label "Ko‘z (camera insights)". No dependencies;
  receipts and conversion need the `sales` module and attendance numbers need attendance, and
  without them those values are `null`.
- Permissions:
  - `vision.view`: "See Ko‘z: visitors, queues, conversion and alerts with photos"
  - `vision.video`: "Watch the cameras live and open video receipts"
  - `vision.manage`: "Set up Ko‘z boxes, cameras, zones and alert rules"
- The agent is called a **Ko‘z box** in the UI (uz "Ko‘z qutisi", ru "Ko‘z-бокс"), even when it is
  software on an existing PC.

## 3. Wire rules (both APIs)

- JSON bodies, UTF-8. Times are ISO 8601 in UTC with `Z` (`2026-11-23T16:31:00Z`); the server turns
  them into the company's time zone for days and hours.
- Camera `key`: the agent's stable name for a camera, `^[a-z0-9:_-]{1,64}$`: `nvr:3` (NVR
  channel 3), `rtsp:<slug>`, `webcam:0`, `file:<slug>`, `sim:<slug>` (the generated scene).
- Coordinates in zones and boxes are **normalized** to 0..1 of the frame (x to the right, y down),
  so they survive a resolution change.
- Errors: `{"detail": "...", "code": "..."}` with 400/401/403/404/409/413/422.

## 4. Zones

A camera has up to 8 zones, stored as a JSON list on the camera:

```json
[
  {"id": "q1", "kind": "queue", "points": [[0.12, 0.55], [0.62, 0.55], [0.70, 0.98], [0.05, 0.98]]},
  {"id": "s1", "kind": "staff", "points": [[0.10, 0.20], [0.80, 0.20], [0.80, 0.45], [0.10, 0.45]]},
  {"id": "l1", "kind": "line",  "points": [[0.10, 0.60], [0.90, 0.62]], "in": "left"},
  {"id": "f1", "kind": "floor", "points": [[0, 0], [1, 0], [1, 1], [0, 1]]},
  {"id": "m1", "kind": "mask",  "points": [[0.85, 0.0], [1.0, 0.0], [1.0, 0.3], [0.85, 0.3]]}
]
```

- `id`: `^[a-z0-9_-]{1,16}$`, unique on the camera.
- `queue`: where customers stand waiting at the counter. Polygon, 3–24 points.
- `staff`: behind the counter, where pharmacists stand. Polygon.
- `line`: an entrance line, exactly 2 points A→B. `in` is `left` or `right`: the side of the
  directed line A→B (in image coordinates) that is inside the pharmacy. A person whose track
  crosses from outside to inside counts as `entered`, the other way as `exited`.
- `floor`: an area for counting people (occupancy).
- `mask`: blacked out in every picture the agent sends (snapshots, live frames, alert photos),
  and detections inside it are ignored. Clips cut from the NVR are not masked (documented in the UI).
- A person's position is the **foot point**: the bottom centre of their box (or the lowest
  visible part, such as at a counter). Zones are drawn where feet are.
- Validation (backend, PATCH): known kinds, point counts, every coordinate within 0..1, at most
  8 zones, unique ids. A camera may have several lines; their counts add up.

Roles of a camera: `counter`, `entrance`, `floor`, `storeroom`, `other`. A new camera starts as
`other` with `enabled: false`. The agent analyses only enabled cameras; it sends snapshots of
every camera so the owner can set them up.

## 5. Device API (agent ↔ Daybook), mounted at `/api/v1/devices/koz/`

Every call except `pair/` sends `Authorization: Bearer koz_<40 url-safe chars>`. Daybook stores only
the SHA-256 of the token. A wrong or revoked token gets 401 with `code: "revoked"`, and the agent
then backs off to one try every 10 minutes. Size limits: JPEG ≤ 1.5 MB, MP4 ≤ 40 MB,
≤ 2,000 stat rows per call.

### 5.1 `POST pair/` (no token)

The owner creates a box in the dashboard and gets a pairing code such as `KOZ-7F3K-92QD`
(8 Crockford base32 characters, shown once, valid 15 minutes, single use, stored hashed, one
active code per box; a new code replaces the old one).

```json
→ {"code": "KOZ-7F3K-92QD", "host": {"hostname": "KASSA-PC", "os": "Windows 11", "version": "0.1.0"}}
← 200 {"token": "koz_…", "agent": {"id": 4, "name": "Asosiy qutisi",
        "company": {"id": 1, "name": "Oydin Farm"}, "branch": {"id": 1, "name": "Asosiy"}},
        "server_time": "2026-11-23T16:31:05Z"}
← 400 {"code": "bad_code"}            (unknown, used or expired; 10 tries per IP per 10 minutes)
```

Pairing again (a new code) issues a new token and revokes the old one.

### 5.2 `GET config/`

```json
{
  "config_version": "9f2c1a",
  "agent": {"id": 4, "name": "Asosiy qutisi", "branch": {"id": 1, "name": "Asosiy"},
            "timezone": "Asia/Tashkent"},
  "rules": {"queue_people": 3, "queue_wait_s": 120, "unattended_s": 90, "clear_after_s": 15,
            "analysis_fps": 2, "live_fps": 2, "privacy_blur": false, "alert_photo": true,
            "record_counter": true, "record_hours": 24},
  "cameras": [{"id": 11, "key": "nvr:3", "name": "Kassa 1", "role": "counter", "enabled": true,
               "zones": [], "register_id": 2}],
  "snapshot_requested": ["nvr:3"]
}
```

`config_version` is a short hash of everything else, so the agent re-reads only when it changes.

### 5.3 `POST cameras/` (inventory)

```json
→ {"cameras": [{"key": "nvr:3", "name": "Kassa 1", "source": "nvr", "channel": 3,
                "w": 1920, "h": 1080, "online": true}]}
← {"cameras": [{"key": "nvr:3", "id": 11}]}
```

Upsert by `(agent, key)`. New cameras: role `other`, `enabled: false`, the agent's name. Later
calls update source, size and `online`, and the name only while the owner hasn't renamed it.
Cameras missing from the list are marked offline, never deleted. `source`: `nvr`, `rtsp`,
`webcam`, `file`, `sim`.

### 5.4 `POST cameras/<key>/snapshot/`

Multipart `image`: a full JPEG frame, masked, not annotated. 204. Sent at start, every 10 minutes
per camera, and soon after the key appears in `snapshot_requested` or `jobs.snapshots`.

### 5.5 `POST live/` (every 5 s)

```json
→ {"at": "2026-11-23T16:31:05Z",
   "agent": {"version": "0.1.0", "fps": 7.8, "cpu": 23},
   "cameras": [{"key": "nvr:3", "online": true, "fps": 2.0, "people": 3, "queue": 2,
                "staff": 1, "wait_s": 45, "error": null}]}
← {"config_version": "9f2c1a", "watch": ["nvr:3"], "jobs": 0, "server_time": "…"}
```

`people`: persons in the frame outside masks; `queue` / `staff`: persons in queue / staff zones;
`wait_s`: the longest current wait in a queue zone, whole seconds. Daybook keeps this in the cache
for 30 s and updates `last_seen_at` at most once a minute. `watch` lists the cameras someone is
watching live (5.6). `jobs > 0` tells the agent to call `jobs/` now.

### 5.6 `POST frames/<key>/` (only while watched)

Multipart `image` (JPEG ≤ 400 KB, ≤ 960 px wide, masked, **not** annotated: the dashboard draws
the boxes) and `meta` (a JSON string):

```json
{"at": "2026-11-23T16:31:05.400Z", "w": 960, "h": 540,
 "people": [{"track": 17, "box": [0.31, 0.22, 0.12, 0.55], "role": "customer", "zone": "q1",
             "wait_s": 45}]}
```

`box` is `[x, y, w, h]`, normalized. `role`: `staff` inside a staff zone, otherwise `customer`.
`zone`: the zone id the foot point is in, or null. `wait_s` only inside a queue zone. At most
`rules.live_fps` frames a second per camera. Daybook keeps only the latest frame per camera, in
the cache for 10 s, and never stores frames. 204.

### 5.7 `POST stats/` (every minute)

```json
→ {"minutes": [{"key": "nvr:3", "minute": "2026-11-23T16:31:00Z", "frames": 118,
                "people_avg": 2.4, "people_max": 5, "entered": 0, "exited": 0,
                "queue_avg": 1.6, "queue_max": 3, "wait_max_s": 75, "staff_seconds": 60}]}
← {"stored": 1, "skipped": []}
```

Upsert by `(camera, minute)`, so a retry is harmless. `staff_seconds` (0–60): seconds of that
minute with at least one person in a staff zone. Unknown keys and minutes older than 7 days are
returned in `skipped`. The agent sends each minute once it closes and keeps unsent minutes on disk
for up to 7 days.

### 5.8 `POST events/` (alerts)

Multipart `event` (a JSON string) and, on `start`, an optional `image`: an annotated JPEG (boxes,
zones, waiting times, heads blurred when `privacy_blur`, masks applied).

```json
{"event_id": "1b9e…", "incident_id": "77c2…", "kind": "queue", "phase": "start",
 "key": "nvr:3", "at": "2026-11-23T16:31:05Z", "started_at": "2026-11-23T16:31:05Z",
 "queue": 3, "wait_s": 130, "staff": 0, "peak_queue": 3, "peak_wait_s": 130}
← {"alert_id": 123, "state": "open"}
```

- `kind`: `queue` or `unattended`. `phase`: `start`, `update` (at most once a minute while open)
  or `end`. `event_id` (uuid4) is unique per call and makes it idempotent; `incident_id` (uuid4)
  ties the phases of one incident together.
- **queue**: at least `queue_people` people in the queue zones and the longest wait at least
  `queue_wait_s`, for 5 s in a row → `start`. It ends after `clear_after_s` with either below
  the threshold.
- **unattended**: at least one person in a queue zone and nobody in the staff zones for
  `unattended_s` → `start`. It ends after `clear_after_s` with someone in a staff zone or nobody
  waiting.
- Only `counter` cameras with the zones a rule needs raise alerts.
- An `end` or `update` for an unknown incident returns `{"alert_id": null}` and does nothing.

### 5.9 `GET jobs/`

```json
← {"clips": [{"id": 55, "key": "nvr:3", "start": "2026-11-23T16:30:50Z", "end": "2026-11-23T16:31:10Z"}],
   "snapshots": ["nvr:3"]}
```

Returned clips become `fetching`. If no video arrives within 5 minutes, the clip is offered
again, up to 3 times, then it fails with `agent_timeout`.

### 5.10 `POST clips/<id>/`

Multipart `video` (MP4, H.264, faststart, ≤ 60 s, ≤ 40 MB), `poster` (JPEG) and `meta`
`{"duration_s": 20.0, "source": "recorder" | "nvr", "w": 1280, "h": 720}` → 204. Or a JSON body
`{"failed": "not_recorded" | "camera_offline" | "nvr_error" | "too_old", "detail": "…"}` → 204.
The agent cuts a clip only after its `end` has passed. It uses its own recorder when it covers the
window, and otherwise the NVR's recording.

## 6. Owner API, mounted at `/api/v1/owner/companies/<company_id>/vision/`

Every endpoint needs the `vision` module on and at least `vision.view`, unless a stronger
permission is named. Members without `branches.all` see only their branches, as everywhere.
Lists are plain arrays unless they say `{count, results}` (`?page=N`).

### 6.1 `GET overview/?branch=<id>&day=YYYY-MM-DD`

`branch` omitted means every branch the caller sees; `day` defaults to today.

```json
{
  "day": "2026-11-23", "branch": {"id": 1, "name": "Asosiy"},
  "setup": {"agents": 1, "cameras": 4, "entrance": true, "counter": true},
  "agents": [{"id": 4, "name": "Asosiy qutisi", "branch_id": 1, "online": true,
              "last_seen_at": "…", "version": "0.1.0"}],
  "totals": {"visitors": 412, "receipts": 267, "conversion": 0.648, "conversion_note": null,
             "left": 145, "wait_avg_s": 38, "wait_max_s": 260, "alerts": 6,
             "unattended_minutes": 14,
             "compare": {"visitors": 380, "receipts": 251, "conversion": 0.661,
                         "label": "same_weekday_last_week"}},
  "hours": [{"hour": 9, "visitors": 31, "receipts": 22, "queue_max": 4, "wait_max_s": 140,
             "staff_avg": 1.4, "staff_checked_in": 2, "unattended_minutes": 0}],
  "insights": [{"kind": "lost_peak", "severity": "warn", "hour": 18,
                "text": "18:00–19:00: 61 kishi kirdi, 34 kishi xarid qildi. …"}],
  "open_alerts": [Alert]
}
```

- `visitors`: the sum of `entered` on `entrance` cameras; null without one.
- `receipts`: non-voided sales whose `sold_at` falls in the hour or day at that branch (returns
  are not receipts); null when the sales module is off.
- `conversion` = receipts / visitors when visitors > 0 and visitors ≥ receipts; otherwise null,
  with `conversion_note: "entrance_undercount"` when receipts exceed visitors.
- `left` = max(visitors − receipts, 0), or null.
- `staff_avg`: the average number of people in staff zones (from `staff_seconds` and
  `people` stats); `staff_checked_in`: the members checked in at that branch during the hour (from
  attendance), or null.
- `hours` has all 24 hours; the dashboard trims empty edges.
- `insights`: deterministic sentences built by the server in the caller's language. Kinds:
  `lost_peak` (the hour with the most people leaving without buying, when it is at least 10 and
  the wait was long), `long_wait`, `unattended` (minutes with customers and nobody at the
  counter), `staff_gap` (people checked in but nobody at the counter), `good_day` (conversion up
  on the comparison). Severity: `info`, `warn`, `bad`, `good`. At most 4, most important first.

### 6.2 `GET live/?branch=<id>`

```json
{"at": "…", "today": {"visitors": 47, "receipts": 31},
 "cameras": [{"id": 11, "name": "Kassa 1", "role": "counter", "branch_id": 1, "online": true,
              "stale": false, "people": 3, "queue": 2, "staff": 1, "wait_s": 45, "fps": 2.0}],
 "open_alerts": [Alert]}
```

`stale`: no live report for 30 s. Polled every 5 s by the dashboard.

### 6.3 `GET cameras/<id>/frame/` (`vision.video`)

200 `{"at", "w", "h", "people": […as 5.6], "image_b64": "<JPEG base64>"}`, or 204 when there is no
fresh frame yet. Every call marks the camera as watched for 15 s, which turns the agent's frames
on. Polled every 500 ms by the live view.

### 6.4 Cameras

- `GET cameras/?branch=` → `[Camera]`:
  `{id, key, name, role, enabled, branch: {id, name}, agent_id, source, channel, w, h, online,
   last_seen_at, zones, register: {id, name} | null, snapshot_url | null, snapshot_at}`
- `PATCH cameras/<id>/` (`vision.manage`): any of `name`, `role`, `enabled`, `zones`,
  `register_id`. Zones are validated as in §4.
- `POST cameras/<id>/snapshot/` (`vision.manage`) → 202; the agent sends a fresh one soon.
- `GET cameras/<id>/snapshot/` → the JPEG (`vision.video` or `vision.manage`).

### 6.5 Alerts

`Alert`: `{id, kind, state: "open" | "resolved", branch: {id, name}, camera: {id, name},
started_at, resolved_at, duration_s, peak_queue, peak_wait_s, acknowledged_by: {id, name} | null,
acknowledged_at, photo_url | null, clip: {id, state} | null}`. `kind` also has `agent_offline`.

- `GET alerts/?branch=&state=&kind=&from=&to=&page=` → `{count, results}`, newest first.
- `GET alerts/<id>/`.
- `POST alerts/<id>/clip/` (`vision.video`) → a Clip from 10 s before the start to the end (at
  most 60 s).

### 6.6 Clips (video receipts, `vision.video`)

`Clip`: `{id, state: "pending" | "fetching" | "ready" | "failed", reason: "sale" | "alert" |
"manual", camera: {id, name}, start, end, sale_id, alert_id, video_url, poster_url, duration_s,
failure, failure_text, created_at}`.

- `POST clips/` with `{"sale_id": 991}`: from 10 s before `sold_at` to 5 s after, on the camera
  whose `register_id` is the sale's register, else the branch's first enabled `counter` camera;
  409 `{"code": "no_camera"}` when there is none.
- `POST clips/` with `{"camera_id": 11, "at": "…", "before_s": 10, "after_s": 5}` (≤ 60 s).
- The same camera and window (±2 s) returns the existing clip.
- `GET clips/<id>/`, polled every 2 s until `ready` or `failed`.

### 6.7 `GET` / `PATCH settings/` (`vision.manage` to change)

`{queue_people (1–20, default 3), queue_wait_s (15–1800, 120), unattended_s (15–1800, 90),
clear_after_s (5–120, 15), cooldown_s (0–3600, 120), analysis_fps (1–5, 2), live_fps (1–4, 2),
privacy_blur (false), alert_photo (true), record_counter (true), record_hours (1–168, 24),
notify_on_shift (true), notify_managers (true), stats_keep_days (30–800, 400),
photos_keep_days (1–365, 30), clips_keep_days (1–365, 30)}`

### 6.8 Ko‘z boxes (`vision.manage`)

- `GET agents/` → `[{id, name, branch: {id, name}, online, last_seen_at, version,
  host: {hostname, os} | null, paired, cameras, created_at}]`
- `POST agents/` `{name, branch_id}` → `{agent, pairing: {code, expires_at, command}}`, where
  `command` is the line to run on the PC: `koz-agent pair https://<host> KOZ-7F3K-92QD`.
- `POST agents/<id>/pairing/` → a new `pairing`.
- `DELETE agents/<id>/`: revokes the token; the box's cameras stay, offline, with their history.

### 6.9 `GET review/?day=&branch=` (`vision.video`)

Moments worth a look: voided sales and cash taken out of a till in a minute when the till's camera
saw nobody at the counter (`queue_max == 0` on that camera and minute).
`{"items": [{"kind": "void" | "payout", "at", "amount", "sale_id" | null,
"cash_movement_id" | null, "cashier": {id, name} | null, "camera": {id, name} | null,
"queue_max": 0, "clip": {id, state} | null}]}`

## 7. Alerts in Telegram

- **Who**: when `notify_on_shift`, the members checked in at that branch right now (an open
  attendance record there), through the employee bot; when `notify_managers`, the members with
  `vision.view` who see that branch, through the bot they use for owner messages. Nobody twice.
- **Cooldown**: an alert still opens every time, but its kind on that camera is announced again
  only `cooldown_s` after the last announcement.
- **Messages** (uz shown; ru and en the same), a photo with the caption when `alert_photo` and a
  photo came:
  - queue: `🟠 Navbat · Kassa 1 (Asosiy)` / `3 mijoz kutmoqda, eng uzog‘i 2 daq 10 s.` /
    `Kassada: 1 farmatsevt` with the button `🙋 Men boraman`.
  - unattended: `🔴 Kassada hech kim yo‘q · Kassa 1 (Asosiy)` / `2 mijoz 1 daq 40 s dan beri
    kutmoqda.` with `🙋 Men boraman`.
  - The button acknowledges: every copy gets the line `🙋 Alimardon boryapti · 16:42`, and the
    button goes away.
  - On `end` every copy is edited to `✅ Navbat tugadi · 3 daq 40 s davom etdi · eng ko‘p 4 kishi`
    (or `✅ Kassaga farmatsevt keldi · …`).
  - agent offline (managers only, after 5 minutes without `live/`): `⚠️ Ko‘z qutisi aloqada emas ·
    Asosiy (5 daqiqadan beri)`, and `✅ Ko‘z qutisi yana aloqada` when it returns.
- Open alerts with no news for 2 hours are resolved by a scheduled job.

## 8. Privacy

- No face recognition of customers: the detector finds person shapes only; nobody is identified.
- Video stays at the pharmacy. What leaves it: live frames while someone watches (kept 10 s in the
  cache, never stored), alert photos (kept `photos_keep_days`), snapshots for setup, and clips
  someone asked for (kept `clips_keep_days`).
- Masks black out areas on everything sent; heads can be blurred on photos (`privacy_blur`).
- Camera and NVR passwords never leave the agent and are never logged.
- The audit log records pairing and revoking boxes, settings and zone changes, every clip request
  and the first live view of a camera per member per 10 minutes.

## 9. Demo data

`make demo` gives each demo pharmacy branch a paired box, four cameras (`Kirish` entrance,
`Kassa 1` counter mapped to a register, `Zal` floor, `Ombor` storeroom) with zones, 14 days of
minute stats during opening hours that agree with the demo sales (conversion 55–80 %, an evening
peak where the queue grows and people leave), 1–3 alerts a day, and generated illustration photos.
Demo photos are drawn scenes, never photos of real people. A demo company's live endpoint returns
moving numbers generated from the clock.

## 10. Agent command line

```
koz-agent pair https://daybook.example KOZ-7F3K-92QD   # once, stores the token locally
koz-agent nvr set 192.168.0.250                        # asks for the NVR user and password
koz-agent sources                                      # NVR channels, RTSP sources, scenes
koz-agent run                                          # the service; status page on :8737
koz-agent run --scene rush                             # the generated scene, no cameras needed
koz-agent selftest                                     # model, speed, server reachability
```

## 11. Not in the first build

Server-side person re-identification of any kind; heatmaps; after-hours motion alarms; a Windows
installer or service for the agent; AI-written summaries (every sentence is a template).
