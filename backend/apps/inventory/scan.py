"""The daily look at stock (docs/PLAN-OWNER.md §14.6.2), for each company with the stock module.

`daily_scan` runs every hour and acts once per company day, from 06:00 company time:

- expiry: every batch on hand that reached a step of `expiry_steps` (default 90, 60, 30 days)
  or expired is told once per step, as one digest per branch to the stock.manage holders who
  see it (with the mandatory medicines missing there);
- on the 1st of the month, one "Expiry shelf check" task per branch holding batches that expire
  within the first step, with a checklist of up to 30 of them (`create_system_task`);
- the mandatory assortment: missing items in the digest, and a defektura row each;
- destruction dates of approved write-offs: 10 days before and on the day;
- the controlled register: a reminder on the 1st to close last month, an alert after the close
  day while it isn't closed, and every unreported difference again each day;
- prescriptions past their keeping time lose their photo and prescriber.

Each notice is deduplicated, so a second run on the same day sends nothing new.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.companies.models import Company, Feature
from apps.inventory import conf, engine, notify, prescriptions, queries, register
from apps.inventory.models import BatchStock, MissingRequest, WriteOff

SCAN_HOUR = 6
CHECKLIST_MAX = 30


def daily_scan(now: datetime | None = None) -> int:
    done = 0
    for company in Company.objects.filter(features__contains=[Feature.STOCK], is_active=True):
        local = engine.local_now(company, now)
        if local.hour < SCAN_HOUR:
            continue
        settings = conf.get_settings(company)
        if settings.scanned_on == local.date():
            continue
        scan_company(company, local.date())
        type(settings).objects.filter(pk=settings.pk).update(scanned_on=local.date())
        done += 1
    return done


def scan_company(company, today: date) -> dict:
    settings = conf.get_settings(company)
    result = {
        "digests": expiry_digests(company, today, settings),
        "shelf_checks": 0,
        "destroy": destruction_reminders(company, today),
        "controlled": controlled_reminders(company, today, settings),
    }
    if today.day == 1:
        result["shelf_checks"] = shelf_checks(company, today, settings)
    prescriptions.clear_past_keeping(company, today)
    return result


def _steps(settings) -> list[int]:
    return sorted({int(step) for step in (settings.expiry_steps or []) if int(step) > 0} | {0})


def reached_step(days_left: int, steps: list[int]) -> int | None:
    """The tightest step a batch has reached: 0 once it expired, else the smallest step not
    below its days left."""
    if days_left < 0:
        return 0
    reached = [step for step in steps if step > 0 and days_left <= step]
    return min(reached) if reached else None


@transaction.atomic
def expiry_digests(company, today: date, settings) -> int:
    steps = _steps(settings)
    rows: dict[int, list[dict]] = defaultdict(list)
    branches = {}
    stocks = (
        BatchStock.objects.select_for_update(of=("self",))
        .filter(batch__company=company, quantity__gt=0, branch__is_active=True)
        .select_related("batch__product", "branch")
        .order_by("batch__expires_on", "pk")
    )
    for stock in stocks:
        batch = stock.batch
        step = reached_step((batch.expires_on - today).days, steps)
        if step is None or (stock.notified_step is not None and stock.notified_step <= step):
            continue
        stock.notified_step = step
        stock.save(update_fields=["notified_step"])
        branches[stock.branch_id] = stock.branch
        rows[stock.branch_id].append(
            {
                "kind": "batch",
                "step": step,
                "product": batch.product.name,
                "series": batch.series,
                "expires_on": batch.expires_on,
                "value": engine.retail_value_of(batch, stock.quantity),
            }
        )
    for row in queries.mandatory_missing(company, branch_ids=None, day=today):
        branch_id = row["branch_id"]
        if branch_id not in branches:
            branches[branch_id] = company.branches.get(pk=branch_id)
        rows[branch_id].append({"kind": "missing", "product": row["product"]})
        _mandatory_request(company, branch_id, row["product_id"], row["product"])
    sent = 0
    for branch_id, found in rows.items():
        branch = branches[branch_id]
        sent += notify.expiry_digest(company, branch, found, today)
    return sent


def _mandatory_request(company, branch_id: int, product_id: int, name: str) -> None:
    """With the defektura list, a missing mandatory medicine opens one row (until it is
    ordered, arrives or is cancelled)."""
    open_ = MissingRequest.objects.filter(
        company=company,
        branch_id=branch_id,
        product_id=product_id,
        source=MissingRequest.Source.MANDATORY,
        status__in=(MissingRequest.Status.OPEN, MissingRequest.Status.ORDERED),
    )
    if not open_.exists():
        MissingRequest.objects.create(
            company=company,
            branch_id=branch_id,
            product_id=product_id,
            name=name,
            source=MissingRequest.Source.MANDATORY,
        )


def shelf_checks(company, today: date, settings) -> int:
    """On the 1st: one "Expiry shelf check" task per branch, once a month."""
    from apps.inventory.services import assignee_for
    from apps.tasks.services import create_system_task

    month = today.replace(day=1)
    with transaction.atomic():
        row = conf.locked_settings(company)
        if row.shelf_check_month == month:
            return 0
        row.shelf_check_month = month
        row.save(update_fields=["shelf_check_month", "updated_at"])
        first = max(_steps(settings)) or 90
        made = 0
        zone = engine.zone_of(company)
        due = datetime.combine(today + timedelta(days=2), time(18, 0), tzinfo=zone)
        for branch in company.branches.filter(is_active=True).order_by("order", "pk"):
            stocks = list(
                queries.stock_rows(company, branch_ids=[branch.pk])
                .filter(batch__expires_on__lte=today + timedelta(days=first))
                .order_by("batch__expires_on", "pk")[:CHECKLIST_MAX]
            )
            if not stocks:
                continue
            assignee = assignee_for(branch)
            if assignee is None:
                continue
            checklist = [
                _("%(product)s, series %(series)s, expires %(day)s")
                % {
                    "product": stock.batch.product.name,
                    "series": stock.batch.series,
                    "day": stock.batch.expires_on.strftime("%d.%m.%Y"),
                }
                for stock in stocks
            ]
            create_system_task(
                company,
                assignee=assignee,
                title=_("Expiry shelf check: %(branch)s") % {"branch": branch.name},
                due_at=due,
                description=_(
                    "Find each series on the shelf, check its expiry date, and move what expires "
                    "soon to the front or to the quarantine zone. Expired goods are proposed for "
                    "write-off in the app."
                ),
                checklist=checklist,
            )
            made += 1
    return made


def destruction_reminders(company, today: date) -> int:
    sent = 0
    rows = (
        WriteOff.objects.for_company(company)
        .filter(status=WriteOff.Status.APPROVED, destroy_by__isnull=False)
        .select_related("company", "branch")
    )
    for writeoff in rows:
        left = (writeoff.destroy_by - today).days
        if left <= 0:
            sent += notify.destroy_due(writeoff, "due", today)
        elif left <= 10:
            sent += notify.destroy_due(writeoff, "soon", today)
    return sent


def controlled_reminders(company, today: date, settings) -> int:
    sent = 0
    last = register.previous_month(today)
    branches = company.branches.filter(is_active=True, controlled_licence=True)
    for branch in branches:
        if register.is_closed(branch, last):
            continue
        if today.day == 1:
            sent += notify.controlled_close_due(company, branch, last, "remind", today)
        elif today.day > settings.controlled_close_day:
            sent += notify.controlled_close_due(company, branch, last, "late", today)
    for period in register.unreported(company):
        sent += notify.controlled_mismatch(period, today, settings.controlled_report_days)
    return sent


# The other jobs ---------------------------------------------------------------------------------


def remind_unposted(now: datetime | None = None) -> int:
    """Receipts waiting more than 2 days: their posters hear once more."""
    from apps.inventory.models import GoodsReceipt

    sent = 0
    limit = (now or timezone.now()) - timedelta(days=2)
    rows = GoodsReceipt.objects.filter(
        company__features__contains=[Feature.STOCK],
        company__is_active=True,
        status__in=(GoodsReceipt.Status.SUBMITTED, GoodsReceipt.Status.DRAFT),
        created_at__lt=limit,
    )
    for receipt in rows.only("pk"):
        sent += notify.receipt_waiting(receipt.pk, reminder=True)
    return sent


def recompute_low_stock() -> int:
    """Levels below their minimum get (or lose) their low flag; the badge refreshes."""
    from django.db.models import F

    from apps.console import pulse
    from apps.inventory.models import StockLevel

    changed = 0
    for company in Company.objects.filter(features__contains=[Feature.STOCK], is_active=True):
        rows = StockLevel.objects.filter(product__company=company, min_qty__isnull=False)
        now = timezone.now()
        newly = rows.filter(quantity__lt=F("min_qty"), low_since__isnull=True).update(low_since=now)
        cleared = rows.filter(quantity__gte=F("min_qty"), low_since__isnull=False).update(
            low_since=None
        )
        if newly or cleared:
            pulse.bump(company.pk, "inventory.low")
            changed += newly + cleared
    return changed
