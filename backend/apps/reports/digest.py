"""The morning digest: everyone working today gets their open tasks from the bot."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardMarkup
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.companies.models import Company
from apps.members.bot_messages import BotMessage
from apps.members.models import Membership
from apps.notifications.tasks import send_telegram_message
from apps.notifications.telegram import BotName, serialize_markup
from apps.reports.models import MorningDigest
from apps.reports.periods import in_window
from apps.tasks.bot_messages import list_button, task_button
from apps.tasks.models import Task
from apps.timeoff.queries import is_holiday, members_off

# Buttons in the digest; the rest are a tap away in the full list.
DIGEST_LIMIT = 8


def post_morning_digests(now: datetime) -> int:
    """Send the digests that are due; return how many went out."""
    sent = 0
    companies = Company.objects.filter(is_active=True, morning_digest=True)
    for company in companies:
        local = timezone.localtime(now, ZoneInfo(company.timezone))
        if not in_window(local, company.morning_report_at) or is_holiday(company, local.date()):
            continue
        sent += _post_for(company, local.date(), now)
    return sent


def _post_for(company: Company, day: date, now: datetime) -> int:
    already = MorningDigest.objects.filter(day=day).values("membership")
    people = (
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
    _, day_end = _bounds(company, day)
    sent = 0
    for person in people:
        # The unique row is the claim: a second run that gets here skips the person.
        _, claimed = MorningDigest.objects.get_or_create(membership=person, day=day)
        if not claimed:
            continue
        tasks = list(
            Task.objects.filter(assignee=person, status__in=Task.OPEN_STATUSES, due_at__lt=day_end)
            .select_related("company")
            .order_by("due_at")
        )
        if not tasks:
            continue  # nothing open today: no need to say good morning about it
        with translation.override(person.user.language):
            text, markup = morning(person, tasks, day, now)
        send_telegram_message.delay(
            BotName.EMPLOYEE, person.user.telegram_id, text, serialize_markup(markup)
        )
        sent += 1
    return sent


def morning(person: Membership, tasks: list[Task], day: date, now: datetime) -> BotMessage:
    day_start, _day_end = _bounds(person.company, day)
    overdue = sum(task.due_at < day_start for task in tasks)
    lines = [
        _("🌅 Good morning, %(name)s! Tasks for today: %(count)d.")
        % {"name": person.first_name or str(person), "count": len(tasks) - overdue}
    ]
    if overdue:
        lines.append(_("⚠️ Still open from earlier days: %(count)d.") % {"count": overdue})
    lines.append(_("Tap a task to open it."))
    rows = [[task_button(task, now)] for task in tasks[:DIGEST_LIMIT]]
    if len(tasks) > DIGEST_LIMIT:
        rows.append([list_button(_("📋 All my tasks"))])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def _bounds(company: Company, day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=ZoneInfo(company.timezone))
    return start, start + timedelta(days=1)
