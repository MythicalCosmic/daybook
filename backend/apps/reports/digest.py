"""The morning digest: everyone working today gets their open tasks from the bot.

When it comes (audit X-9, research R1 N7, R2 T52):
- someone on the attendance roster gets it 15 minutes before their shift starts, so the night
  pharmacist hears at 19:45 rather than at 09:00, after her shift; on a rostered day off,
  nothing;
- everyone else at the company's morning time, or 30 minutes before their first task of the
  day when that's earlier (never before 07:00).

The greeting is "good morning" for a shift that starts before noon and a plain "tasks for your
shift" otherwise. Sends are spread at about 25 a second, under Telegram's limit.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from aiogram import html
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from django.conf import settings
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.companies.models import Company
from apps.members.bot_messages import BotMessage, miniapp_url
from apps.members.models import Membership
from apps.notifications.tasks import send_telegram_message
from apps.notifications.telegram import BotName, serialize_markup
from apps.reports.models import MorningDigest
from apps.reports.periods import REPORT_WINDOW
from apps.tasks.bot_messages import list_button, task_button
from apps.tasks.models import Task
from apps.timeoff.queries import is_holiday, members_off

# Buttons in the digest; the rest are a tap away in the full list.
DIGEST_LIMIT = 8
SHIFT_LEAD = timedelta(minutes=15)
FIRST_TASK_LEAD = timedelta(minutes=30)
EARLIEST = time(7, 0)
NOON = time(12, 0)
SENDS_PER_SECOND = 25


def post_morning_digests(now: datetime) -> int:
    """Send the digests that are due; return how many went out."""
    sent = 0
    companies = Company.objects.filter(is_active=True, morning_digest=True)
    for company in companies:
        local = timezone.localtime(now, ZoneInfo(company.timezone))
        if is_holiday(company, local.date()):
            continue
        sent += _post_for(company, local.date(), now, sent)
    return sent


def _post_for(company: Company, day: date, now: datetime, already_sent: int) -> int:
    already = MorningDigest.objects.filter(day=day).values("membership")
    people = list(
        Membership.objects.for_company(company)
        .filter(
            status=Membership.Status.APPROVED,
            onboarded_at__isnull=False,
            user__telegram_id__isnull=False,
            user__employee_bot_blocked_at__isnull=True,
        )
        .exclude(pk__in=members_off(company, day))
        .exclude(pk__in=already)
        .select_related("user", "company")
    )
    if not people:
        return 0
    rostered, shifts = _shifts(company, day, people)
    day_start, day_end = _bounds(company, day)
    morning_at = datetime.combine(day, company.morning_report_at, tzinfo=day_start.tzinfo)
    sent = 0
    for person in people:
        shift = shifts.get(person.pk)
        until = day_end
        if person.pk in rostered:
            if shift is None:
                continue  # a rostered day off
            send_at = shift[0] - SHIFT_LEAD
            until = max(day_end, shift[1])
        else:
            send_at = _send_time(person, morning_at, day_start, day_end)
        if not send_at <= now < send_at + REPORT_WINDOW:
            continue
        # The unique row is the claim: a second run that gets here skips the person.
        _, claimed = MorningDigest.objects.get_or_create(membership=person, day=day)
        if not claimed:
            continue
        tasks = list(
            Task.objects.filter(assignee=person, status__in=Task.OPEN_STATUSES, due_at__lt=until)
            .select_related("company", "project")
            .order_by("due_at")
        )
        if not tasks:
            continue  # nothing open today: no need to say good morning about it
        starts = timezone.localtime(shift[0], day_start.tzinfo) if shift else None
        with translation.override(person.user.language):
            text, markup = morning(person, tasks, day, now, shift_start=starts)
        send_telegram_message.apply_async(
            (BotName.EMPLOYEE, person.user.telegram_id, text, serialize_markup(markup)),
            countdown=(already_sent + sent) // SENDS_PER_SECOND,
        )
        sent += 1
    return sent


def _send_time(person: Membership, morning: datetime, start: datetime, end: datetime) -> datetime:
    """The morning time, or half an hour before the person's first task today if that's earlier,
    but not before 07:00."""
    first = (
        Task.objects.filter(
            assignee=person,
            status__in=Task.OPEN_STATUSES,
            due_at__gte=start,
            due_at__lt=end,
        )
        .order_by("due_at")
        .values_list("due_at", flat=True)
        .first()
    )
    if first is None:
        return morning
    earliest = datetime.combine(start.date(), EARLIEST, tzinfo=start.tzinfo)
    return max(earliest, min(morning, first - FIRST_TASK_LEAD))


def _shifts(
    company: Company, day: date, people: list[Membership]
) -> tuple[set[int], dict[int, tuple[datetime, datetime]]]:
    """Who is on the attendance roster around `day`, and each one's first shift that day."""
    if not company.has_feature("attendance"):
        return set(), {}
    from apps.attendance.models import WorkShift

    ids = [person.pk for person in people]
    around = WorkShift.objects.working().filter(
        membership_id__in=ids, date__range=(day - timedelta(days=6), day + timedelta(days=6))
    )
    rostered = set(around.values_list("membership_id", flat=True))
    shifts: dict[int, tuple[datetime, datetime]] = {}
    for member_id, starts, ends in (
        around.filter(date=day)
        .order_by("starts_at")
        .values_list("membership_id", "starts_at", "ends_at")
    ):
        shifts.setdefault(member_id, (starts, ends))
    return rostered, shifts


def morning(
    person: Membership,
    tasks: list[Task],
    day: date,
    now: datetime,
    *,
    shift_start: datetime | None = None,
) -> BotMessage:
    day_start, _day_end = _bounds(person.company, day)
    overdue = sum(task.due_at < day_start for task in tasks)
    values = {
        "name": html.quote(person.first_name or str(person)),
        "count": len(tasks) - overdue,
    }
    if shift_start is not None and shift_start.time() >= NOON:
        first = _("%(name)s, tasks for your shift: %(count)d.") % values
    else:
        first = _("Good morning, %(name)s! Tasks for today: %(count)d.") % values
    lines = [f"<b>{first}</b>"]  # a bold first line, no emoji
    if overdue:
        lines.append(_("Still open from earlier days: %(count)d.") % {"count": overdue})
    lines.append(_("Tap a task to open it."))
    rows = [[task_button(task, now)] for task in tasks[:DIGEST_LIMIT]]
    last = []
    if len(tasks) > DIGEST_LIMIT:
        last.append(list_button(_("All my tasks")))
    if settings.EMPLOYEE_MINIAPP_URL.startswith("https://"):
        url = miniapp_url("tasks")
        last.append(InlineKeyboardButton(text=_("Open the app"), web_app=WebAppInfo(url=url)))
    if last:
        rows.append(last)
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def _bounds(company: Company, day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=ZoneInfo(company.timezone))
    return start, start + timedelta(days=1)
