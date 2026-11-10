"""Partners and their dividends (v11): who owns how much of the business, profit shared out by
those shares, and each partner's part of a period's profit.

- `set_partners(company, by=, effective_on=, rows=)` replaces the partners from a day on: the
  rows in force end the day before (or are replaced when they start that same day) and the new
  ones start then. Their shares add up to exactly 100 %. A partner is a member of the company
  or just a name.
- A dividend round (`create_dividend`) is made for a period with an amount (suggested by
  `suggest`: the period's net profit, at most what is safe to take out today), split by the
  shares in force on the period's last day (what is left from rounding goes to the biggest
  share). Each line is paid as an owner draw from a business account (`pay_dividend`, ledger
  source `finance.dividend`); the round is paid once every line is. Voiding a line's draw (here
  or in the ledger) makes the line unpaid again.
- `profit_share(company, start, end)` gives each partner's part of the period's net profit, by
  the days they held each share, with the dividends paid to them for rounds in the period.

Contract for other packages: `partners_on(company, day)`, `profit_share(company, start, end)`,
`suggest(company, start, end)` and `dividends(company)`; money as Decimal.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.core.money import quantize
from apps.finance import conf, owner_draw, queries, services
from apps.finance.audit_actions import FinanceAction
from apps.finance.models import (
    Dividend,
    DividendLine,
    FinanceSettings,
    MoneyAccount,
    Partner,
    Transaction,
)
from apps.finance.sources import Source
from apps.members.models import Membership

ZERO = Decimal(0)
HUNDRED = Decimal(100)
SHARE_STEP = Decimal("0.01")
SOURCE = "finance.dividend"
MAX_PARTNERS = 20


# Partners ------------------------------------------------------------------------------------


def partners_on(company, day: date) -> list[Partner]:
    """The partners on `day`, the biggest share first."""
    return list(
        Partner.objects.for_company(company)
        .filter(starts_on__lte=day)
        .filter(Q(ends_on__isnull=True) | Q(ends_on__gte=day))
        .select_related("membership")
        .order_by("-share", "name", "pk")
    )


def current(company) -> list[Partner]:
    """The partners now in force (no end day)."""
    return list(
        Partner.objects.for_company(company)
        .filter(ends_on__isnull=True)
        .select_related("membership")
        .order_by("-share", "name", "pk")
    )


def identity(partner: Partner) -> str:
    """The same partner across share changes: their membership, or else their name."""
    if partner.membership_id is not None:
        return f"m{partner.membership_id}"
    return f"n:{partner.name.strip().casefold()}"


@transaction.atomic
def set_partners(company, *, by: Membership, effective_on: date, rows) -> list[Partner]:
    """Replace the partners from `effective_on` on. `rows`: dicts with `membership` (a
    Membership or None), `name` (required without a membership) and `share` (percent)."""
    services._need_actor(by)
    user = services._actor(company, by)
    # One change at a time per company (the settings row heads the finance lock order).
    FinanceSettings.objects.select_for_update().get(pk=conf.get_settings(company).pk)
    cleaned = _clean_rows(company, rows)
    in_force = list(
        Partner.objects.select_for_update().filter(company=company, ends_on__isnull=True)
    )
    latest = max((row.starts_on for row in in_force), default=None)
    if latest is not None and effective_on < latest:
        raise DomainError(
            _("The partners changed on %(date)s: a new change starts on that day or later.")
            % {"date": latest.strftime("%d.%m.%Y")}
        )
    for row in in_force:
        if row.starts_on == effective_on:
            if row.dividend_lines.exists():
                raise DomainError(
                    _(
                        "A dividend already uses the shares that start on %(date)s: pick a "
                        "later day."
                    )
                    % {"date": effective_on.strftime("%d.%m.%Y")}
                )
            row.delete()
        else:
            row.ends_on = effective_on - timedelta(days=1)
            row.save(update_fields=["ends_on", "updated_at"])
    made = [
        Partner.objects.create(
            company=company,
            membership=row["membership"],
            name=row["name"],
            share=row["share"],
            starts_on=effective_on,
            created_by=user,
        )
        for row in cleaned
    ]
    services._audit(
        FinanceAction.PARTNERS_SET,
        company,
        user,
        made[0],
        effective_on=effective_on.isoformat(),
        partners=[[row.name, str(row.share)] for row in made],
    )
    return made


def _clean_rows(company, rows) -> list[dict]:
    rows = list(rows or [])
    if not rows:
        raise DomainError(_("Add at least one partner."))
    if len(rows) > MAX_PARTNERS:
        raise DomainError(_("At most %(n)s partners.") % {"n": MAX_PARTNERS})
    cleaned = []
    seen = set()
    for row in rows:
        member = row.get("membership")
        if member is not None:
            services._same_company(company, member)
        name = (row.get("name") or "").strip()[:200] or (str(member) if member else "")
        if not name:
            raise DomainError(_("Give each partner a name or pick a person."))
        share = _share(row.get("share"))
        key = f"m{member.pk}" if member is not None else f"n:{name.casefold()}"
        if key in seen:
            raise DomainError(_("%(name)s is listed twice.") % {"name": name})
        seen.add(key)
        cleaned.append({"membership": member, "name": name, "share": share})
    total = sum((row["share"] for row in cleaned), ZERO)
    if total != HUNDRED:
        raise DomainError(
            _("The shares add up to %(total)s %%; they must make exactly 100 %%.")
            % {"total": _percent_text(total)}
        )
    return cleaned


def _share(value) -> Decimal:
    try:
        share = Decimal(str(value)).quantize(SHARE_STEP)
    except Exception:
        raise DomainError(_("Enter each share as a percentage.")) from None
    if not share.is_finite() or share <= 0 or share > HUNDRED:
        raise DomainError(_("A share is more than 0 and at most 100 %."))
    return share


def _percent_text(value: Decimal) -> str:
    return f"{value.normalize():f}"


# Profit share ----------------------------------------------------------------------------------


def profit_share(company, start: date, end: date) -> dict:
    """Each partner's part of the net profit from `start` to `end` (both included), by the
    days they held each share, and the dividends paid to them for rounds of the period."""
    if end < start:
        raise DomainError(_("The period ends before it starts."))
    profit = queries.totals(company, start, end, branch_ids=None)["profit"]
    days = (end - start).days + 1
    rows = (
        Partner.objects.for_company(company)
        .filter(starts_on__lte=end)
        .filter(Q(ends_on__isnull=True) | Q(ends_on__gte=start))
        .select_related("membership")
    )
    weighted: dict[str, Decimal] = defaultdict(lambda: ZERO)
    people: dict[str, Partner] = {}
    for row in rows.order_by("starts_on", "pk"):
        first, last = max(row.starts_on, start), min(row.ends_on or end, end)
        key = identity(row)
        weighted[key] += row.share * ((last - first).days + 1)
        people[key] = row  # the latest row names them
    paid: dict[str, Decimal] = defaultdict(lambda: ZERO)
    owed: dict[str, Decimal] = defaultdict(lambda: ZERO)
    lines = (
        DividendLine.objects.filter(
            dividend__company=company,
            dividend__period_start__gte=start,
            dividend__period_end__lte=end,
        )
        .exclude(dividend__status=Dividend.Status.CANCELLED)
        .select_related("partner", "transaction")
    )
    for line in lines:
        key = identity(line.partner)
        people.setdefault(key, line.partner)
        if line.is_paid:
            paid[key] += line.amount
        else:
            owed[key] += line.amount
    covered = ZERO
    result = []
    for key, partner in people.items():
        share = (weighted[key] / days).quantize(SHARE_STEP) if days else ZERO
        covered += weighted[key]
        result.append(
            {
                "key": key,
                "name": partner.name,
                "membership_id": partner.membership_id,
                "share": share,
                "profit": quantize(profit * weighted[key] / days / HUNDRED) if days else ZERO,
                "dividends_paid": quantize(paid[key]),
                "dividends_due": quantize(owed[key]),
            }
        )
    result.sort(key=lambda row: (-row["share"], row["name"]))
    unassigned = HUNDRED - (covered / days if days else ZERO)
    return {
        "from": start,
        "to": end,
        "currency": company.base_currency,
        "profit": quantize(profit),
        "partners": result,
        "unassigned_share": max(unassigned.quantize(SHARE_STEP), ZERO),
    }


# Dividends ------------------------------------------------------------------------------------


def dividends(company):
    """Every dividend round, the latest period first, with its lines and their draws."""
    return (
        Dividend.objects.for_company(company)
        .prefetch_related("lines__partner__membership", "lines__transaction__account")
        .order_by("-period_end", "-pk")
    )


def state(dividend: Dividend) -> str:
    """The round's status from its lines (a draw voided in the ledger unpays its line)."""
    if dividend.status == Dividend.Status.CANCELLED:
        return Dividend.Status.CANCELLED
    lines = list(dividend.lines.all())
    paid = sum(1 for line in lines if line.is_paid)
    if lines and paid == len(lines):
        return Dividend.Status.PAID
    if paid:
        return Dividend.Status.PARTLY_PAID
    return Dividend.Status.DRAFT


