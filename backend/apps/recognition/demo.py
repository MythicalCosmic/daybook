"""Demo data of recognition (docs/PLAN-LEARNING.md §14): points, streaks, badges, kudos and a
leaderboard with Madina first on Demo Dorixona.

It runs after learning's demo (INSTALLED_APPS order). The points of the learning the demo did
(lessons watched, tests passed, courses finished, the question of the day, regular checks) go
through `services.award` with the keys of §7.1, so whatever learning's own services already
gave isn't given twice; without any learning rows (this package alone) the same story is told
with demo keys. Then: points for the tasks done on time, thanks between colleagues over the last
three weeks (one to Alisher this morning, for Home's card), the learning streaks (Madina's
reaches 7), an owner's correction, last month's top three, and the levels and badges that
follow, dated when they were earned. The bot told nobody (it's a demo): everything is marked
notified; only Alisher's newest level and badge wait for the app's celebration.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from apps.core import demo_time
from apps.core.demo_plan import Plan
from apps.members.models import Membership
from apps.recognition import badges as catalogue
from apps.recognition import conf, progress, rules, services
from apps.recognition.models import BadgeAward, Kudos, LevelUp, PointsEntry

# Thanks between colleagues: (days ago, giver, receiver, badge, note, hour).
KUDOS = (
    (
        20,
        "madina",
        "worker",
        "careful",
        "Muzlatgich haroratini kechqurun ham tekshirib qo‘yding, rahmat.",
        18,
    ),
    (
        17,
        "nigora",
        "madina",
        "teamwork",
        "Tungi smenani tartibli topshirding, hammasi joyida edi.",
        8,
    ),
    (15, "jasur", "nigora", "fast", "Shoshilinch buyurtmani tez yig‘ib berdingiz.", 11),
    (12, "manager", "madina", "star", "Tekshiruvga hujjatlarni a’lo tayyorlading.", 16),
    (10, "worker", "madina", "helpful", "Navbat ko‘payganda darhol yordamga kelding.", 13),
    (8, "madina", "jasur", "thanks", "Yunusoboddan dorilarni vaqtida olib kelding.", 15),
    (6, "owner", "nigora", "careful", "Muddati yaqin dorilarni oldindan ajratib qo‘yibsiz.", 10),
    (4, "nigora", "worker", "fast", "Kassadagi qaytarishni tez hal qilding.", 7),
    (3, "manager", "worker", "teamwork", "Inventarizatsiyada oxirigacha qolding, rahmat.", 17),
    (2, "madina", "nigora", "helpful", "Retsept jurnalini to‘ldirishda yordam berding.", 9),
    (1, "jasur", "madina", "thanks", "Kuryer ro‘yxatini oldindan tayyorlab qo‘yding.", 12),
    (0, "madina", "worker", "careful", "Kirimni seriyalari bilan puxta tekshirding.", 9),
)

# Without learning's rows: what each person learned, as (days ago, reason).
# Madina finished every course and is strong in the cold chain; Alisher is late with his
# cold-chain course; Nigora is half-way; Jasur finished the new-hire course.
STORY = {
    "madina": [
        (26, "lesson"),
        (25, "quiz"),
        (24, "lesson"),
        (23, "course"),
        (21, "lesson"),
        (20, "quiz"),
        (20, "quiz_perfect"),
        (19, "course"),
        (18, "lesson"),
        (14, "check"),
        (14, "quiz"),
        (14, "quiz_perfect"),
        (13, "course"),
        (9, "course"),
        (7, "check"),
        (0, "lesson"),
    ],
    "worker": [(22, "lesson"), (16, "quiz"), (5, "lesson")],
    "nigora": [(19, "lesson"), (12, "lesson"), (11, "quiz"), (2, "lesson")],
    "jasur": [(27, "lesson"), (26, "course")],
    "manager": [(15, "lesson"), (8, "quiz")],
}
# The question of the day: (person, days ago from, to, every how many days, right out of 4).
DAILY = (
    ("madina", 27, 0, 1, 4),
    ("worker", 20, 0, 2, 3),
    ("nigora", 18, 0, 2, 3),
    ("jasur", 12, 1, 3, 2),
    ("manager", 14, 1, 3, 3),
)
# Learning streaks the story wants, ending today: person -> days in a row.
STREAKS = {"madina": 9, "nigora": 3, "worker": 2}


def seed(company, people, now) -> None:
    if not conf.is_on(company):
        return
    plan = Plan(company, people, now)
    today = plan.today
    if _learning_rows(company):
        _award_learning(company)
    else:
        _tell_the_story(plan, people)
    for back in range(28, 0, -1):
        services.award_task_points(company, today - timedelta(days=back))
    _kudos(plan, people, now)
    owner, madina = people.get("owner"), people.get("madina")
    if owner is not None and madina is not None:
        with demo_time.moment(plan.at(today - timedelta(days=11), time(18, 30))):
            services.adjust(
                madina,
                points=30,
                note="GPP tekshiruviga tayyorgarlikda katta yordam berdi.",
                by=owner,
            )
    last_month = today.replace(day=1) - timedelta(days=1)
    services.award_month_top(company, last_month, now=plan.at(today.replace(day=1), time(0, 40)))
    for member in Membership.objects.select_related("company").filter(
        company=company, status=Membership.Status.APPROVED
    ):
        progress.check(member, now=now)
    _story_badges(company, people, now)
    _date_what_was_earned(company, now)
    _mark_told(company, people, now)


# Learning that happened ---------------------------------------------------------------------


def _learning_rows(company) -> bool:
    from apps.learning.models import Assignment, Attempt, DailyQuestion, LessonProgress

    return any(
        model.objects.filter(company=company).exists()
        for model in (LessonProgress, Attempt, Assignment, DailyQuestion)
    )


def _award_learning(company) -> None:
    """The points of learning's own rows, with §7.1's keys (a no-op where learning's services
    already gave them), and the streak of each person's learning days in order."""
    from apps.learning.models import (
        Assignment,
        Attempt,
        CheckEntry,
        DailyQuestion,
        LessonProgress,
    )

    settings = conf.get_settings(company)
    days: dict[int, set[date]] = {}
    people: dict[int, Membership] = {}

    def note(member: Membership, moment: datetime) -> None:
        people[member.pk] = member
        days.setdefault(member.pk, set()).add(services.local_today(company, moment))

    for row in LessonProgress.objects.filter(
        company=company, completed_at__isnull=False
    ).select_related("membership__company"):
        member = row.membership
        services.award(
            member,
            reason=PointsEntry.Reason.LESSON,
            key=f"lesson:{row.lesson_id}:{member.pk}",
            at=row.completed_at,
        )
        note(member, row.completed_at)
    seen: set[tuple[int, int]] = set()
    for attempt in (
        Attempt.objects.filter(company=company, passed=True, finished_at__isnull=False)
        .select_related("membership__company")
        .order_by("finished_at", "pk")
    ):
        member = attempt.membership
        note(member, attempt.finished_at)
        if (attempt.quiz_id, member.pk) in seen:
            continue
        seen.add((attempt.quiz_id, member.pk))
        services.award(
            member,
            reason=PointsEntry.Reason.QUIZ,
            key=f"quiz:{attempt.quiz_id}:{member.pk}",
            at=attempt.finished_at,
        )
        if attempt.percent == 100:
            services.award(
                member,
                reason=PointsEntry.Reason.QUIZ_PERFECT,
                key=f"quiz-perfect:{attempt.quiz_id}:{member.pk}",
                at=attempt.finished_at,
            )
    for assignment in Assignment.objects.filter(
        company=company, completed_at__isnull=False
    ).select_related("membership__company"):
        services.award(
            assignment.membership,
            reason=PointsEntry.Reason.COURSE,
            key=f"course:{assignment.pk}",
            at=assignment.completed_at,
        )
    for daily in DailyQuestion.objects.filter(
        company=company, answered_at__isnull=False
    ).select_related("membership__company"):
        right = bool(daily.correct)
        services.award(
            daily.membership,
            reason=PointsEntry.Reason.DAILY,
            key=f"daily:{daily.pk}",
            points=rules.points_for(settings, "daily" if right else "daily_tried"),
            at=daily.answered_at,
        )
        note(daily.membership, daily.answered_at)
    for entry in CheckEntry.objects.filter(company=company, attempt__passed=True).select_related(
        "membership__company", "attempt"
    ):
        services.award(
            entry.membership,
            reason=PointsEntry.Reason.CHECK,
            key=f"check:{entry.pk}",
            at=entry.attempt.finished_at or entry.attempt.started_at,
        )
    for member_id, learned in days.items():
        for day in sorted(learned):
            services.touch_streak(people[member_id], day)


