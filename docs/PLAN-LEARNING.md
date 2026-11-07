# 911 Trello: learning, quizzes, the tutor and recognition (PLAN-LEARNING)

The owner's ask (2026-11-07): "the main thing is the knowledge base and its video lessons and all
that kind of stuff… its agent gives random types of quizzes, ranks them, talks with the owner,
suggests who is lacking and who is not… mandatory stuff asking, knowledge base watching who
watched what… and make the app a bit more fun to use."

This plan turns the knowledge base (pages, PLAN-OWNER §13.5, live since Wave 1) into a training
system for pharmacy staff, with a tutor agent on top and recognition (points, levels, badges,
streaks, kudos, leaderboards) across the app. It follows PLAN-OWNER's rules (§2.3 rules every
engineer follows, §2.5 registries, §2.6 branch scope, §14.0–14.2 the pharmacy focus and words).
Where the two disagree on learning or recognition, this plan wins.

## 0. Decisions at a glance

| Question | Decision |
|---|---|
| Where it lives | New app `apps.learning` (module switch `learning`, "Training and quizzes", off by default). The knowledge base stays always on; topics and page views live in `apps.knowledge`. Recognition is `apps.recognition` (module `recognition`, exists as a switch). |
| What a lesson is | A video (uploaded, or a YouTube link) with notes. Text belongs in knowledge base pages; a course mixes lessons, pages and quizzes. |
| Video | Chunked upload (≤ 2 GB, ≤ 3 h), made into a 720p H.264 MP4 with a poster by a media worker (ffmpeg, one at a time), served through signed links; in production Caddy serves the bytes with Range requests after Django checks the link (`X-Accel-Redirect`). Own volume `learning_media`, left out of the daily backup. Per-company limit 10 GB (setting). |
| Who watched what | Every second actually played, merged into ranges per person and lesson; skipping ahead never counts; speed above 2× counts as 2×. A lesson is watched at 90 % (setting). Pages: visits, reading time, how far down, the version seen. |
| Mandatory | A mandatory course is assigned to everyone in its audience (positions, branches, or everyone), new people included, with a deadline (`due_days`) and an optional renewal (`renew_months`). Reminders before the deadline, notices when late, the manager after N days late. |
| Quizzes | Seven kinds of question (one answer, several, true/false, order, match pairs, type the answer, a number), fixed or drawn at random from topics, options shuffled, time limits, pass mark, attempts and a cool-down, partial credit, answers shown after / once passed / never. Graded on the server only. |
| "Random types" | Random quizzes draw a balanced mix per attempt; the question of the day picks a kind and topic per person; regular checks send a fresh random draw to each person. |
| "Mandatory stuff asking" | Regular checks: a quiz sent to an audience every week or month with a deadline, reminders, results to managers. Plus mandatory courses. |
| "Ranks them" | Points and levels for everyone, weekly / monthly / all-time leaderboards (company or branch), a quiz's results table, and topic mastery per person. |
| The agent | The tutor ("Ustoz" / "Наставник"), an AI agent (`apps/ai/agents/tutor.py`): the weekly training report to managers with who is ahead and who is lacking and why, suggestions with one-tap actions (assign a course, a missing lesson, a mentor, a thank-you), personal nudges after a weak result, questions written from a page or a lesson, and a chat for the owner ("Ask the tutor"). Works without Claude by rules and templates; Claude (Haiku, low effort) words the report, writes questions and answers the chat. |
| Without AI | Courses, lessons, quizzes, the question of the day, checks, the skill matrix and the reminders are learning features and work with the AI module off. The tutor's report, suggestions, nudges, AI questions and chat need the AI module (agents run only there). |
| Fun | Recognition: points, ten levels, a badge catalogue, learning streaks (days off and leave never break them), kudos, leaderboards; confetti and a success buzz in the mini app when something is achieved (quiz passed, course finished, level up, badge, a task done on time); no emoji in bot messages (PLAN-OWNER n2 rule). |
| AI money | Haiku 5.5 by default (`AI_MODEL_FAST`), effort low; the company's AI budget applies; one structured call per report, per drafting job, per chat turn. |

## 1. Scope

**Must** (ships in the first release, switched off until an owner turns `learning` on):

- Topics; page views and "who read what" (all of it, also without the module).
- Lessons with uploaded videos (processing, poster, signed streaming) and YouTube links; notes;
  who watched what.
- Courses with lesson, page and quiz steps; optional and mandatory; audience; deadlines; renewal;
  certificates (PDF); assignments by audience, by a manager, by the tutor, on one's own.
- Reminders, late notices, escalation to the manager.
- Question bank (seven kinds, pictures, topics, difficulty), quizzes (fixed or random), attempts,
  grading, results, a quiz's statistics (hardest questions).
- The question of the day (bot and mini app) and regular checks.
- Mastery per person and topic; the skill matrix.
- The tutor agent: weekly report, suggestions, nudges, chat, question drafting (Claude and rules).
- Recognition: points, levels, badges, streaks, kudos, leaderboards, task points.
- Dashboard modules `learning`, `quizzes`, `recognition`; mini app features `learning` and
  `recognition` (with the celebrations); employee bot: the question of the day, kudos.
- AI tools for Ask AI; demo story on Demo Dorixona; uz/ru everywhere.

**Should** (when time allows, in this order): transcripts of uploaded videos through the speech
service (feeds search and drafting); "my team's training" for department heads in the mini app;
a learning widget on the dashboard's Today; kudos posts to groups; copying courses between
companies (`register_copy_part`); a printable result sheet of a check round.

**Not now:** SCORM, live classes, external learners, paid courses, comments on lessons.

## 2. Words

| en | uz | ru |
|---|---|---|
| Training (the module) | O‘qitish | Обучение |
| Course | Kurs | Курс |
| Lesson | Dars | Урок |
| Video lesson | Video dars | Видеоурок |
| Step | Qadam | Шаг |
| Mandatory | Majburiy | Обязательный |
| Deadline | Muddat | Срок |
| Assigned to | Biriktirilgan | Назначено |
| Certificate | Sertifikat | Сертификат |
| Topic | Mavzu | Тема |
| Quiz / test | Test | Тест |
| Question bank | Savollar bazasi | Банк вопросов |
| Question of the day | Kun savoli | Вопрос дня |
| Regular check | Muntazam tekshiruv | Регулярная проверка |
| Attempt | Urinish | Попытка |
| Pass mark | O‘tish bali | Проходной балл |
| Skill matrix | Ko‘nikmalar xaritasi | Матрица навыков |
| Weak / strong | Sust / kuchli | Слабо / сильно |
| Tutor (the agent) | Ustoz | Наставник |
| Suggestion | Taklif | Предложение |
| Points | Ball | Баллы |
| Level | Daraja | Уровень |
| Badge | Nishon | Значок |
| Streak | Ketma-ket kunlar | Серия дней |
| Leaderboard | Reyting | Рейтинг |
| Kudos (thanks) | Rahmat | Благодарность |
| Who watched | Kim ko‘rdi | Кто смотрел |

