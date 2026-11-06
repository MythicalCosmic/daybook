"""Messages payroll sends once a change has committed: inbox notifications (the dashboard, the
mini app inbox and both bots), and the payslip PDF in the employee bot.

Services call the public functions here inside their transaction; each one defers its work to
`transaction.on_commit` and reloads by id, so nothing goes out for a change that was rolled
back. Texts render in each recipient's language; amounts are formatted for that language.
Nothing here writes payroll rows.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import formats, translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.inbox import services as inbox
from apps.inbox.services import NotificationAction
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import in_scope, members_with_perm
from apps.payroll import periods, queries
from apps.payroll.models import Adjustment, Advance, PayrollRun, Payslip

logger = logging.getLogger(__name__)

APPROVE = NotificationAction("approve", gettext_lazy("Approve"), "primary")
REJECT = NotificationAction("reject", gettext_lazy("Reject"), "danger")
RECEIVED = NotificationAction("received", gettext_lazy("I received it"), "primary")

# Mini app screens (`?screen=` deep links).
WALLET = "wallet"


def payslip_screen(payslip_id: int) -> str:
    return f"payslip:{payslip_id}"


def _url(company_id: int, path: str = "") -> str:
    return f"/c/{company_id}/payroll{path}"


def _money(amount, currency) -> str:
    return queries.money_text(amount, currency, translation.get_language())


def _later(job, *args) -> None:
    transaction.on_commit(lambda: job(*args))


def deciders(company, member: Membership, perm: Perm = Perm.PAYROLL_MANAGE) -> list[Membership]:
    """Who decides about `member`: holders of `perm` who see them, never they themselves."""
    people = members_with_perm(company, perm).exclude(pk=member.pk).select_related("user")
    return [person for person in people if in_scope(person, member)]


# Bonuses and fines ----------------------------------------------------------------------


def _adjustment(adjustment_id: int) -> Adjustment | None:
    return (
        Adjustment.objects.select_related("company", "membership__user")
        .filter(pk=adjustment_id)
        .first()
    )


def _kind_title(row: Adjustment) -> str:
    values = {"name": row.membership, "amount": _money(row.amount, row.currency)}
    return {
        Adjustment.Kind.BONUS: _("Bonus for %(name)s: %(amount)s"),
        Adjustment.Kind.FINE: _("Fine for %(name)s: %(amount)s"),
        Adjustment.Kind.ALLOWANCE: _("Allowance for %(name)s: %(amount)s"),
        Adjustment.Kind.DEDUCTION: _("Deduction for %(name)s: %(amount)s"),
    }[row.kind] % values


def adjustment_proposed(row: Adjustment, by: Membership | None) -> None:
    _later(_adjustment_proposed, row.pk, by.pk if by is not None else None)


def _adjustment_proposed(adjustment_id: int, by_id: int | None) -> None:
    row = _adjustment(adjustment_id)
    if row is None or row.status != Adjustment.Status.PROPOSED:
        return
    recipients = [p for p in deciders(row.company, row.membership) if p.pk != by_id]
    inbox.notify(
        recipients,
        "payroll.adjustment",
        title=lambda _person: _kind_title(row),
        body=lambda _person: row.reason,
        url=_url(row.company_id, "/adjustments"),
        target=row,
        actions=[APPROVE, REJECT],
    )


def adjustment_approved(row: Adjustment, by: Membership | None) -> None:
    _later(_adjustment_approved, row.pk)


def _adjustment_approved(adjustment_id: int) -> None:
    row = _adjustment(adjustment_id)
    if row is None or row.status != Adjustment.Status.APPROVED:
        return

    def title(_person):
        values = {"amount": _money(row.amount, row.currency)}
        return {
            Adjustment.Kind.BONUS: _("You got a bonus: +%(amount)s"),
            Adjustment.Kind.ALLOWANCE: _("You got an allowance: +%(amount)s"),
            Adjustment.Kind.FINE: _("You were fined %(amount)s"),
            Adjustment.Kind.DEDUCTION: _("A deduction from your pay: %(amount)s"),
        }[row.kind] % values

    def body(_person):
        lines = [
            row.reason,
            _("On your %(month)s pay.") % {"month": queries.month_label(row.period)},
        ]
        if row.kind in Adjustment.NEGATIVE:
            lines.append(_("Disagree? Open the app and dispute it."))
        return "\n".join(lines)

    inbox.notify(
        [row.membership],
        "payroll.adjustment_decided",
        title=title,
        body=body,
        app_screen=WALLET,
        target=row,
        severity="warning" if row.kind in Adjustment.NEGATIVE else "info",
    )


def adjustment_disputed(row: Adjustment) -> None:
    _later(_adjustment_disputed, row.pk)


def _adjustment_disputed(adjustment_id: int) -> None:
    row = _adjustment(adjustment_id)
    if row is None or not row.dispute_open:
        return
    inbox.notify(
        deciders(row.company, row.membership),
        "payroll.dispute",
        title=lambda _person: (
            _("%(name)s disputes a fine of %(amount)s")
            % {"name": row.membership, "amount": _money(row.amount, row.currency)}
        ),
        body=lambda _person: row.dispute_text,
        url=_url(row.company_id, "/adjustments?tab=disputed"),
        target=row,
    )


def dispute_answered(row: Adjustment, by: Membership | None) -> None:
    _later(_dispute_answered, row.pk)


def _dispute_answered(adjustment_id: int) -> None:
    row = _adjustment(adjustment_id)
    if row is None or row.dispute_answered_at is None:
        return

    def title(_person):
        if row.status == Adjustment.Status.VOID:
            return _("Your dispute was accepted: the fine of %(amount)s is taken back") % {
                "amount": _money(row.amount, row.currency)
            }
        return _("Answer to your dispute about a fine of %(amount)s") % {
            "amount": _money(row.amount, row.currency)
        }

    inbox.notify(
        [row.membership],
        "payroll.adjustment_decided",
        title=title,
        body=lambda _person: row.dispute_answer,
        app_screen=WALLET,
        target=row,
    )


# Advances -------------------------------------------------------------------------------


def _advance(advance_id: int) -> Advance | None:
    return (
        Advance.objects.select_related("company", "membership__user").filter(pk=advance_id).first()
    )


def advance_requested(row: Advance, cap: dict) -> None:
    _later(_advance_requested, row.pk, cap["cap"])


def _advance_requested(advance_id: int, cap) -> None:
    row = _advance(advance_id)
    if row is None or row.status != Advance.Status.REQUESTED:
        return

    def title(_person):
        return _("%(name)s asks for an advance of %(amount)s") % {
            "name": row.membership,
            "amount": _money(row.amount, row.currency),
        }

    def body(_person):
        lines = [_("Limit: %(cap)s") % {"cap": _money(cap, row.currency)}]
        if row.installments > 1:
            lines.append(_("Paid back over %(count)s months") % {"count": row.installments})
        if row.reason:
            lines.append(row.reason)
        return "\n".join(lines)

    inbox.notify(
        deciders(row.company, row.membership),
        "payroll.advance",
        title=title,
        body=body,
        url=_url(row.company_id, "/advances"),
        target=row,
        actions=[APPROVE, REJECT],
    )


def advance_decided(row: Advance, by: Membership | None) -> None:
    _later(_advance_decided, row.pk)


def _advance_decided(advance_id: int) -> None:
    row = _advance(advance_id)
    if row is None or row.status not in (Advance.Status.APPROVED, Advance.Status.REJECTED):
        return
    approved = row.status == Advance.Status.APPROVED

    def title(_person):
        values = {"amount": _money(row.amount, row.currency)}
        if approved:
            return _("Your advance of %(amount)s is approved") % values
        return _("Your advance of %(amount)s was not approved") % values

    inbox.notify(
        [row.membership],
        "payroll.advance_decided",
        title=title,
        body=lambda _person: row.decision_note,
        app_screen=WALLET,
        target=row,
        severity="info",
    )
    if approved:
        payers = deciders(row.company, row.membership, Perm.PAYROLL_PAY)
        inbox.notify(
            payers,
            "payroll.advance_to_pay",
            title=lambda _person: (
                _("Advance to pay: %(name)s, %(amount)s")
                % {"name": row.membership, "amount": _money(row.amount, row.currency)}
            ),
            url=_url(row.company_id, "/advances?tab=to_pay"),
            target=row,
        )


def advance_paid(row: Advance, by: Membership | None) -> None:
    _later(_advance_paid, row.pk)


def _advance_paid(advance_id: int) -> None:
    row = _advance(advance_id)
    if row is None or row.status != Advance.Status.PAID:
        return

    def body(_person):
        if row.installments > 1:
            return _("It comes off your pay over %(count)s months from %(month)s.") % {
                "count": row.installments,
                "month": queries.month_label(row.first_period),
            }
        return _("It comes off your %(month)s pay.") % {
            "month": queries.month_label(row.first_period)
        }

    inbox.notify(
        [row.membership],
        "payroll.advance_decided",
        title=lambda _person: (
            _("Your advance of %(amount)s was paid") % {"amount": _money(row.amount, row.currency)}
        ),
        body=body,
        app_screen=WALLET,
        target=row,
    )


# Runs and payslips ----------------------------------------------------------------------


def run_prepared(run: PayrollRun) -> None:
    _later(_run_prepared, run.pk)


def _run_prepared(run_id: int) -> None:
    run = PayrollRun.objects.select_related("company").filter(pk=run_id).first()
    if run is None or run.status != PayrollRun.Status.DRAFT:
        return
    totals = run.totals or {}
    currency = totals.get("currency") or run.company.base_currency

    def title(_person):
        return _("%(month)s payroll is ready to check") % {"month": queries.month_label(run.period)}

    def body(_person):
        parts = [
            _("People: %(count)s") % {"count": totals.get("people", 0)},
            _("Net pay: %(amount)s") % {"amount": _money(totals.get("net", "0"), currency)},
        ]
        if run.warnings:
            parts.append(_("Warnings: %(count)s") % {"count": len(run.warnings)})
        return " · ".join(parts)

    recipients = list(members_with_perm(run.company, Perm.PAYROLL_FINALIZE).select_related("user"))
    inbox.notify(
        recipients,
        "payroll.run_prepared",
        title=title,
        body=body,
        url=_url(run.company_id, f"/runs/{run.pk}"),
        target=run,
        dedupe_key=f"payroll.run_prepared:{run.pk}:{run.calculated_at:%Y%m%d%H%M%S}"
        if run.calculated_at
        else "",
    )


def final_run_prepared(run: PayrollRun) -> None:
    """A leaver's final payslip waits as a draft: payroll managers who see them hear."""
    _later(_final_run_prepared, run.pk)