def _tell_the_story(plan: Plan, people: dict) -> None:
    """The same story without learning's rows: points with demo keys, the question of the day,
    and the streaks."""
    settings = conf.get_settings(plan.company)
    today = plan.today
    for key, events in STORY.items():
        member = people.get(key)
        if member is None:
            continue
        for index, (back, reason) in enumerate(events):
            day = today - timedelta(days=back)
            moment = _when(plan, key, day, time(11, 20))
            services.award(
                member, reason=reason, key=f"{_prefix(reason)}:demo{index}:{member.pk}", at=moment
            )
    for key, first, last, every, right in DAILY:
        member = people.get(key)
        if member is None:
            continue
        for number, back in enumerate(range(first, last - 1, -every)):
            day = today - timedelta(days=back)
            correct = number % 4 < right
            services.award(
                member,
                reason=PointsEntry.Reason.DAILY,
                key=f"daily:demo-{member.pk}-{day.isoformat()}",
                points=rules.points_for(settings, "daily" if correct else "daily_tried"),
                at=_when(plan, key, day, time(9, 40)),
            )
    for key, length in STREAKS.items():
        member = people.get(key)
        if member is None:
            continue
        for back in range(length - 1, -1, -1):
            services.touch_streak(member, today - timedelta(days=back))


def _prefix(reason: str) -> str:
    return "quiz-perfect" if reason == "quiz_perfect" else reason