def suggest(company, start: date, end: date) -> dict:
    """What a round for the period could pay: its net profit less the rounds already made for
    it, at most what is safe to take out today; and how that splits by the shares on its last
    day."""
    if end < start:
        raise DomainError(_("The period ends before it starts."))
    profit = queries.totals(company, start, end, branch_ids=None)["profit"]
    made = sum(
        (
            row.amount
            for row in Dividend.objects.for_company(company)
            .exclude(status=Dividend.Status.CANCELLED)
            .filter(period_start__lte=end, period_end__gte=start)
        ),
        ZERO,
    )
    safe = owner_draw.safe_amount(company)["safe"]
    room = max(quantize(profit - made), ZERO)
    amount = owner_draw.round_down(min(room, safe), company.base_currency)
    partners = partners_on(company, end)
    return {
        "from": start,
        "to": end,
        "currency": company.base_currency,
        "profit": quantize(profit),
        "already": quantize(made),
        "safe": safe,
        "amount": amount,
        "limited_by": "safe" if safe < room else "profit",
        "split": [
            {
                "partner_id": partner.pk,
                "name": partner.name,
                "share": partner.share,
                "amount": part,
            }
            for partner, part in zip(partners, split(amount, partners), strict=True)
        ],
    }


def split(amount: Decimal, partners: list[Partner]) -> list[Decimal]:
    """`amount` by the partners' shares, to the tiyin, the rounding left over to the biggest."""
    if not partners:
        return []
    parts = [quantize(amount * partner.share / HUNDRED) for partner in partners]
    biggest = max(range(len(partners)), key=lambda index: (partners[index].share, -index))
    parts[biggest] += quantize(amount) - sum(parts, ZERO)
    return parts