Uzbek in Latin script with ‘ for o‘/g‘ and ’ for the tutuq belgisi; no case ending glued to a
placeholder; bot texts plain, short, without emoji (`apps/notifications/tests/test_emoji.py`).

## 2.5 Topics are shared

`knowledge.Topic` (name, palette colour, description, order, archived) tags knowledge pages
(`Page.topics`), lessons (`Lesson.topics`) and questions (`Question.topic`, one each). Managers of
either the knowledge base or learning keep them (`apps/knowledge/topics.py`, owner endpoint
`knowledge/topics/` with archive, restore, reorder and `pharmacy/`, which adds the usual pharmacy
topics in the company's language). Colours are palette keys (`topics.COLORS`).

## 3. Models

The models are written (lead step, `apps/learning/models.py`, `apps/recognition/models.py`,
`apps/knowledge/models.py` `Topic` and `PageView`) with migrations `knowledge/0002`,
`learning/0001`, `recognition/0001`, `companies/0010` (the `learning` switch) and `members/0017`
(the permissions). Read their docstrings; this section adds what the code can't say.

- A package may add fields to the models it owns (§15) with a migration of its own app, named
  `00NN_<pkg>_<what>.py`; say so in the hand-off (the lead orders migrations at integration).
- JSON shapes:
  - `Question.data` per kind (§4.3). The right answer never leaves the server in an employee
    response before the attempt (or the day's question) is answered.
  - `Attempt.items`: `[{"question": 12, "kind": "single", "points": 1, "order": ["c", "a", "b"]}]`
    (`order`: option ids as shown; for `match` the right-hand ids as shown; empty for text and
    number). `Attempt.answers`: `{"12": <answer>}` (§4.3 shapes).
  - `LessonProgress.ranges`: `[[0, 75], [90, 240]]`, whole seconds, sorted, merged, within
    `[0, duration]`.
  - `TutorSuggestion.params`: the numbers its wording needs (`{"answers": 6, "share": 40}`).
- `Assignment.state` (not `status`): assigned → in progress → completed; exempt and cancelled
  close it. Late is not a state: `due_at < now` and not closed.
- `CourseStep` points at exactly one of lesson, page or quiz (a check constraint). Steps are
  protected: archive a lesson, page or quiz, never delete one a course uses.

## 4. Rules

### 4.1 Page views (knowledge)

- The mini app's page reader (and the dashboard's page view) reports while the page is in front
  of the person: on open, then every 15 s, and on leaving: `{session, seconds, scrolled}`.
- `seconds` added per report is at most the time since the previous report of that session plus
  5 s, and at most 30; `scrolled` keeps the maximum; `version` the newest opened.
- A new visit starts when the previous report is more than 30 minutes old.
- Readers (`ReadersDrawer`) show for each person in the audience: opened or not, visits, reading
  time, how far down, the version seen, confirmed (the existing acknowledgement) or not.
- Always on (also without `learning`); a person never sees anyone else's views.

### 4.2 Video progress (who watched what)

- The player reports every 10 s while playing, on pause, on seek and on leaving:
  `{session, position, duration, ranges: [[start, end], …], playing}`, where `ranges` are what
  was played since the previous report (media seconds), and `session` is a random id per opening.
- The server clips each range to `[0, duration]`, merges it into `LessonProgress.ranges`, and
  accepts at most `(now − last_report_at) × max_speed_percent / 100 + 5` new seconds per report
  (the excess is cut from the end of the newest range): skipping or a forged report can't fill
  the bar faster than real playing time at 2×.
- `watched_seconds` = length of the union; `percent` = floor(watched / duration × 100), capped
  at 100; `position` = the resume point (the last position unless within 5 s of the end);
  `spent_seconds` grows by the accepted seconds; `sessions` counts distinct sessions.
- **Watched** when `percent ≥ completion_percent` (90): `completed_at` is set once and never
  unset; points (`lesson`); the course step is done for every open assignment holding the
  lesson.
- YouTube: the duration comes from the player's first report (kept on the lesson when it has
  none). A video still processing can't be watched (the lesson says so).
- Who watched what (dashboard): per lesson, everyone in its audience or with it in an open course:
  never opened / watching (percent, a strip of the watched ranges) / watched (when), time spent,
  sessions, last watched; per person, every lesson.

### 4.3 Question kinds