def _when(plan: Plan, key: str, day: date, clock: time) -> datetime:
    """A moment of `day` while `key` is at work (their shift, or the branch's hours), never in
    the future."""
    moment = plan.at_work(key, day, plan.at(day, clock))
    return min(moment, plan.now - timedelta(minutes=20))


# Thanks between colleagues ------------------------------------------------------------------


def _kudos(plan: Plan, people: dict, now: datetime) -> None:
    today = plan.today
    for back, giver_key, receiver_key, badge, message, hour in KUDOS:
        giver, receiver = people.get(giver_key), people.get(receiver_key)
        if giver is None or receiver is None:
            continue
        day = today - timedelta(days=back)
        moment = _when(plan, giver_key, day, time(hour, 15))
        with demo_time.moment(moment):
            services.send_kudos(giver, to=receiver, badge=badge, message=message)


# Badges, levels, and who was told -------------------------------------------------------------


def _story_badges(company, people: dict, now: datetime) -> None:
    """Madina is the cold-chain expert (learning's answers make her so when they are there; the
    story keeps it when they aren't)."""
    from apps.knowledge.models import Topic
    from apps.knowledge.topics import PHARMACY_TOPICS

    madina = people.get("madina")
    if madina is None:
        return
    name = str(PHARMACY_TOPICS[0][0])
    topic = Topic.objects.filter(company=company, name=name).first()
    if topic is not None:
        progress.give(madina, "topic_expert", str(topic.pk), now=now - timedelta(days=6))


def _date_what_was_earned(company, now: datetime) -> None:
    """Each level on the day its points were reached, each badge on the day of what earned it."""
    entries: dict[int, list[PointsEntry]] = {}
    for entry in PointsEntry.objects.filter(company=company).order_by("at", "pk"):
        entries.setdefault(entry.membership_id, []).append(entry)
    for level in LevelUp.objects.filter(company=company):
        total = 0
        for entry in entries.get(level.membership_id, []):
            total += entry.points
            if total >= rules.LEVELS[level.number - 1]:
                LevelUp.objects.filter(pk=level.pk).update(reached_at=entry.at)
                break
    firsts = {
        "first_lesson": (PointsEntry.Reason.LESSON, 1),
        "first_quiz": (PointsEntry.Reason.QUIZ, 1),
        "perfect_score": (PointsEntry.Reason.QUIZ_PERFECT, 1),
        "course_finisher": (PointsEntry.Reason.COURSE, 1),
        "five_courses": (PointsEntry.Reason.COURSE, progress.COURSES_FOR_GOLD),
    }
    for award in BadgeAward.objects.filter(company=company, badge__in=list(firsts)):
        reason, count = firsts[award.badge]
        mine = [entry for entry in entries.get(award.membership_id, []) if entry.reason == reason]
        if len(mine) >= count:
            BadgeAward.objects.filter(pk=award.pk).update(awarded_at=mine[count - 1].at)
    for award in BadgeAward.objects.filter(company=company, badge__startswith="streak_"):
        milestone = [
            entry
            for entry in entries.get(award.membership_id, [])
            if entry.reason == PointsEntry.Reason.STREAK
            and entry.key.split(":")[3] == award.badge.removeprefix("streak_")
        ]
        if milestone:
            BadgeAward.objects.filter(pk=award.pk).update(awarded_at=milestone[-1].at)


def _mark_told(company, people: dict, now: datetime) -> None:
    """No bot messages for a demo; the app celebrates only Alisher's newest level and badge, and
    shows his thank-you of this morning on Home."""
    LevelUp.objects.filter(company=company).update(notified_at=now, seen_at=now)
    BadgeAward.objects.filter(company=company).update(notified_at=now, seen_at=now)
    Kudos.objects.filter(company=company).update(seen_at=now)
    worker = people.get("worker")
    if worker is None:
        return
    level = LevelUp.objects.filter(membership=worker).order_by("-number").first()
    if level is not None:
        LevelUp.objects.filter(pk=level.pk).update(seen_at=None)
    badge = (
        BadgeAward.objects.filter(membership=worker)
        .exclude(badge__in=[key for key, item in catalogue.CATALOGUE.items() if item.per_ref])
        .order_by("-awarded_at")
        .first()
    )
    if badge is not None:
        BadgeAward.objects.filter(pk=badge.pk).update(seen_at=None)
    start = datetime.combine(
        services.local_today(company, now), time.min, tzinfo=ZoneInfo(company.timezone)
    )
    Kudos.objects.filter(to_member=worker, created_at__gte=start).update(seen_at=None)
