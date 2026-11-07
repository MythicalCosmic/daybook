"""Celery tasks of recognition, queued with `transaction.on_commit` (default queue).

Thin wrappers: services import this module to queue jobs, so it never imports `services` at
module level; the work itself lives in plain modules both can import.
"""

from __future__ import annotations

import logging
import time

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

NIGHT_HOURS = range(0, 6)  # the company's small hours: the sweep and the monthly top three


@shared_task
def check_member(member_id: int) -> int:
    """The levels and badges new points earned (after an award); tells the person, batched."""
    from apps.members.models import Membership
    from apps.recognition import notify, progress

    cache.delete(f"recognition:check:{member_id}")
    member = Membership.objects.select_related("company").filter(pk=member_id).first()
    if member is None:
        return 0
    levels, badges = progress.check(member)
    if levels or badges:
        notify.schedule_notices(member_id)
    return len(levels) + len(badges)


@shared_task
def send_notices(member_id: int, after_quiet: bool = False) -> bool:
    """One message about everything new (`notify.schedule_notices` queues it)."""
    from apps.members.models import Membership
    from apps.recognition import notify

    cache.delete(notify._pending_key(member_id))
    member = Membership.objects.select_related("company").filter(pk=member_id).first()
    if member is None:
        return False
    if not after_quiet:
        until = notify.quiet_until(member, timezone.now())
        if until is not None:
            wait = max(60, int((until - timezone.now()).total_seconds()))
            send_notices.apply_async((member_id,), {"after_quiet": True}, countdown=wait)
            return False
    cache.set(notify._last_key(member_id), time.time(), timeout=notify.NOTICE_GAP_SECONDS * 2)
    return notify.achievements(member_id)


@shared_task
def kudos_sent(kudos_id: int) -> None:
    """The receiver hears about their thanks; linked groups see it when the company wants."""
    from apps.recognition import groups, notify

    notify.kudos(kudos_id)
    groups.post_kudos(kudos_id)


def _companies():
    from apps.companies.models import Company, Feature

    return Company.objects.filter(features__contains=[Feature.RECOGNITION], is_active=True)


@shared_task
def task_points() -> int:
    """Hourly: `task` points for the last two days' work done on time (idempotent, so a missed
    run catches up)."""
    from datetime import timedelta

    from apps.recognition import services

    made = 0
    for company in _companies():
        today = services.local_today(company)
        for back in (1, 2):
            try:
                made += services.award_task_points(company, today - timedelta(days=back))
            except Exception:
                logger.exception("Task points failed for company %s", company.pk)
    return made


@shared_task
def nightly() -> int:
    """Hourly, working only in each company's small hours, once a night: the badge sweep (and
    "on time all week" on Mondays), and the monthly top three in the first days of a month."""
    from apps.recognition import services

    found = 0
    now = timezone.now()
    for company in _companies():
        local = timezone.localtime(now, services.ZoneInfo(company.timezone))
        if local.hour not in NIGHT_HOURS:
            continue
        if not cache.add(f"recognition:sweep:{company.pk}:{local.date()}", 1, timeout=26 * 3600):
            continue
        try:
            found += services.sweep(company, now=now)
        except Exception:
            logger.exception("Recognition sweep failed for company %s", company.pk)
    return found
