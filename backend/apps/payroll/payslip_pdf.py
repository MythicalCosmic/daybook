"""The payslip as a PDF (`apps.core.pdf`), in the reader's language: a plain module the API, the
Celery task and the bot use.

Each render replaces the payslip's stored file (`Payslip.pdf`, private storage): downloads
get a short-lived signed link to it, and the employee bot sends it as a document.
"""

import logging
from decimal import Decimal
from uuid import uuid4

from django.core.files.base import ContentFile
from django.utils import formats, timezone, translation
from django.utils.translation import gettext as _

from apps.core import pdf
from apps.payroll import labels, periods, queries
from apps.payroll.models import Payslip, PayType

logger = logging.getLogger(__name__)


def _money(amount: Decimal, currency: str) -> str:
    return queries.money_text(amount, currency)


def _how(line) -> str:
    if line.quantity is None or line.rate is None:
        return ""
    quantity = f"{line.quantity:.2f}".rstrip("0").rstrip(".")
    return f"{quantity} × {_money(line.rate, line.payslip.currency)}"


def context(payslip: Payslip) -> dict:
    run = payslip.run
    member = payslip.membership
    month = queries.month_label(run.period)
    lines = list(payslip.lines.select_related("adjustment", "payslip").order_by("order", "pk"))
    final = run.kind == run.Kind.FINAL
    facts = []
    if final and run.last_day is not None:
        facts.append(
            _("Last working day: %(date)s") % {"date": formats.date_format(run.last_day, "d.m.Y")}
        )
    facts += [
        _("Working days: %(days)s") % {"days": payslip.scheduled_days.normalize()},
        _("Paid days: %(days)s") % {"days": payslip.paid_days.normalize()},
    ]
    if payslip.worked_minutes:
        facts.append(
            _("Hours worked: %(hours)s")
            % {"hours": (Decimal(payslip.worked_minutes) / 60).quantize(Decimal("0.1"))}
        )
    taxes_note = ""
    if payslip.taxes and not payslip.taxes.get("withheld"):
        taxes_note = _(
            "Taxes are paid by the company on top: income tax %(income)s, pension %(pension)s."
        ) % {
            "income": _money(Decimal(payslip.taxes["income_tax"]), payslip.currency),
            "pension": _money(Decimal(payslip.taxes["inps"]), payslip.currency),
        }
    paid_on = ""
    if payslip.paid_at is not None:
        paid_on = formats.date_format(periods.local(payslip.company, payslip.paid_at), "d.m.Y")
    owes = payslip.net < 0
    title = _("Final payslip: %(month)s") if final else _("Payslip: %(month)s")
    return {
        "company": payslip.company,
        "title": title % {"month": month},
        "heading": member.full_name or str(member.user),
        "printed_on": formats.date_format(periods.today(payslip.company), "d.m.Y"),
        "person": str(member),
        "position": member.position.name if member.position_id else "",
        "branch": member.home_branch.name if member.home_branch_id else "",
        "month": month,
        "pay_type": PayType(payslip.pay_type).label,
        "net": _money(-payslip.net if owes else payslip.net, payslip.currency),
        # A final payslip below zero: what they owe stays as a debt in Finance.
        "net_label": _("They owe the company") if owes else _("To be paid"),
        "owes_note": _("What they owe stays as a debt in Finance.") if owes else "",
        "gross": _money(payslip.gross, payslip.currency),
        "deductions": _money(payslip.deductions, payslip.currency),
        "paid_on": paid_on,
        "facts": " · ".join(facts),
        "taxes_note": taxes_note,
        "lines": [
            {
                "label": labels.line_label(line),
                "how": _how(line),
                "amount": _money(line.amount, payslip.currency),
                "negative": line.amount < 0,
            }
            for line in lines
        ],
    }


def render(payslip: Payslip, *, language: str) -> bytes:
    payslip = Payslip.objects.select_related(
        "company", "run", "membership__user", "membership__position", "membership__home_branch"
    ).get(pk=payslip.pk)
    with translation.override(language):
        data = context(payslip)
    return pdf.render_pdf("payroll/payslip.html", data, language=language)


def save(payslip: Payslip, *, language: str):
    """Render and store the PDF; returns the stored file."""
    data = render(payslip, language=language)
    old = payslip.pdf.name if payslip.pdf else ""
    payslip.pdf.save(f"{uuid4().hex}.pdf", ContentFile(data), save=False)
    Payslip.objects.filter(pk=payslip.pk).update(pdf=payslip.pdf.name, updated_at=timezone.now())
    if old:
        try:
            payslip.pdf.storage.delete(old)
        except OSError:
            logger.warning("Old payslip PDF %s could not be removed", old)
    return payslip.pdf


def file_name(payslip: Payslip) -> str:
    return f"payslip-{payslip.run.period:%Y-%m}-{payslip.pk}.pdf"
