"""The operational scan and the evening post (docs/PLAN-OWNER.md §10.1), run by Celery beat.

Branch hours (`Branch.opens_at`, `closes_at`, `open_weekdays`) and holidays decide only these
alerts (§2.7). Each check is cheap and idempotent; every alert carries a dedupe key, so running
the scan every 5 minutes sends each alert once.

- **Branch not opened**: an open day, `late_open_minutes` past `opens_at` (for two hours), no
  shift opened that business day, and, when the attendance module registered its branch facts,
  nobody checked in either.
- **Shift not closed**: still open `close_alert_minutes` after the branch closed (or 16 hours
  after opening, for a branch without hours): managers and the cashier hear.
- **Handover unconfirmed** for `handover_confirm_hours`.
- **Cash over the limit** after closing (`Branch.cash_limit`).
"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone, translation

from apps.companies.models import Branch, Company, Feature
from apps.console import registry
from apps.groups.models import GroupEvent
from apps.groups.services import broadcast
from apps.sales import alerts, cash, rollup
from apps.sales import bot_messages as msg
from apps.sales.conf import get_settings
from apps.sales.days import business_day, local
from apps.sales.models import (
    CashMovement,
    CashShift,
    Register,
    Sale,
    SalePayment,
    SalesSettings,
    ShiftPayment,
)
from apps.timeoff.models import Holiday

logger = logging.getLogger(__name__)

NOT_OPENED_WINDOW = timedelta(hours=2)
NO_HOURS_LIMIT = timedelta(hours=16)
EVENING_DELAY = timedelta(minutes=30)
DEFAULT_CLOSE = (22, 0)


def sales_companies():
    return Company.objects.filter(is_active=True, features__contains=[Feature.SALES])


def scan_all(now: datetime | None = None) -> int:
    sent = 0
    for company in sales_companies():
        try:
            sent += scan_company(company, now or timezone.now())
        except Exception:
            logger.exception("sales scan failed for company %s", company.pk)
    return sent


def scan_company(company, now: datetime) -> int:
    settings = get_settings(company)
    at = local(company, now)
    today = business_day(company, now, ends_at=settings.business_day_ends_at)
    sent = 0
    branches = list(Branch.objects.filter(company=company, is_active=True))
    holiday = Holiday.objects.filter(company=company, date=at.date()).exists()
    opened = set(
        CashShift.objects.filter(company=company, business_day=today).values_list(
            "branch_id", flat=True
        )
    )
    checked_in = _checked_in(company, at.date(), now, [b.pk for b in branches])
    for branch in branches:
        quiet = branch.pk in opened or branch.pk in checked_in
        if not quiet and _not_opened(branch, at, holiday, settings):
            late = int((at - _at(at, branch.opens_at)).total_seconds() // 60)
            sent += alerts.branch_not_opened(
                branch, at.date(), branch.opens_at.strftime("%H:%M"), late
            )
        if branch.cash_limit and _after_closing_today(branch, at):
            amount = cash_in_branch(branch)
            if amount > branch.cash_limit:
                sent += alerts.cash_over_limit(branch, at.date(), amount)
    sent += _open_too_long(company, settings, now)
    sent += _late_handovers(company, settings, now)
    return sent


def _checked_in(company, day: date, now: datetime, branch_ids: list[int]) -> set[int]:
    """Branches where someone checked in today, from attendance's branch facts when that
    module registered them (and only then)."""
    provider = registry.BRANCH_FACTS.get("attendance")
    if provider is None or not company.has_feature(Feature.ATTENDANCE) or not branch_ids:
        return set()
    try:
        facts = provider.facts(company, day, now, branch_ids) or {}
    except Exception:
        logger.exception("attendance branch facts failed; ignoring them")
        return set()
    return {branch_id for branch_id, row in facts.items() if row.get("first_check_in")}


def _at(at: datetime, clock) -> datetime:
    return at.replace(hour=clock.hour, minute=clock.minute, second=0, microsecond=0)


def _not_opened(branch: Branch, at: datetime, holiday: bool, settings: SalesSettings) -> bool:
    if branch.opens_at is None or holiday or at.weekday() not in branch.open_weekdays:
        return False
    due = _at(at, branch.opens_at) + timedelta(minutes=settings.late_open_minutes)
    if not (due <= at < due + NOT_OPENED_WINDOW):
        return False
    if branch.closes_at is not None and branch.closes_at > branch.opens_at:
        return at < _at(at, branch.closes_at)
    return True


def _after_closing_today(branch: Branch, at: datetime) -> bool:
    if branch.closes_at is None:
        return False
    if branch.opens_at is not None and branch.closes_at < branch.opens_at:
        return False  # open past midnight: no clean "after closing" moment in this calendar day
    return at >= _at(at, branch.closes_at)


def _closing_moment(shift: CashShift) -> datetime | None:
    branch = shift.branch
    if branch.closes_at is None:
        return None
    opened = local(shift.company, shift.opened_at)
    closing = opened.replace(
        year=shift.business_day.year,
        month=shift.business_day.month,
        day=shift.business_day.day,
        hour=branch.closes_at.hour,
        minute=branch.closes_at.minute,
        second=0,
        microsecond=0,
    )
    if branch.opens_at is not None and branch.closes_at < branch.opens_at:
        closing += timedelta(days=1)
    return closing


def _open_too_long(company, settings: SalesSettings, now: datetime) -> int:
    sent = 0
    for shift in CashShift.objects.filter(
        company=company, status=CashShift.Status.OPEN
    ).select_related("branch", "cashier__user", "company"):
        closing = _closing_moment(shift)
        if closing is None:
            if now - shift.opened_at >= NO_HOURS_LIMIT:
                sent += alerts.shift_not_closed(shift, "—")
            continue
        if now >= closing + timedelta(minutes=settings.close_alert_minutes):
            sent += alerts.shift_not_closed(shift, shift.branch.closes_at.strftime("%H:%M"))
    return sent


def _late_handovers(company, settings: SalesSettings, now: datetime) -> int:
    hours = settings.handover_confirm_hours
    if not hours:
        return 0
    late = CashMovement.objects.filter(
        cash.in_transit_filter(), company=company, created_at__lte=now - timedelta(hours=hours)
    ).values_list("pk", flat=True)
    sent = 0
    for pk in late:
        before = alerts.already_sent(company.pk, f"sales.handover_late:{pk}")
        alerts.handover_late(pk, hours)
        sent += 0 if before else 1
    return sent


def cash_in_branch(branch: Branch) -> Decimal:
    """Σ the branch's tills now + its safe's balance."""
    from apps.finance.models import MoneyAccount

    open_shifts = {
        shift.register_id: shift
        for shift in CashShift.objects.filter(branch=branch, status=CashShift.Status.OPEN)
    }
    total = Decimal(0)
    for register in Register.objects.filter(branch=branch, is_active=True).select_related(
        "cash_account"
    ):
        total += cash.till_now(register, open_shifts.get(register.pk))
    safe = MoneyAccount.objects.filter(
        company_id=branch.company_id, branch=branch, kind=MoneyAccount.Kind.SAFE, is_active=True
    ).aggregate(total=Sum("balance"))["total"]
    return total + (safe or Decimal(0))


# DailySales safety net --------------------------------------------------------------------


def rollup_recent(now: datetime | None = None) -> int:
    count = 0
    for company in sales_companies():
        today = business_day(company, now)
        count += rollup.rebuild_range(company, today - timedelta(days=2), today)
    return count


# Evening post -----------------------------------------------------------------------------


def post_evening_all(now: datetime | None = None) -> int:
    posted = 0
    for company in sales_companies():
        try:
            posted += post_evening(company, now or timezone.now())
        except Exception:
            logger.exception("sales evening post failed for company %s", company.pk)
    return posted


def _last_close(company, at: datetime) -> datetime:
    closes = [
        branch.closes_at
        for branch in Branch.objects.filter(company=company, is_active=True)
        if branch.closes_at is not None
        and (branch.opens_at is None or branch.closes_at > branch.opens_at)
    ]
    if closes:
        latest = max(closes)
        return at.replace(hour=latest.hour, minute=latest.minute, second=0, microsecond=0)
    return at.replace(hour=DEFAULT_CLOSE[0], minute=DEFAULT_CLOSE[1], second=0, microsecond=0)


def day_by_branch(company, day: date) -> list[tuple[Branch, Decimal, int]]:
    """Net and receipts per branch for one business day, straight from shifts and receipts."""
    rows = []
    for branch in Branch.objects.filter(company=company, is_active=True).order_by("order", "name"):
        shifts = CashShift.objects.filter(branch=branch, business_day=day).exclude(
            status=CashShift.Status.OPEN
        )
        totals = ShiftPayment.objects.filter(shift__in=shifts).aggregate(
            sales=Sum("sales"), refunds=Sum("refunds")
        )
        net = (totals["sales"] or Decimal(0)) - (totals["refunds"] or Decimal(0))
        receipts = shifts.aggregate(n=Sum("receipts"))["n"] or 0
        loose = Sale.objects.filter(
            branch=branch, business_day=day, shift__isnull=True, voided_at__isnull=True
        )
        for kind, amount in SalePayment.objects.filter(sale__in=loose).values_list(
            "sale__kind", "amount"
        ):
            net += -amount if kind == Sale.Kind.REFUND else amount
        receipts += loose.filter(kind=Sale.Kind.SALE).count()
        if net or receipts:
            rows.append((branch, net, receipts))
    return rows


def post_evening(company, now: datetime) -> int:
    settings = get_settings(company)
    at = local(company, now)
    day = business_day(company, now, ends_at=settings.business_day_ends_at)
    if settings.evening_posted_on == day or at < _last_close(company, at) + EVENING_DELAY:
        return 0
    if at.date() != day:
        return 0  # past midnight the evening is over; never post yesterday at 01:00
    with transaction.atomic():
        locked = SalesSettings.objects.select_for_update().get(pk=settings.pk)
        if locked.evening_posted_on == day:
            return 0
        locked.evening_posted_on = day
        locked.save(update_fields=["evening_posted_on", "updated_at"])
        rows = day_by_branch(company, day)
        if not rows:
            return 0
        total = sum((net for _b, net, _r in rows), Decimal(0))
        week_ago = sum(
            (net for _b, net, _r in day_by_branch(company, day - timedelta(days=7))), Decimal(0)
        )
        change = None
        if week_ago:
            percent = (total - week_ago) / week_ago * 100
            change = f"{percent:+.0f}%"
        with translation.override(company.default_language):
            text = msg.group_evening(
                day.strftime("%d.%m.%Y"),
                [(branch.name, net, receipts) for branch, net, receipts in rows],
                total,
                change,
            )
        broadcast(company.pk, GroupEvent.SALES, text)
    return 1