@transaction.atomic
def create_dividend(
    company,
    *,
    by: Membership,
    period_start: date,
    period_end: date,
    amount,
    note: str = "",
) -> Dividend:
    """A draft round for the period, split by the shares on its last day."""
    services._need_actor(by)
    user = services._actor(company, by)
    if period_end < period_start:
        raise DomainError(_("The period ends before it starts."))
    value = services._money(amount)
    partners = partners_on(company, period_end)
    if not partners:
        raise DomainError(_("Add the partners and their shares first."))
    profit = queries.totals(company, period_start, period_end, branch_ids=None)["profit"]
    dividend = Dividend.objects.create(
        company=company,
        period_start=period_start,
        period_end=period_end,
        amount=value,
        profit=quantize(profit),
        note=(note or "").strip()[:300],
        created_by=user,
    )
    _make_lines(dividend, partners)
    services._audit(
        FinanceAction.DIVIDEND_CREATED,
        company,
        user,
        dividend,
        period=[period_start.isoformat(), period_end.isoformat()],
        amount=str(value),
    )
    return dividend


def _make_lines(dividend: Dividend, partners: list[Partner]) -> None:
    DividendLine.objects.bulk_create(
        DividendLine(dividend=dividend, partner=partner, share=partner.share, amount=part)
        for partner, part in zip(partners, split(dividend.amount, partners), strict=True)
        if part > 0
    )


@transaction.atomic
def update_dividend(dividend: Dividend, *, by: Membership, amount=None, note=None) -> Dividend:
    """Change a round's amount (its lines split again) or note while nothing of it is paid."""
    services._need_actor(by)
    dividend = _lock(dividend)
    company = dividend.company
    user = services._actor(company, by)
    if state(dividend) != Dividend.Status.DRAFT:
        raise DomainError(_("Only a dividend with nothing paid yet can be changed."))
    changes = {}
    if amount is not None:
        value = services._money(amount)
        if value != dividend.amount:
            changes["amount"] = [str(dividend.amount), str(value)]
            dividend.amount = value
            dividend.lines.all().delete()
            _make_lines(dividend, partners_on(company, dividend.period_end))
    if note is not None and (note or "").strip()[:300] != dividend.note:
        changes["note"] = [dividend.note, (note or "").strip()[:300]]
        dividend.note = (note or "").strip()[:300]
    if changes:
        dividend.save(update_fields=["amount", "note", "updated_at"])
        services._audit(FinanceAction.DIVIDEND_UPDATED, company, user, dividend, changes=changes)
    return dividend