def _final_run_prepared(run_id: int) -> None:
    run = (
        PayrollRun.objects.select_related("company", "membership__user")
        .filter(pk=run_id, kind=PayrollRun.Kind.FINAL)
        .first()
    )
    if run is None or run.status != PayrollRun.Status.DRAFT or run.membership is None:
        return
    member = run.membership
    totals = run.totals or {}
    currency = totals.get("currency") or run.company.base_currency
    net = Decimal(str(totals.get("net") or "0"))

    def title(_person):
        return _("The final payslip of %(name)s is ready to check") % {"name": member}

    def body(_person):
        parts = []
        if run.last_day is not None:
            parts.append(
                _("Last working day: %(date)s")
                % {"date": formats.date_format(run.last_day, "d.m.Y")}
            )
        if net < 0:
            parts.append(_("They owe: %(amount)s") % {"amount": _money(-net, currency)})
        else:
            parts.append(_("Net pay: %(amount)s") % {"amount": _money(net, currency)})
        return " · ".join(parts)

    inbox.notify(
        deciders(run.company, member),
        "payroll.final_run",
        title=title,
        body=body,
        url=_url(run.company_id, f"/runs/{run.pk}"),
        target=run,
        dedupe_key=f"payroll.final_run:{run.pk}",
    )


def pay_day(run: PayrollRun | None, company, period) -> None:
    """Pay day morning and the month's pay not marked paid: the payers and owners hear."""
    recipients = list(members_with_perm(company, Perm.PAYROLL_PAY).select_related("user"))

    def title(_person):
        return _("Today is pay day for %(month)s") % {"month": queries.month_label(period)}

    def body(_person):
        if run is None:
            return _("The payroll isn't prepared yet.")
        if run.status == PayrollRun.Status.DRAFT:
            return _("The payroll is still a draft: check and finalize it.")
        return _("The payroll is finalized but not marked paid yet.")

    inbox.notify(
        recipients,
        "payroll.pay_day",
        title=title,
        body=body,
        url=_url(company.pk, f"/runs/{run.pk}" if run is not None else ""),
        dedupe_key=f"payroll.pay_day:{period:%Y-%m}",
        severity="warning",
    )