| Kind | `data` (server only) | Shown to the person | Answer | Full points when | Partial credit (if the quiz allows) |
|---|---|---|---|---|---|
| `single` | `{"options": [{"id", "text", "correct"}]}`, exactly one correct, 2–6 options | options shuffled | `{"option": "b"}` | the right option | none |
| `multi` | same, at least one correct | options shuffled | `{"options": ["a", "c"]}` | exactly the right set | max(0, (right picked − wrong picked) / right total) |
| `true_false` | `{"answer": true}` | the statement | `{"value": false}` | equal | none |
| `order` | `{"items": [{"id", "text"}]}` in the right order, 3–8 | items shuffled | `{"order": ["c", "a", "b"]}` | the same order | share of items in their right place |
| `match` | `{"pairs": [{"id", "left", "right"}]}`, 2–6 | left side as written, right side shuffled (ids of the pairs) | `{"pairs": {"<left id>": "<right id>"}}` | every pair right | share of pairs right |
| `text` | `{"answers": ["2–8", "2-8"], "case": false}` | a box | `{"text": "2-8"}` | it equals an accepted answer after normalising (trim, collapse spaces, lower case unless `case`, ‘’`' unified, dashes unified, "°C" and "C" ignored) | none |
| `number` | `{"value": 4.5, "tolerance": 0.1, "unit": "ml"}` | a number box with the unit | `{"value": 4.5}` | `abs(answer − value) ≤ tolerance` | none |

- A question has `points` (1–10), an optional picture, an `explanation` shown after answering,
  a topic, a difficulty, a state (drafts and archived ones are never drawn).
- An unanswered question scores 0. Score = Σ(points × share); percent = floor(score / max × 100);
  passed = percent ≥ pass mark.
- Validation on save: the shapes above, unique ids, the option counts, non-empty texts (≤ 300
  each), `tolerance ≥ 0`.
- `Question.answered` and `correct` (cached) count answers from attempts, checks and the daily
  question; a quiz's "hardest questions" list sorts by correct share.

### 4.4 Courses, steps, completion, certificates

- A course has ordered steps: lesson (done when watched, §4.2), page (done when the person has
  confirmed the page's current version, the existing acknowledgement, whatever its `require_ack`),
  quiz (done by a passed attempt finished after the assignment began). `required=False` steps
  don't count for completion.
- Sequential courses open step N once every required step before it is done; others in any order.
- Progress: `steps_done / steps_total` (required steps), cached on the assignment after each
  change. The first activity moves an assignment to in progress.
- **Completed** when every required step is done: `completed_at`, the certificate number
  (`<prefix>-<year>-<number>`, `LearningSettings` counter under a row lock) when the course gives
  one, `expires_at = completed_at + renew_months` for renewing courses, points (`course`), a
  notice to the person ("certificate ready" with the PDF), badges through recognition.
- Changing a published course's steps: new required steps reopen nobody's completed assignment;
  open assignments recount (a removed step's completion no longer counts).
- **Certificate PDF** (`apps/core/pdf.render_pdf`, uz/ru/en, `%PDF`): the company, the person,
  the course, the date, the number, valid until (renewing courses), the manager line; employee and
  owner downloads through signed links.

### 4.5 Assignments: who has to do what, by when

- **Audience** of a course: everyone (`audience_all`) or the chosen positions, narrowed to the
  chosen branches when any (a person's branches: `Membership.branches` / home branch). Approved
  members only; suspended people keep their assignments but get no reminders.
- **Mandatory** published course: everyone in the audience has an assignment of the current
  cycle. `sync_audiences` (hourly, idempotent) assigns whoever is missing: people who joined,
  changed position or branch. Leaving the audience cancels nothing already finished; an open
  assignment of someone no longer in the audience stays (a manager may cancel it).
- **Due date** = assigned + `due_days` (at the end of that day in the company's time); no
  `due_days`, no deadline. New hires get the same count from their own assignment.
- **Manual**: a manager with `learning.manage` assigns a published course to people they see
  (branch scope), with an optional due date. **Tutor**: through an accepted suggestion. **Self**:
  a person starts an optional course of their audience (`catalog_for_staff`).
- **Renewal**: `renew_due` (daily) opens cycle + 1 of a completed renewing course 14 days before
  `expires_at`, due at `expires_at` (source renewal).
- **Exempt** (with a reason) and **cancel** close an open assignment (managers; audited).
- **Reminders** (`send_reminders`, hourly; each company at its morning report hour,
  `Company.morning_report_at`, else 09:00): due within `remind_before_days` → one reminder; late →
  a notice on the first late day, then every 3 days, at most 3; `escalate_after_days` late → one
  notice to the person's managers (department heads up the chain, `apps.members.departments`,
  else holders of `learning.manage` who see them), batched per recipient ("3 people are late with
  mandatory training"). People on approved time off today get nothing that day.

### 4.6 Mastery and the skill matrix

- Every answered question writes an `AnswerLog` (attempts, checks, the question of the day) with
  the question's topic at that time and `share` (0–1).
- Mastery of a person in a topic = the weighted mean of `share` over their last 20 answers in the
  topic, weights 0.85^age (newest 1), × 100, rounded. Rated from `MIN_ANSWERS` (3) answers; band
  weak (< 60), ok, strong (≥ 85) (`skills.py` constants, pinned by the contract test).
- The matrix (dashboard): people × topics with the score (colour by band, unrated grey), the
  number of answers on hover, filters by branch, position and topic; a row per person links to
  their learning page; column averages; a topic's weakest people first.

### 4.7 Quizzes and attempts

- **Fixed** quizzes ask their list (`QuizQuestion` order, shuffled when `shuffle_questions`).
  **Random** quizzes draw `question_count` active questions from the quiz's topics plus its list:
  spread over the topics (round robin), preferring questions the person hasn't answered right in
  their last two attempts of the quiz, then the rest; fewer available than asked → all of them.
- Options shuffled per attempt when `shuffle_options` (stored in `items[].order`).
- **Starting**: published, the person may take it (in its audience, in an open course of theirs,
  a check entry of theirs, or a manager trying it — a manager's own attempts never count in
  results or points), `max_attempts` not used up, `retry_after_minutes` passed since the last
  finished attempt; an attempt in progress is resumed instead of starting another.
- **Answers** are saved one by one (autosave); a time limit sets `deadline_at`; after it the
  attempt is graded with what was saved (`expire_attempts`, every 5 minutes, and on any read).
- **Finishing** grades on the server, writes the answer logs, updates `Question` counters,
  calls `courses.on_attempt_finished(attempt)` and recognition (`quiz`, `quiz_perfect` at 100 %,
  once per quiz and person each), then returns the result with the review the quiz allows
  (`show_answers`: after / passed / never).
- A manager may reset someone's attempts (audited): the attempts stay in history but stop
  counting for `max_attempts`.

### 4.8 The question of the day

- `LearningSettings.daily_question` on, at `daily_at` (company time), on the company's workdays,
  for approved people (only `daily_position_ids` when set) who are not on time off or suspended.
- One question per person per day: topics from their open courses and the company's topics,
  preferring their weakest rated topic, then unrated ones; never a question they saw in the last
  30 days while others are left; kinds `single`, `multi`, `true_false` go to the bot with buttons
  (§9.2), the others only to the mini app's Home card (the bot message then has "Answer in the
  app").
- Answering (bot or app, until the end of that day): the result, the explanation, the right
  answer, points (`daily`: 5 right, 1 for trying), the streak.

### 4.9 Regular checks ("mandatory stuff asking")

- A check sends its quiz to its audience (positions, branches or everyone) every week (weekday)
  or month (day 1–28) at `at`, to answer within `answer_within_hours`.
- `run_checks` (every 10 minutes): starts the rounds that are due (`CheckRound` + a `CheckEntry`
  per person, a notice with "Start" to each), reminds whoever hasn't answered at half time and
  2 hours before the end, closes rounds at their end (counts; a digest to the managers: done,
  passed, the weakest questions, who didn't answer), then sets `next_run_at`.
- Each person's attempt is a fresh draw when the quiz is random; a check attempt allows one try
  unless the quiz allows more; points `check` when passed.

### 4.10 The tutor's suggestions

Worked out by the tutor weekly and after each closed check round, kept as `TutorSuggestion`
(one open per person, kind, topic and course), worded at read time:

| Kind | When | Action |
|---|---|---|
| `assign` | weak in a topic (rated) and a published course or lesson covers it, not finished | Assign the course (or its lesson's course) |
| `lesson_needed` | ≥ 2 people weak in a topic and nothing published covers it (company-wide) | Open "new lesson" with the topic |
| `overdue` | late with mandatory training ≥ `escalate_after_days` | Remind them / open their page |
| `mentor` | strong (≥ 90, ≥ 10 answers) in a topic where others are weak | Note to the manager: "could coach …" |
| `praise` | the week's top learners (top 3 by points, ≥ 30 points) | Send kudos (recognition) |

A suggestion resolves itself (`done`) when its reason goes away (the course finished, the topic no
longer weak). Accepting and dismissing are audited.

## 5. Video pipeline

- **Upload** (owner API, `learning.manage`): `POST learning/videos/` `{name, size}` → a `Video`
  (uploading) with `upload_expires_at` = now + 24 h and the chunk size (8 MB); `PUT
  learning/videos/{id}/chunk/?offset=N` with raw bytes (each ≤ 8 MB, in order; the reply says the
  bytes received, so a dropped connection resumes); `POST learning/videos/{id}/finish/` → processing
  and `process_video` queued. Refused: over 2 GB, over the company's storage limit (sum of
  `size_bytes` + uploads in progress), a company without the module.
- **Processing** (`tasks.process_video`, queue `media`): `ffprobe` (JSON) must find a video stream
  in an allowed container (mp4/mov/m4v/3gp/webm/mkv/avi); duration ≤ 3 h; then `ffmpeg -nostdin
  -threads 2` under `nice`: H.264 (`libx264 -preset veryfast -crf 26 -profile:v high -pix_fmt
  yuv420p`), at most 720 px high (even sizes), at most 30 fps, AAC 96 kbit/s stereo,
  `-movflags +faststart`; a poster (JPEG, through `apps.core.uploads.sanitize_image`) at 10 % of the
  duration; a timeout of 4 × duration + 5 minutes. Success: `file`, `poster`, `size_bytes`,
  `duration_seconds`, `width`, `height`, `ready`; the original and the pieces are deleted; lessons
  using the video get its duration. Failure: `failed` with a message for the owner, the pieces
  deleted. Never trust the client's name or type; the stored name is the server's.
- **Serving**: `apps.core.files` learns the `learning` storage and `.mp4` (inline) and serves
  Range requests (206); `signed_url(video.file, …, check="learning.video:<id>", ttl=6 h)`. In
  production (`LEARNING_MEDIA_ACCEL=/_learning/`) Django answers a valid link with
  `X-Accel-Redirect: /_learning/<path>` and Caddy's `handle_response` serves the file from its
  read-only mount (Range, sendfile, no gzip). The check `learning.video` lets in a user who may
  open some lesson with that video (`queries.can_open_lesson`) or holds `learning.manage`.
- **Deploy**: the image gets `ffmpeg`; a `media-worker` service (`celery … -Q media -c 1
  --prefetch-multiplier 1`, `cpus: 2`, profile app) and the `learning_media` volume (backend,
  worker, media-worker read-write; caddy read-only at `/srv/learning`); `deploy/Caddyfile` gets the
  `handle_response`; the backup service leaves `learning_media` out of the daily tar and keeps a
  weekly copy of it (2 kept). `docs/DEPLOY.md` says all of this.
- **Cleanup** (`clean_uploads`, daily): uploads past `upload_expires_at` are deleted with their
  pieces; a deleted lesson's video goes when nothing else uses it.

## 6. The tutor agent (`apps/ai/agents/tutor.py`)

- `Agent(key="tutor", name=_("Tutor"), features=("learning",), needs_claude=False,
  default_enabled=True, icon="graduation-cap")` with fields: `weekly_report` (on), `report_day`
  (Monday), `at` (09:00), `nudge_learners` (on), `suggest` (on), `weak_threshold` (60).
- **Weekly report** (on the day at the time, company time) to holders of `learning.manage`, each
  about the people they see (branch scope), owner bot for owners and top managers, the employee
  bot for others (inbox kind `learning.tutor_report`, `apps.inbox.delivery.bots_for`):
  mandatory training (done / of / late, by name up to 5), the week's tests (count, average), the
  weakest topic, the top three learners (points), who needs help (weak topics, late), and the
  open suggestions with "Assign suggested" (accepts every open `assign` suggestion of that
  reader's scope) and "Open" (the dashboard's tutor page). Without Claude: the template; with
  Claude: one call writes a two-sentence opening from the facts (a number that isn't among the
  facts sends the template instead, as the HR assistant does). No phone numbers, ids or pay.
- **Nudges** (`nudge_learners`): the day after a person scored below the pass mark in a topic (a
  quiz or a check), at most one every 3 days: "Yesterday's test on <topic> was hard. This lesson
  helps: <lesson>" with "Watch" (mini app). Template wording; never during time off.
- **Suggestions** (§4.10), computed weekly and after each closed check round.
- **Writing questions** (`drafting.py`): from a page (its text) or a lesson (notes + transcript),
  `count` (1–15), kinds, difficulty, topic → `Question` drafts (`source` ai or rules, `state`
  draft) for a manager to review, edit and activate in the bank. Claude: one structured call
  (Haiku), every question validated against §4.3; a number in a question or answer that isn't in
  the source text drops that question. **Rules** (no Claude, no AI module, or out of budget):
  sentences with numbers, temperatures, days or percentages become `number`/`text` questions
  with the number blanked, and their changed number a `true_false` one; numbered or bulleted
  steps become `order`; "term – meaning" lines become `match`. The job runs on the ai queue
  (`tasks.draft_questions`) and the dashboard polls it.
- **Ask the tutor**: an Ask AI conversation with `AIConversation.agent = "tutor"` (migration
  `ai/0006`, package Q2): the tutor's instructions follow the system prompt (the company's own
  instructions for the agent after them, `apps.ai.instructions`), and the tools are the learning,
  knowledge, recognition and member tools. In the dashboard: the tutor page's chat; in the owner
  bot: the report's "Ask the tutor" opens that page inside Telegram.
- **Its page and chibi**: the agents' room shows the tutor at its desk (mortarboard, round
  glasses, a pile of books, chalk-dust sparkle when it finishes a report; warm amber); its
  upcoming list says when the next report and today's daily questions go out; its events say what
  it did ("Sent the weekly report to 2 people", "Made 4 suggestions"). Keep it cute and out of
  the way (the owner loves the chibis).

## 7. Recognition (`apps.recognition`)

### 7.1 Points

| Reason | Points | Key (once per) |
|---|---|---|
| `lesson` watched | 10 | `lesson:<lesson>:<member>` |
| `page` confirmed in a course | 5 | `page:<page>:v<version>:<member>` |
| `quiz` passed | 20 | `quiz:<quiz>:<member>` (first pass) |
| `quiz_perfect` (100 %) | 10 | `quiz-perfect:<quiz>:<member>` |
| `course` finished | 50 | `course:<assignment>` |
| `daily` question | 5 right, 1 tried | `daily:<daily>` |
| `check` passed | 15 | `check:<entry>` |
| `streak` 7 / 30 / 100 days | 20 / 100 / 300 | `streak:<member>:<kind>:<length>:<start day>` |
| `kudos` received | 5 | `kudos:<kudos>` |
| `task` done on time (not personal, at most 10 a day) | 2 | `task:<task>` |
| `adjust` (an owner's correction, ± with a note) | any | `adjust:<uuid>` |

The company can change the numbers (`RecognitionSettings.points_table`, `{reason: points}`).
Points are never money.

### 7.2 Levels

Ten levels by total points: 0, 100, 250, 500, 1 000, 2 000, 3 500, 5 500, 8 000, 12 000.
Names: Newcomer, Learner, Active, Knowledgeable, Experienced, Specialist, Mentor, Expert, Master,
Legend (uz: Yangi boshlovchi, O‘rganuvchi, Faol, Bilimdon, Tajribali, Mutaxassis, Ustoz, Ekspert,
Usta, Afsona; ru: Новичок, Ученик, Активный, Знаток, Опытный, Специалист, Наставник, Эксперт,
Мастер, Легенда). A new level: a notice (bot, plain words) and the app's celebration.

### 7.3 Badges (catalogue in code, `apps/recognition/badges.py`)

`first_lesson`, `first_quiz`, `perfect_score`, `course_finisher`, `five_courses`, `streak_7`,
`streak_30`, `streak_100`, `daily_10` (ten daily questions right), `topic_expert` (per topic:
mastery ≥ 90 with ≥ 10 answers; `ref` the topic id), `early_bird` (a mandatory course finished in
its first three days), `helper` (gave 10 kudos), `thanked` (received 10 kudos), `on_time_week`
(every task of a work week on time, at least 5), `top3_month` (top three of a month; `ref`
"YYYY-MM"). Each has a lucide icon, a tier (bronze, silver, gold) and en/uz/ru name and
description. Checked after each award (`award`'s after-commit hook) and by a nightly job.

### 7.4 Streaks

A learning day is a company day with a lesson watched or progressed by ≥ 60 s, a quiz finished
or the question of the day answered. `touch_streak(member, day)`: +1 when the last counted day is
the previous workday of the company (days off, holidays and the person's approved time off in
between are skipped), same day → no change, otherwise 1. `best` keeps the record. Milestones
7 / 30 / 100 → points and badges.

### 7.5 Kudos (PLAN-OWNER §3.16)

From one colleague to another (never oneself), a badge (thanks, teamwork, fast, careful, helpful,
star), a note ≤ 200, optionally a task; `kudos_per_day` (3) per giver; the receiver gets 5
points and a bot message ("Madina thanked you: careful work."); owners (`recognition.manage`)
hide one (audited), and a hidden one disappears everywhere. A feed in the mini app and the
dashboard; optional posts to linked groups (`post_kudos_to_groups`, Should).

### 7.6 Leaderboards

Points in a period: this week (Monday to Sunday, company time), this month, all time; scope the
company or a branch. Staff (`leaderboard_for_staff`) see the top ten and their own place in
their scope (`leaderboard_scope`); managers see everyone they see. People with no points aren't
listed; ties by who got there first. Monthly top three get `top3_month` on the 1st.

### 7.7 Task points

A nightly job (and on the next morning's run) gives `task` points for yesterday's tasks finished
on time (daily routines and assigned tasks; not personal ones; at most 10 a person a day), when
`task_points` is on. It reads tasks through `apps.tasks.queries`; tasks code is not changed.

## 8. Permissions, switches, settings

| Code | Who by default | What |
|---|---|---|
| `learning.view` | Manager (and every role that manages routines, members/0017) | See training, results and skills of the people they see (branch scope) |
| `learning.manage` | same | Make lessons, courses, quizzes, checks; assign, exempt, reset; settings |
| `recognition.manage` | owners only | Hide kudos, correct points, recognition settings |
| `knowledge.manage` | owners | (unchanged) also keeps topics |

- Every person sees their own training in the mini app (no permission); never someone else's
  results unless they hold `learning.view` (and then only people they see).
- Module `learning` off: learning endpoints answer 404, jobs skip the company, the dashboard and
  mini app hide it, the tutor isn't listed. Module `recognition` off: nothing awarded or shown.
- `LearningSettings` (Settings › Training panel, Q1; the daily-question fields Q2), and
  `RecognitionSettings` (Settings › Recognition panel, R).

## 9. Jobs, notifications and the bots

### 9.1 Beat (in `apps/learning/beat.py`, fixed) and inbox kinds

Jobs: `sync_audiences` (hourly), `send_reminders` (hourly), `renew_due` (daily), `clean_uploads`
(daily) — Q1; `send_daily_questions` (every 10 min), `run_checks` (every 10 min),
`expire_attempts` (every 5 min) — Q2; recognition adds its own (task points, monthly top three,
the badge sweep) in `apps/recognition/beat.py` — R.

Inbox kinds (each registers with its label, audience and actions):

| Kind | Package | To | Buttons |
|---|---|---|---|
| `learning.assigned` | Q1 | the learner (batched per burst) | Open (mini app course) |
| `learning.due_soon`, `learning.overdue` | Q1 | the learner | Open |
| `learning.escalated` | Q1 | managers (digest) | Open (dashboard people) |
| `learning.certificate` | Q1 | the learner | Open (certificate) |
| `learning.daily` | Q2 | the learner (Telegram only, the bot's own message, §9.2) | answers |
| `learning.check_started`, `learning.check_reminder` | Q2 | the learner | Start (mini app) |
| `learning.check_results` | Q2 | managers | Open |
| `learning.tutor_report` | Q2 | managers | Assign suggested, Open |
| `learning.nudge` | Q2 | the learner | Watch |
| `recognition.kudos` | R | the receiver | Open |
| `recognition.level`, `recognition.badge` | R | the person | Open |

### 9.2 Employee bot

- **Question of the day** (Q2, `employee_bot/bot/handlers/features/learning.py`,
  `apps/learning/callbacks.py`): the message "Question of the day" + the question + the options
  (A–F, the texts in the message when long); `single` and `true_false` answer with one tap;
  `multi` toggles (the chosen letters shown in the text) and "Answer"; after answering the message
  is edited to the result, the explanation, points and the streak, with "Open in the app".
  Answered in the app first → the bot message is edited the same way. Callback data holds only the
  daily id and the option id; the handler checks the person owns it and it's still that day.
- **Kudos** (R, `recognition.py`): the receiver's message and "Say thanks back" (opens the
  mini app's kudos sheet).

## 10. The contract between packages

Signatures fixed in the lead step, pinned by `apps/learning/tests/test_contract.py`; keep them.

| Function | Owner | Called by |
|---|---|---|
| `learning.courses.assign(course, members, *, by, source="manual", due_at=None)` | Q1 | Q2 (suggestions), the tutor |
| `learning.courses.on_attempt_finished(attempt)` | Q1 | Q2 (grading) |
| `learning.queries.compliance(company, *, branch_ids, now=None)` | Q1 | Q2 (report, suggestions), R? |
| `learning.queries.open_assignments(member)` | Q1 | Q2 (daily topics), P |
| `learning.queries.courses_for_topic(company, topic_id)` / `lessons_for_topic` | Q1 | Q2 (suggestions, nudges) |
| `learning.queries.can_open_lesson(member, lesson)` | Q1 | file checks |
| `learning.skills.mastery(company, *, member_ids=None, topic_ids=None, since=None)` | Q2 | Q1 (person page), R (topic_expert), the tutor |
| `learning.conf.get_settings(company)`, `is_on(company)` | lead | all |
| `recognition.services.award(member, *, reason, key, points=None, note="", at=None, by=None)` | R | Q1, Q2 |
| `recognition.services.touch_streak(member, day, *, kind="learning")` | R | Q1, Q2 |
| `recognition.queries.summary(member)`, `levels()` | R | Q1 (person page), P (Home) |
| `knowledge.topics.*` | lead | Q1, Q2 |
| `apps.ui.celebrate` (mini app `src/ui/celebrate.ts`) | lead | P, R |

Until a package lands, its functions are stubs that do nothing (recognition returns None, the
learning queries return empty results); callers must work with that.

## 11. Dashboard

Modules (catalog entries exist; group People): `learning` (Q1, hotkey l), `quizzes` (Q2, hotkey
q), `recognition` (R). Routes under `/c/:companyId/learning/…` (Q1 and Q2) and `recognition/…` (R).
Extension points: `learning.person.panels` (Q1's person page; Q2: skills and quiz history; R:
points, level, badges), `learning.overview.cards` (Q1's overview; Q2: suggestions and weakest
topics; R: top learners).

- **Q1 `learning`**: Overview (mandatory completion ring, late people, hours watched this week,
  activity by day, courses by completion; the slot); Courses (list with completion bars; editor:
  details, audience, mandatory/deadline/renewal/certificate, steps with drag order and pickers for
  lessons, pages and quizzes, publish; People tab: everyone assigned with progress, due, late,
  actions: assign more, remind, exempt, move the deadline, cancel); Lessons (list; editor: upload
  with a progress bar and resume, or a YouTube link, poster preview, notes in the rich editor,
  topics, audience, publish; Who watched tab, §4.2); People (people × mandatory courses grid with
  states; a person's page: their courses, lessons watched, the slot); Settings › Training panel;
  the knowledge base's Readers drawer and page list gain views (§4.1); topic pickers.
- **Q2 `quizzes`**: Quizzes (list with pass rate; editor: settings, fixed list or topics and
  count, preview as a learner; Results tab: attempts table, score distribution, the hardest
  questions, reset); Question bank (filters by topic, kind, difficulty, state, source; editor per
  kind with live validation and a preview; "Write questions from…" a page or lesson → the drafts
  to review and activate; bulk activate/archive); Checks (list, editor with schedule and audience,
  rounds with results); Skills (the matrix, §4.6); Tutor (suggestions with accept/dismiss, the last
  report, "Ask the tutor" chat); daily question fields in Settings › Training; the tutor's chibi
  and agent page entries in `modules/ai`.
- **R `recognition`**: Leaderboard (podium for the top three with avatars and levels, the list,
  week/month/all, branch filter); Kudos (feed with hide); Badges (catalogue with who has each);
  Settings › Recognition panel; a person's points and badges panel (slot).

House rules: the component library, DataTable with export where it lists rows, i18n en/uz/ru,
empty/loading/error states, the pulse keys, phone-width layouts, both themes.

## 12. Mini app

### 12.1 `learning` (P)

- Home cards: "Training" (mandatory courses open: title, progress, due or late; at most 3, "All")
  and "Question of the day" (answer in place, the result with confetti when right), and a check
  card while a round of theirs is open ("Weekly check: 5 questions, by Wednesday 10:00", Start).
- Me item "My training" (badge: open mandatory courses).
- Pages: home (To do / Done / Catalogue tabs; certificates); course (header with progress and due,
  steps with locked / open / done states, "Continue"); lesson (the player: HTML5 `<video
  playsInline>` with the signed MP4 and the poster, or the YouTube IFrame player
  (`youtube-nocookie.com`, `enablejsapi`); resume from `position`; progress reports §4.2 with a
  retry queue; notes below; "Next step" when watched); quiz intro (questions, time, pass mark,
  attempts left, cool-down) → the player (one question per screen, a progress strip, a timer,
  answers autosaved, every kind of §4.3 with large touch targets: radio cards, checkbox cards,
  two big true/false buttons, order by drag handle or up/down buttons, match by tapping a left
  then a right, text and number inputs with the unit) → the result (a score ring, passed or not,
  points, confetti when passed, the review the quiz allows, retry or its time, back to the
  course); certificate (PDF link).
- The knowledge page reader reports views (§4.1).
- Deep links: `learning`, `course:<id>`, `lesson:<id>`, `quiz:<id>`, `check:<entry id>`,
  `daily`; `startapp=learn-<course id>`.

### 12.2 `recognition` (R)

- Home hero chip under the greeting: level badge, points this week, the streak flame with days.
- Me item "My achievements": level ring and the next level, points history, badges (earned and
  locked, with how to get them), the streak; the leaderboard page (podium, list, my place, tabs).
- Kudos: the (+) action "Say thanks" (pick a colleague from the team directory, a badge, a note),
  a feed of received and given; a Home card when someone thanked you today.
- Celebrations when the app opens after a new level or badge (`GET recognition/me/` lists the
  unseen ones; `POST recognition/seen/`): a sheet with the badge and confetti.
- A task finished on time gets a small confetti burst and a buzz (a one-line call in the task
  screen's done handler; R lists it as a shared-file edit).

### 12.3 Celebrations (`src/ui/celebrate.ts`, lead)

`celebrate({from?, pieces?, haptic?})`: confetti over the screen for ~1.6 s and Telegram's
success haptic; nothing drawn under reduced motion. Use it for real achievements only (passed,
finished, new level or badge, the day's question right, a task on time), never for routine taps.

## 13. API

Employee endpoints (mounted at `/api/v1/companies/{c}/`, the mini app's token; 404 while the
module is off; a person only ever sees their own). The shapes below are the contract with P;
names are snake_case JSON, times ISO in UTC, the app shows them in the company's zone.

**Q1 (courses and lessons)**

- `GET learning/` →
  `{todo: [AssignmentCard], done: [AssignmentCard] (newest 20), catalog: [CourseCard], certificates: number}`
  - `AssignmentCard = {id, state, percent, steps_done, steps_total, due_at|null, late: bool, completed_at|null, certificate_url|null, course: CourseCard}`
  - `CourseCard = {id, title, emoji, color, description, mandatory, steps: number, minutes: number}`
- `GET learning/courses/{id}/` →
  `{...CourseCard, sequential, certificate, assignment: AssignmentCard|null, can_start: bool, steps: [Step]}`
  - `Step = {id, kind: "lesson"|"page"|"quiz", title, emoji, required, done, locked, done_at|null, lesson_id|null, page_id|null, quiz_id|null, minutes|null, best_percent|null}`
- `POST learning/courses/{id}/start/` → `AssignmentCard` (optional courses of their audience).
- `GET learning/lessons/{id}/?course=<id>` →
  `{id, title, emoji, summary, notes_html, source: "upload"|"youtube", video: {url, poster_url, duration_seconds, width, height}|null, youtube_id, duration_seconds, processing: bool, topics: [{id, name, color}], completion_percent, progress: {percent, position, completed_at|null, ranges}|null, next: {kind, id, title}|null}`
  (`url` and `poster_url` are signed, valid 6 h).
- `POST learning/lessons/{id}/progress/` `{session, position, duration, ranges, playing}` →
  `{percent, position, completed: bool, completed_now: bool, points: number|null}`.
- `GET learning/assignments/{id}/certificate/` → the PDF.
- `POST knowledge/pages/{id}/view/` `{session, seconds, scrolled}` → 204 (knowledge app, always on).

**Q2 (quizzes, the question of the day, checks)**

- `GET learning/quizzes/{id}/?assignment=<id>&entry=<id>` →
  `{id, title, emoji, description, questions: number, time_limit_seconds|null, pass_percent, max_attempts|null, attempts_used, retry_at|null, best: {percent, passed}|null, in_progress: number|null, can_start: bool, reason: string|null}`
- `POST learning/quizzes/{id}/attempts/` `{assignment?: id, entry?: id}` → `AttemptPlay`
  - `AttemptPlay = {id, quiz: {id, title, emoji, pass_percent}, number, started_at, deadline_at|null, questions: [QuestionPlay], answers: {"<id>": answer}}`
  - `QuestionPlay = {id, kind, text, image_url|null, points, options: [{id, text}] (single, multi, order), left: [{id, text}], right: [{id, text}] (match), unit: string|null (number)}`
- `GET learning/attempts/{id}/` → `AttemptPlay` while in progress, else `AttemptResult`.
- `PUT learning/attempts/{id}/answers/` `{question: id, answer}` → 204 (400 after the deadline).
- `POST learning/attempts/{id}/finish/` → `AttemptResult`
  - `AttemptResult = {id, state, score, max_score, percent, passed, points: number|null, retry_at|null, course_step_done: bool, review: [{question: QuestionPlay, answer, correct, share, right_answer|null, explanation}]|null}`
- `GET learning/daily/` → `{daily: {id, day, question: QuestionPlay, answered, correct|null, answer|null, right_answer|null, explanation|null}|null, streak: number|null}`
- `POST learning/daily/{id}/answer/` `{answer}` → `{correct, share, right_answer, explanation, points: number|null, streak: number|null}`
- `GET learning/checks/` → `[{entry_id, title, quiz_id, due_at, done, passed|null}]` (open rounds and the last closed ones).

**R (recognition)**

- `GET recognition/me/` → `{enabled, points, week_points, level: {number, name, starts_at, next_at|null}, streak, best_streak, badges: [{key, ref, name, description, icon, tier, awarded_at}], locked: [{key, name, description, icon, tier}], recent: [{points, reason, label, at}], unseen: [{type: "level"|"badge", key?, name, icon?, number?}]}`
- `POST recognition/seen/` → 204.
- `GET recognition/leaderboard/?period=week|month|all&scope=company|branch` → `{visible, period, start|null, end|null, rows: [{place, member: {id, name, avatar_url|null, position|null}, points, level}], me: {place|null, points}}`
- `GET recognition/kudos/?box=received|given` · `POST recognition/kudos/` `{to, badge, message, task?}` · `GET recognition/kudos/colleagues/?q=`.

Owner endpoints (`/api/v1/owner/companies/{c}/…`) belong to each package with its dashboard
pages: Q1 `learning/{overview,courses,lessons,videos,assignments,people,settings}/…`, Q2
`learning/{questions,quizzes,attempts,checks,skills,suggestions,drafts,tutor}/…`, R
`recognition/…`, all with rule 21 (company scope, `Perm`, audit, pulse, `extend_schema`, tests
for another company's id, a missing permission and hidden fields).

## 14. The demo story (Demo Dorixona)

Topics: the pharmacy set. Lessons (Q1): "Sovuq zanjir: muzlatgich va termometr" (generated
placeholder video when ffmpeg is there, else a YouTube-less text lesson state), "Retseptli dorini
berish tartibi", "Kassa: chek va qaytarish", "Muddat o‘tgan dorilar bilan ishlash". Courses:
"Yangi xodim kursi" (mandatory for everyone, 14 days), "Sovuq zanjir" (mandatory for
pharmacists, renews every 12 months), "Retsept bo‘yicha dori berish" (pharmacists), "Kassa
qoidalari" (cashiers, optional for others). Progress: Madina (senior pharmacist) finished all with
certificates and is strong in the cold chain; Alisher is late with "Sovuq zanjir" and weak in it;
Nigora (night pharmacist) half-way, weak in prescriptions; Jasur (courier) finished the new-hire
course. Quizzes (Q2): about 40 Uzbek pharmacy questions of every kind, a random "Sovuq zanjir
testi", a fixed "Retsept testi", a weekly check "Dushanba tekshiruvi", answer logs over four weeks
so the matrix and the suggestions tell the story, a question of the day history, an open round.
Recognition (R): points from that activity (through `award`, so the keys match), streaks, badges
(Madina: course finisher, streak 7, cold-chain expert), kudos between colleagues, a leaderboard
with Madina first. The tutor: last Monday's report and open suggestions (assign "Sovuq zanjir" to
Alisher, Madina could coach the cold chain, a lesson is missing on prices).

## 15. Packages, ownership and order

The lead step (on `main`): this plan, the models and migrations, the permissions and members/0017,
the `learning` switch, topics (`apps/knowledge/topics.py` + endpoint), the split plumbing of
`apps.learning` (hooks, urls, beat, tasks, demo, ai_tools by package), the contract stubs and test,
the dashboard catalog entries, perms, permission areas and extension points, `ui/celebrate.ts`,
the env files. Then four builders, each in its own worktree and branch:

| Package | Branch | Letter (db, ports) | Owns |
|---|---|---|---|
| **Q1** courses, lessons, videos | `v8/learning` | q (`trello_q`, 28280) | `apps/learning/{courses,lessons,media,progress,certificates,reminders,queries,api_courses,owner_api_courses,serializers_courses,urls_courses,owner_urls_courses,hooks_courses,ai_tools_courses,demo_courses,schedule_courses,notify_courses}.py`, the Q1 models' new fields, templates `learning/*.html`; `apps/knowledge` changes for page views and page topics (not `topics.py`); `apps/core/files.py` (learning storage, `.mp4`, Range, accel); `Dockerfile`, `docker-compose*.yml`, `deploy/Caddyfile`, `docs/DEPLOY.md` (video only); `dashboard/src/modules/learning/**`, `dashboard/src/modules/knowledge/**` (views); |
| **Q2** quizzes, skills, the tutor | `v8/quizzes` | k (`trello_k`, 28210) | `apps/learning/{quizzes,attempts,grading,daily,checks,skills,suggestions,drafting,quiz_queries,api_quizzes,owner_api_quizzes,serializers_quizzes,urls_quizzes,owner_urls_quizzes,hooks_quizzes,ai_tools_quizzes,demo_quizzes,schedule_quizzes,notify_quizzes,bot_messages,callbacks}.py`, the Q2 models' new fields; `apps/ai/agents/tutor.py`, `AIConversation.agent` + `ai/0006`, the chat's tutor branch (`apps/ai/chat.py`), tutor registrations; `employee_bot/bot/handlers/features/learning.py` + its tests; `dashboard/src/modules/quizzes/**`, the tutor chibi in `dashboard/src/modules/ai` (scene/chibi files only) |
| **R** recognition and fun | `v8/recognition` | r (`trello_r`, 28250) | `apps/recognition/**`; `employee_bot/bot/handlers/features/recognition.py` + tests; `dashboard/src/modules/recognition/**`; `miniapp/src/features/recognition/**`; the one-line celebration in the mini app's task done handler |
| **P** mini app learning | `v8/mini-learning` | p (`trello_p`, 28240) | `miniapp/src/features/learning/**`; the page reader's view reports in `miniapp/src/features/knowledge/**` |

- Shared files (`config/settings`, `members/permissions.py`, `companies/models.py`, `core/*`
  beyond what the table says, `dashboard/src/core/*`, `miniapp/src/ui/*`, the other apps): a small
  edit only when there is no other way, listed in the hand-off.
- P starts with Q1 and Q2: it builds against §13 with mocked responses, then merges
  `v8/learning` and `v8/quizzes` into its branch as they commit their employee endpoints (only
  merges, never edits their files) for the real run.
- Order inside each package: models' extra fields → services with tests (the rules of §4) →
  employee API (Q1, Q2 first, so P can merge) → owner API → dashboard → bot → AI tools → demo →
  Should.

## 16. Acceptance

- Learning off: every learning endpoint 404, no job touches the company, nothing in the apps.
- Video: an uploaded MP4 is processed into a playable 720p MP4 with a poster (ffmpeg present),
  a renamed text file is refused at processing with a message, a 2 GB + 1 upload is refused, a
  dropped upload resumes from the server's offset, the signed link answers 206 to a Range
  request, another company's video link is 404, a link stops working when the person loses
  access, production answers with `X-Accel-Redirect`.
- Who watched what: forged ranges can't add more than real time × 2 + 5 s; seeking to the end
  doesn't complete; overlapping ranges count once; 90 % completes, once.
- Courses: sequential locking; a quiz step needs a pass after the assignment began; completion
  makes one certificate number under concurrency; renewal opens the next cycle 14 days early;
  audience sync assigns new hires once; branch scope on every manager endpoint.
- Quizzes: every kind graded as §4.3 (golden tests, partial credit on and off); no right answer in
  any employee response before answering; random draws spread over topics; max attempts and
  cool-down; the time limit grades what was saved; a manager's attempts never count.
- Daily: one per person per workday, none on time off, buttons only for single/multi/true_false,
  a forged callback for someone else's question does nothing.
- Checks: rounds start once per period, reminders at half time and 2 h before, the digest at the
  end.
- Tutor: works without Claude (template report, rules drafting); with AI_FAKE the Claude path; a
  number not in the facts falls back to the template; no names outside the reader's scope.
- Recognition: award is idempotent per key; levels and badges once; streaks skip days off and
  leave; kudos limits and no self-kudos; hidden kudos vanish; leaderboard visibility for staff.
- uz/ru complete; demo shows every screen with data; `make schema-check` clean.