@transaction.atomic
def pay_dividend(
    dividend: Dividend,
    *,
    by: Membership,
    account: MoneyAccount,
    paid_on: date,
    line_ids: list[int] | None = None,
) -> Dividend:
    """Pay the round's unpaid lines (or the ones in `line_ids`) from `account` on `paid_on`:
    one owner draw per line. Everything or nothing: the account must hold it all."""
    services._need_actor(by)
    dividend = _lock(dividend)
    company = dividend.company
    user = services._actor(company, by)
    if dividend.status == Dividend.Status.CANCELLED:
        raise DomainError(_("This dividend was cancelled."))
    services._same_company(company, account)
    if account.kind not in owner_draw.DRAW_KINDS:
        raise DomainError(_("Pay dividends from a cash desk, safe, bank account, card or wallet."))
    if account.currency != company.base_currency:
        raise DomainError(
            _("Pay dividends from an account in %(currency)s.")
            % {"currency": company.base_currency}
        )
    lines = [
        line
        for line in dividend.lines.select_related("partner__membership", "transaction")
        if not line.is_paid and (line_ids is None or line.pk in line_ids)
    ]
    if not lines:
        raise DomainError(_("Everything of this dividend is already paid."))
    period = _period_text(dividend)
    for line in lines:
        row = services.record_transaction(
            company,
            by=by,
            kind=Transaction.Kind.OWNER,
            amount=-line.amount,
            occurred_on=paid_on,
            account=account,
            membership=line.partner.membership,
            description=_("Dividend for %(period)s: %(name)s")
            % {"period": period, "name": line.partner.name},
            source=Source(SOURCE, dividend.pk, f"l{line.pk}"),
        )
        line.transaction = row
        line.paid_on = paid_on
        line.save(update_fields=["transaction", "paid_on"])
    _settle(dividend)
    services._audit(
        FinanceAction.DIVIDEND_PAID,
        company,
        user,
        dividend,
        account=account.pk,
        paid_on=paid_on.isoformat(),
        lines=[[line.partner.name, str(line.amount)] for line in lines],
    )
    return dividend


@transaction.atomic
def undo_payment(line: DividendLine, *, by: Membership, reason: str) -> Dividend:
    """Take back one line's payment: its owner draw is voided and the line is unpaid again."""
    services._need_actor(by)
    dividend = _lock(line.dividend)
    company = dividend.company
    user = services._actor(company, by)
    line = DividendLine.objects.select_related("transaction", "partner").get(pk=line.pk)
    if not line.is_paid:
        raise DomainError(_("This part isn't paid."))
    services.void_transaction(line.transaction, by=by, reason=reason)
    line.paid_on = None
    line.save(update_fields=["paid_on"])
    _settle(dividend)
    services._audit(
        FinanceAction.DIVIDEND_UNDONE,
        company,
        user,
        dividend,
        partner=line.partner.name,
        amount=str(line.amount),
        reason=(reason or "").strip()[:300],
    )
    return dividend


@transaction.atomic
def cancel_dividend(dividend: Dividend, *, by: Membership, reason: str) -> Dividend:
    """Drop a round nothing of which is paid."""
    services._need_actor(by)
    reason = services._reason(reason)
    dividend = _lock(dividend)
    company = dividend.company
    user = services._actor(company, by)
    if dividend.status == Dividend.Status.CANCELLED:
        return dividend
    if state(dividend) != Dividend.Status.DRAFT:
        raise DomainError(_("Part of this dividend is paid: take those payments back first."))
    dividend.status = Dividend.Status.CANCELLED
    dividend.cancelled_at = timezone.now()
    dividend.save(update_fields=["status", "cancelled_at", "updated_at"])
    services._audit(FinanceAction.DIVIDEND_CANCELLED, company, user, dividend, reason=reason)
    return dividend


def _lock(dividend: Dividend) -> Dividend:
    return Dividend.objects.select_for_update().select_related("company").get(pk=dividend.pk)


def _settle(dividend: Dividend) -> None:
    status = state(dividend)
    dividend.status = status
    dividend.paid_at = timezone.now() if status == Dividend.Status.PAID else None
    dividend.save(update_fields=["status", "paid_at", "updated_at"])


def _period_text(dividend: Dividend) -> str:
    return (
        f"{dividend.period_start.strftime('%d.%m.%Y')}–{dividend.period_end.strftime('%d.%m.%Y')}"
    )