def payslips_published(payslip_ids: list[int]) -> None:
    _later(_payslips_published, list(payslip_ids))


def _payslip(payslip_id: int) -> Payslip | None:
    return (
        Payslip.objects.select_related("company", "membership__user", "run")
        .filter(pk=payslip_id)
        .first()
    )


def _payslips_published(payslip_ids: list[int]) -> None:
    from apps.payroll import tasks

    for payslip_id in payslip_ids:
        payslip = _payslip(payslip_id)
        if payslip is None or payslip.published_at is None:
            continue

        def title(_person, payslip=payslip):
            return _("Your %(month)s payslip: %(amount)s") % {
                "month": queries.month_label(payslip.run.period),
                "amount": _money(payslip.net, payslip.currency),
            }

        created = inbox.notify(
            [payslip.membership],
            "payroll.payslip",
            title=title,
            body=lambda _person: _("Open it to see every line, or download the PDF."),
            app_screen=payslip_screen(payslip.pk),
            target=payslip,
            dedupe_key=f"payroll.payslip:{payslip.pk}:{payslip.published_at:%Y%m%d%H%M%S}",
        )
        if created:
            tasks.send_payslip_pdf.delay(payslip.pk)


def payslips_paid(payslip_ids: list[int]) -> None:
    _later(_payslips_paid, list(payslip_ids))


def _payslips_paid(payslip_ids: list[int]) -> None:
    for payslip_id in payslip_ids:
        payslip = _payslip(payslip_id)
        if payslip is None or payslip.paid_at is None:
            continue

        def title(_person, payslip=payslip):
            return _("Your %(month)s pay of %(amount)s was paid") % {
                "month": queries.month_label(payslip.run.period),
                "amount": _money(payslip.net, payslip.currency),
            }

        inbox.notify(
            [payslip.membership],
            "payroll.payslip",
            title=title,
            body=lambda _person: _("Tap the button once the money is with you."),
            app_screen=payslip_screen(payslip.pk),
            target=payslip,
            actions=[RECEIVED],
            dedupe_key=f"payroll.paid:{payslip.pk}:{payslip.paid_at:%Y%m%d%H%M%S}",
        )


def month(period) -> str:
    """For bot texts: the month a payroll period names."""
    return queries.month_label(periods.first_day(period))
