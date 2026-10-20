from datetime import datetime
from zoneinfo import ZoneInfo

from celery import shared_task
from django.utils import timezone, translation

from apps.companies.models import Company
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm
from apps.notifications.tasks import send_telegram_message
from apps.notifications.telegram import BotName, serialize_markup
from apps.reports import bot_messages, kpis
from apps.reports.models import WeeklyReport
from apps.reports.periods import Period, bounds, in_window


@shared_task
def send_weekly_reports() -> None:
    post_weekly_reports(timezone.now())


def post_weekly_reports(now: datetime) -> int:
    """On Monday mornings, send last week's numbers to everyone who may see reports."""
    sent = 0
    for company in Company.objects.filter(is_active=True):
        local = timezone.localtime(now, ZoneInfo(company.timezone))
        if local.weekday() != 0 or not in_window(local, company.morning_report_at):
            continue
        start, end = bounds(Period.LAST_WEEK, local.date())
        report = None
        readers = (
            members_with_perm(company, Perm.REPORTS_VIEW)
            .filter(onboarded_at__isnull=False, user__telegram_id__isnull=False)
            .select_related("user")
        )
        for reader in readers:
            report = report or kpis.team(company, start, end, now)
            if report.totals.total == 0:
                break  # a quiet week: nothing to report
            # The unique row is the claim: a second run that gets here skips it.
            _, claimed = WeeklyReport.objects.get_or_create(membership=reader, week_start=start)
            if not claimed:
                continue
            with translation.override(reader.user.language):
                text, markup = bot_messages.weekly(report)
            send_telegram_message.delay(
                BotName.EMPLOYEE, reader.user.telegram_id, text, serialize_markup(markup)
            )
            sent += 1
    return sent
