"""The statement pack (v12): one PDF for a bank, a partner or a buyer, in Uzbek, Russian or
English, built in the background from the company's books (`StatementPack`, kept 7 days).

    cover            company, period, the day it was prepared, "from the company's records in
                     Daybook, not audited"
    summary          revenue, profit, cash, debts, net assets, twelve months of trend, ratios
    purpose pages    bank: loans and their payments, then the cash flow; partner: the partners,
                     their part of the profit and the dividends; sale: what the business is worth
    profit and loss  revenue, cost of goods, gross profit, running costs, depreciation, taxes,
                     net profit; by month (a quarter) or quarter (a year), with the same period a
                     year before when the books have it
    cash flow        operating, equipment, loans, owner money, opening balances, revaluation
    balance sheet    on the period's last day (`statements.balance_sheet`), with the day a year
                     before when the books go back that far
    notes            how the figures are made, loans, the largest debts both ways, fixed assets,
                     foreign money, how retained earnings are made, and what the books leave out

`request_pack` queues one (audited); `build(pack_id)` runs in Celery, moving `progress` as it
goes, and sends the PDF to the requester's Telegram when asked. Figures come from `queries`,
`statements`, `partners` and the assets module's register; nothing here writes the ledger.
"""

from __future__ import annotations

import logging
import re
import zlib
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone, translation
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.audit import services as audit
from apps.console import pulse
from apps.core import pdf
from apps.core.exceptions import DomainError
from apps.core.money import SOM, Currency, quantize
from apps.finance import partners, queries, statements
from apps.finance.audit_actions import FinanceAction
from apps.finance.models import Debt, Dividend, StatementPack, Transaction
from apps.members import scope
from apps.members.models import Membership

logger = logging.getLogger(__name__)

ZERO = Decimal(0)
HUNDRED = Decimal(100)
LANGUAGES = ("uz", "ru", "en")
KEEP = timedelta(days=7)
STUCK_AFTER = timedelta(hours=2)
PULSE = "finance.statements"
EXPORTER = "finance.balance_sheet"
TEMPLATE = "finance/statement_pack.html"
PAGE_OBJECT = re.compile(rb"/Type\s*/Page(?![a-zA-Z])")
STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.DOTALL)
TOP_DEBTS = 5
TREND_MONTHS = 12
NBSP = " "
THIN = " "
DASH = "–"
MINUS = "−"

MONTHS = {
    "en": (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ),
    "ru": (
        "Январь",
        "Февраль",
        "Март",
        "Апрель",
        "Май",
        "Июнь",
        "Июль",
        "Август",
        "Сентябрь",
        "Октябрь",
        "Ноябрь",
        "Декабрь",
    ),
    "uz": (
        "yanvar",
        "fevral",
        "mart",
        "aprel",
        "may",
        "iyun",
        "iyul",
        "avgust",
        "sentabr",
        "oktabr",
        "noyabr",
        "dekabr",
    ),
}
SHORT_MONTHS = {
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
    "ru": ("янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"),
    "uz": ("yan", "fev", "mar", "apr", "may", "iyn", "iyl", "avg", "sen", "okt", "noy", "dek"),
}
# Purpose pages after the summary, and the order of the rest.
ORDER = {
    StatementPack.Purpose.BANK: ("loans", "cash_flow", "pnl", "balance", "notes"),
    StatementPack.Purpose.PARTNER: ("partners", "pnl", "balance", "cash_flow", "notes"),
    StatementPack.Purpose.SALE: ("valuation", "pnl", "balance", "cash_flow", "notes"),
}


# Periods ------------------------------------------------------------------------------------------


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def period_range(period: str, of: date, today: date) -> tuple[date, date]:
    """The first and last day of the month, quarter or year holding `of`; a period not over
    yet ends today. Raises DomainError for a period that hasn't started."""
    if period == StatementPack.Period.MONTH:
        start = date(of.year, of.month, 1)
        end = _add_months(start, 1) - timedelta(days=1)
    elif period == StatementPack.Period.QUARTER:
        start = date(of.year, 3 * ((of.month - 1) // 3) + 1, 1)
        end = _add_months(start, 3) - timedelta(days=1)
    elif period == StatementPack.Period.YEAR:
        start, end = date(of.year, 1, 1), date(of.year, 12, 31)
    else:
        raise DomainError(_("Pick a month, a quarter or a year."))
    if start > today:
        raise DomainError(_("That period hasn't started yet."))
    return start, min(end, today)


def _year_before(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:  # 29 February
        return day.replace(year=day.year - 1, day=28)


# Formatting ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Fmt:
    """Numbers, money and days the way the pack prints them in `language`: whole so‘m with
    grouped digits, a loss in brackets, nothing as an en dash."""

    language: str
    currency: str

    @property
    def unit(self) -> str:
        return SOM[self.language] if self.currency == Currency.UZS else self.currency

    def n(self, value, *, dash: bool = True) -> str:
        if value is None:
            return DASH
        value = Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        if not value and dash:
            return DASH
        text = f"{abs(int(value)):,}".replace(",", "," if self.language == "en" else NBSP)
        return f"({text})" if value < 0 else text

    def money(self, value) -> str:
        if value is None:
            return DASH
        return f"{self.n(value, dash=False)}{NBSP}{self.unit}"

    def amount(self, value, currency: str) -> str:
        """A foreign amount in its own currency, cents kept."""
        value = quantize(value)
        whole, cents = divmod(abs(value), 1)
        group, mark = (",", ".") if self.language == "en" else (NBSP, ",")
        text = f"{int(whole):,}".replace(",", group) + f"{mark}{int(cents * 100):02d}"
        sign = "−" if value < 0 else ""
        return f"{sign}${text}" if currency == Currency.USD else f"{sign}{text}{NBSP}{currency}"

    def rate(self, value) -> str:
        if value is None:
            return DASH
        value = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        whole, cents = divmod(value, 1)
        group, mark = (",", ".") if self.language == "en" else (NBSP, ",")
        return f"{int(whole):,}".replace(",", group) + f"{mark}{int(cents * 100):02d}"

    def pct(self, value) -> str:
        if value is None:
            return DASH
        text = f"{Decimal(value).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}"
        if self.language != "en":
            text = text.replace(".", ",")
        return f"{text.replace('-', MINUS)}{NBSP}%"

    def times(self, value) -> str:
        if value is None:
            return DASH
        text = f"{Decimal(value).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}"
        if self.language != "en":
            text = text.replace(".", ",")
        return f"{text.replace('-', MINUS)}×"

    def decimal(self, value) -> str:
        text = f"{Decimal(value).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}"
        if self.language != "en":
            text = text.replace(".", ",")
        return text.replace("-", MINUS)

    def day(self, value: date | None) -> str:
        if value is None:
            return DASH
        if self.language == "en":
            return f"{value.day}{NBSP}{SHORT_MONTHS['en'][value.month - 1]}{NBSP}{value.year}"
        return value.strftime("%d.%m.%Y")

    def month(self, value: date) -> str:
        return MONTHS[self.language][value.month - 1]

    def short_month(self, value: date) -> str:
        return SHORT_MONTHS[self.language][value.month - 1]


def period_label(fmt: Fmt, period: str, start: date, end: date, *, full_end: date) -> str:
    if period == StatementPack.Period.MONTH:
        text = _("%(month)s %(year)s") % {"month": fmt.month(start), "year": start.year}
    elif period == StatementPack.Period.QUARTER:
        text = _("Quarter %(quarter)s, %(year)s") % {
            "quarter": (start.month - 1) // 3 + 1,
            "year": start.year,
        }
    else:
        text = _("Year %(year)s") % {"year": start.year}
    if end < full_end:
        text = _("%(period)s, to %(day)s") % {"period": text, "day": fmt.day(end)}
    return text


def _ratio(part, whole) -> Decimal | None:
    if part is None or not whole:
        return None
    return Decimal(part) / Decimal(whole) * HUNDRED


# Requesting ---------------------------------------------------------------------------------------


def may_prepare(member: Membership) -> bool:
    """`finance.view` and the export permission, as the other finance exports need."""
    from apps.exports.registry import get_exporter, may_export

    exporter = get_exporter(EXPORTER)
    return exporter is not None and may_export(member, exporter)


@transaction.atomic
def request_pack(
    member: Membership,
    *,
    period: str,
    of: date,
    purpose: str,
    language: str,
    branch_ids: list[int] | None,
    multiple_low=None,
    multiple_high=None,
    deliver_telegram: bool = False,
) -> StatementPack:
    """Queue a statement pack as `member` (who must `may_prepare`); `branch_ids` is already
    their scope narrowed by what they picked."""
    from django.core.exceptions import PermissionDenied

    if not may_prepare(member):
        raise PermissionDenied(_("You don't have permission to export this."))
    if purpose not in StatementPack.Purpose.values:
        raise DomainError(_("Pick who the report is for."))
    if language not in LANGUAGES:
        raise DomainError(_("Pick the report's language."))
    company = member.company
    today = queries.local_today(company)
    start, end = period_range(period, of, today)
    if statements.books_start(company) is None:
        raise DomainError(_("There is nothing in the books yet to report on."))
    params: dict = {"branch": branch_ids}
    for key, value in (("multiple_low", multiple_low), ("multiple_high", multiple_high)):
        if value is not None:
            params[key] = str(value)
    pack = StatementPack.objects.create(
        company=company,
        requested_by=member,
        period=period,
        start=start,
        end=end,
        purpose=purpose,
        language=language,
        params=params,
        deliver_telegram=deliver_telegram and member.user.telegram_id is not None,
    )
    audit.record(
        FinanceAction.STATEMENTS_PREPARED,
        company_id=company.pk,
        actor=member.user,
        target=pack,
        period=period,
        start=start.isoformat(),
        end=end.isoformat(),
        purpose=purpose,
        language=language,
        branches=branch_ids,
        deliver_telegram=pack.deliver_telegram,
    )
    from apps.finance import tasks

    transaction.on_commit(lambda: tasks.build_statement_pack.delay(pack.pk))
    transaction.on_commit(lambda: pulse.bump(company.pk, PULSE))
    return pack


# Building -----------------------------------------------------------------------------------------


def build(pack_id: int) -> None:
    """Build one waiting pack. Safe to run twice: only a waiting pack is built."""
    with transaction.atomic():
        pack = (
            StatementPack.objects.select_for_update(of=("self",))
            .select_related("company", "requested_by__user", "requested_by__role")
            .filter(pk=pack_id)
            .first()
        )
        if pack is None or pack.status != StatementPack.Status.PENDING:
            return
        pack.status = StatementPack.Status.RUNNING
        pack.progress = 5
        pack.save(update_fields=["status", "progress", "updated_at"])
    member = pack.requested_by
    with translation.override(pack.language):
        try:
            member.refresh_from_db(fields=["status", "role"])
            if (
                member.status != Membership.Status.APPROVED
                or not pack.company.is_active
                or not pack.company.has_feature("finance")
                or not may_prepare(member)
            ):
                _finish(pack, error=_("You no longer have permission to prepare this report."))
                return
            content, pages = render(pack, progress=lambda value: _progress(pack, value))
        except Exception:
            logger.exception("Statement pack %s failed", pack.pk)
            _finish(pack, error=_("Something went wrong while preparing this report."))
            return
        pack.file.save(f"{pack.pk}.pdf", ContentFile(content), save=False)
        pack.pages = pages
        _finish(pack)
        if pack.deliver_telegram:
            _send_to_telegram(pack)


def _progress(pack: StatementPack, value: int) -> None:
    StatementPack.objects.filter(pk=pack.pk).update(progress=min(max(value, 0), 99))


def _finish(pack: StatementPack, *, error: str = "") -> None:
    pack.status = StatementPack.Status.FAILED if error else StatementPack.Status.READY
    pack.error = error[:300]
    pack.progress = 100
    pack.finished_at = timezone.now()
    pack.save(
        update_fields=["status", "error", "progress", "pages", "file", "finished_at", "updated_at"]
    )
    pulse.bump(pack.company_id, PULSE)


def download_name(pack: StatementPack) -> str:
    """ "hisobot-demo-dorixona-2026-10.pdf": the report, the company and the period."""
    company = slugify(pack.company.name) or "company"
    if pack.period == StatementPack.Period.MONTH:
        period = f"{pack.start:%Y-%m}"
    elif pack.period == StatementPack.Period.QUARTER:
        period = f"{pack.start.year}-q{(pack.start.month - 1) // 3 + 1}"
    else:
        period = f"{pack.start.year}"
    with translation.override(pack.language):
        word = slugify(_("financial statements")) or "statements"
    return f"{word}-{company}-{period}.pdf"


def can_download(user, company_id: int, object_id) -> bool:
    """A signed link to a pack opens for the person who asked for it, while they still may
    prepare one (checked every time the link is used)."""
    try:
        pk = int(object_id)
    except TypeError, ValueError:
        return False
    pack = (
        StatementPack.objects.select_related("requested_by__role", "requested_by__company")
        .filter(pk=pk, company_id=company_id, status=StatementPack.Status.READY)
        .first()
    )
    if pack is None or pack.requested_by.user_id != user.pk:
        return False
    member = pack.requested_by
    return (
        member.status == Membership.Status.APPROVED
        and member.company.is_active
        and member.company.has_feature("finance")
        and may_prepare(member)
    )


def _send_to_telegram(pack: StatementPack) -> None:
    from apps.inbox.delivery import bot_for
    from apps.notifications.tasks import send_telegram_document

    user = pack.requested_by.user
    if user.telegram_id is None:
        return
    with translation.override(pack.language):
        caption = _("%(company)s: financial statements, %(period)s") % {
            "company": pack.company.name,
            "period": _label_of(pack),
        }
    send_telegram_document.delay(
        bot_for(user, "owner"),
        user.telegram_id,
        pack.file.name,
        storage="private",
        caption=caption,
        filename=download_name(pack),
    )


def _label_of(pack: StatementPack) -> str:
    fmt = Fmt(pack.language, pack.company.base_currency)
    _start, full_end = period_range(pack.period, pack.start, date.max - timedelta(days=400))
    return period_label(fmt, pack.period, pack.start, pack.end, full_end=full_end)


def render(pack: StatementPack, *, progress=lambda value: None) -> tuple[bytes, int]:
    """The pack's PDF and its page count."""
    context = collect(
        pack.company,
        period=pack.period,
        start=pack.start,
        end=pack.end,
        purpose=pack.purpose,
        language=pack.language,
        branch_ids=_branch_ids(pack),
        multiple_low=pack.params.get("multiple_low"),
        multiple_high=pack.params.get("multiple_high"),
        prepared_by=pack.requested_by,
        progress=progress,
    )
    progress(80)
    content = pdf.render_pdf(TEMPLATE, context, language=pack.language)
    progress(95)
    return content, page_count(content)


def _branch_ids(pack: StatementPack) -> list[int] | None:
    """The branches asked for, kept inside the requester's scope today."""
    asked = pack.params.get("branch")
    member_scope = scope.branch_ids(pack.requested_by)
    if asked is None:
        return member_scope
    if member_scope is None:
        return list(asked)
    return [pk for pk in asked if pk in member_scope]


def page_count(content: bytes) -> int:
    """How many pages a PDF has: its page objects, which WeasyPrint keeps in compressed object
    streams."""
    found = len(PAGE_OBJECT.findall(content))
    for stream in STREAM.findall(content):
        try:
            found += len(PAGE_OBJECT.findall(zlib.decompress(stream)))
        except zlib.error:
            continue
    return found


def prune() -> int:
    """Daily: packs older than `KEEP` go with their files; stuck ones are marked failed."""
    now = timezone.now()
    removed = 0
    for pack in StatementPack.objects.filter(created_at__lt=now - KEEP).iterator():
        if pack.file:
            pack.file.delete(save=False)
        pack.delete()
        removed += 1
    stuck = StatementPack.objects.filter(
        status__in=(StatementPack.Status.PENDING, StatementPack.Status.RUNNING),
        created_at__lt=now - STUCK_AFTER,
    )
    for pack in stuck.select_related("requested_by__user"):
        with translation.override(pack.language):
            pack.error = _("This report took too long. Please try again.")
        pack.status = StatementPack.Status.FAILED
        pack.finished_at = now
        pack.save(update_fields=["status", "error", "finished_at", "updated_at"])
    return removed


# Collecting ---------------------------------------------------------------------------------------


def collect(
    company,
    *,
    period: str,
    start: date,
    end: date,
    purpose: str,
    language: str,
    branch_ids: list[int] | None,
    multiple_low=None,
    multiple_high=None,
    prepared_by: Membership | None = None,
    progress=lambda value: None,
) -> dict:
    """Everything the template prints, formatted, in `language` (call it inside
    `translation.override`), with the raw figures under `raw` for tests."""
    with translation.override(language):
        return _collect(
            company,
            period=period,
            start=start,
            end=end,
            purpose=purpose,
            language=language,
            branch_ids=branch_ids,
            multiple_low=multiple_low,
            multiple_high=multiple_high,
            prepared_by=prepared_by,
            progress=progress,
        )


def _collect(
    company,
    *,
    period,
    start,
    end,
    purpose,
    language,
    branch_ids,
    multiple_low,
    multiple_high,
    prepared_by,
    progress,
) -> dict:
    fmt = Fmt(language, company.base_currency)
    today = queries.local_today(company)
    _first, full_end = period_range(period, start, date.max - timedelta(days=400))
    whole = branch_ids is None
    compare = None
    before_start, before_end = _year_before(start), _year_before(end)
    if statements.has_rows(company, before_start, before_end, branch_ids=branch_ids):
        compare = (before_start, before_end)
    group = "quarter" if period == StatementPack.Period.YEAR else "month"
    progress(15)
    pnl = queries.pnl(company, start, end, group, branch_ids=branch_ids, compare=compare)
    pnl_view = _pnl_view(pnl, fmt, compare is not None)
    progress(30)
    flow = queries.cash_flow(company, start, end, "month", branch_ids=branch_ids, compare=compare)
    flow_view = _cash_flow_view(flow, fmt, compare is not None)
    progress(45)
    sheet = statements.balance_sheet(company, end, branch_ids=branch_ids, today=today)
    sheet_before = None
    books_start = statements.books_start(company)
    if books_start is not None and books_start <= _year_before(end):
        sheet_before = statements.balance_sheet(
            company, _year_before(end), branch_ids=branch_ids, today=today
        )
    balance_view = _balance_view(sheet, sheet_before, fmt)
    progress(60)
    loans = _loans(company, start, end, branch_ids=branch_ids, fmt=fmt)
    worth = None
    if whole:
        worth = statements.worth(company, end, sheet=sheet, low=multiple_low, high=multiple_high)
    partner_view = _partners_view(company, start, end, fmt) if whole else None
    progress(70)
    revenue = pnl["income"]["total"]
    profit = pnl["profit"]["total"]
    summary = _summary(
        company,
        start=start,
        end=end,
        books_start=books_start,
        branch_ids=branch_ids,
        fmt=fmt,
        pnl=pnl,
        pnl_view=pnl_view,
        flow=flow,
        sheet=sheet,
        loans=loans,
    )
    notes = _notes(
        company,
        start=start,
        end=end,
        branch_ids=branch_ids,
        fmt=fmt,
        sheet=sheet,
        books_start=books_start,
        compare=compare,
    )
    order = [key for key in ORDER[purpose] if key != "partners" or partner_view is not None]
    if purpose == StatementPack.Purpose.SALE and worth is None:
        order = [key for key in order if key != "valuation"]
    if purpose == StatementPack.Purpose.BANK and not loans["rows"]:
        order = [key for key in order if key != "loans"]
    title = _("Financial statements")
    period_text = period_label(fmt, period, start, end, full_end=full_end)
    branches = None
    if branch_ids is not None:
        names = list(
            company.branches.filter(pk__in=branch_ids)
            .order_by("order", "name")
            .values_list("name", flat=True)
        )
        branches = ", ".join(names) if names else _("No branches")
    logo = pdf.image_src(company.logo) if getattr(company, "logo", None) else ""
    return {
        "company": company,
        "logo_src": logo,
        "title": title,
        "period_text": period_text,
        "purpose": purpose,
        "purpose_text": {
            StatementPack.Purpose.BANK: _("Prepared for a bank"),
            StatementPack.Purpose.PARTNER: _("Prepared for the partners"),
            StatementPack.Purpose.SALE: _("Prepared for a buyer of the business"),
        }[purpose],
        "range_text": _("%(start)s – %(end)s") % {"start": fmt.day(start), "end": fmt.day(end)},
        "prepared_on": fmt.day(today),
        "prepared_by": prepared_by.full_name if prepared_by is not None else "",
        "branches": branches,
        "unit": fmt.unit,
        "order": order,
        "toc": [(key.replace("_", "-"), section_title(key)) for key in ("summary", *order)],
        "summary": summary,
        "pnl": pnl_view,
        "cash_flow": flow_view,
        "balance": balance_view,
        "loans": loans,
        "valuation": _valuation_view(worth, fmt) if worth is not None else None,
        "partners": partner_view,
        "notes": notes,
        "footer": f"{company.name} · {title} · {period_text}",
        "raw": {
            "revenue": revenue,
            "profit": profit,
            "sheet": sheet,
            "worth": worth,
            "compare": compare,
            "pnl": pnl,
            "flow": flow,
        },
    }


def section_title(key: str) -> str:
    return {
        "summary": _("Summary"),
        "loans": _("Loans and their payments"),
        "partners": _("Partners and dividends"),
        "valuation": _("What the business is worth"),
        "pnl": _("Profit and loss"),
        "cash_flow": _("Cash flow"),
        "balance": _("Balance sheet"),
        "notes": _("Notes"),
    }[key]


# The profit and loss ------------------------------------------------------------------------------


COGS_CODES = ("goods",)
TAX_CODES = ("taxes",)


def _pnl_view(pnl: dict, fmt: Fmt, compare: bool) -> dict:
    """The P&L in sections: revenue, cost of goods, gross profit, running costs, operating
    profit, depreciation, taxes, net profit; one column per period (when more than one), the
    total, and the year before."""
    periods = pnl["periods"]
    many = len(periods) > 1

    def label(period: dict) -> str:
        key = period["key"]
        if "Q" in key:
            _year, quarter = key.split("-Q")
            return _("Q%(quarter)s") % {"quarter": quarter}
        first = date.fromisoformat(period["from"])
        return fmt.short_month(first)

    columns = [label(period) for period in periods] if many else []

    def cells(amounts, total, previous) -> dict:
        return {
            "amounts": [fmt.n(value) for value in amounts] if many else [],
            "total": fmt.n(total),
            "previous": fmt.n(previous) if compare else None,
            "change": _change(total, previous, fmt) if compare else None,
        }

    def rows_of(nodes: list[dict]) -> list[dict]:
        rows = []
        for node in nodes:
            rows.append(
                {
                    "name": node["name"],
                    "level": 0,
                    **cells(node["amounts"], node["total"], node["previous"]),
                }
            )
            for child in node["children"]:
                rows.append(
                    {
                        "name": child["name"],
                        "level": 1,
                        **cells(child["amounts"], child["total"], child["previous"]),
                    }
                )
            if node["children"] and any(node["own"]):
                rows.append(
                    {
                        "name": _("%(category)s, other") % {"category": node["name"]},
                        "level": 1,
                        **cells(node["own"], node["own_total"], None),
                    }
                )
        return rows

    def total_of(nodes: list[dict]) -> tuple[list[Decimal], Decimal, Decimal]:
        amounts = [
            sum((node["amounts"][index] for node in nodes), ZERO) for index in range(len(periods))
        ]
        previous = sum((node["previous"] or ZERO for node in nodes), ZERO)
        return amounts, sum(amounts, ZERO), previous

    expense = pnl["expense"]["nodes"]
    cogs = [node for node in expense if node["system_code"] in COGS_CODES]
    taxes = [node for node in expense if node["system_code"] in TAX_CODES]
    depreciation = [
        node for node in expense if node["system_code"] in statements.DEPRECIATION_CODES
    ]
    running = [node for node in expense if node not in cogs + taxes + depreciation]
    income = pnl["income"]["nodes"]
    revenue_amounts, revenue_total, revenue_previous = total_of(income)
    cogs_amounts, cogs_total, cogs_previous = total_of(cogs)
    running_amounts, running_total, running_previous = total_of(running)

    def minus(a, b):
        return [x - y for x, y in zip(a, b, strict=True)]

    gross_amounts = minus(revenue_amounts, cogs_amounts)
    gross_total, gross_previous = revenue_total - cogs_total, revenue_previous - cogs_previous
    operating_amounts = minus(gross_amounts, running_amounts)
    operating_total = gross_total - running_total
    operating_previous = gross_previous - running_previous
    net_amounts = pnl["profit"]["amounts"]
    net_total, net_previous = pnl["profit"]["total"], pnl["profit"]["previous"] or ZERO

    blocks = [
        {"kind": "head", "name": _("Revenue")},
        *[{"kind": "line", **row} for row in rows_of(income)],
        {
            "kind": "subtotal",
            "name": _("Total revenue"),
            **cells(revenue_amounts, revenue_total, revenue_previous),
        },
    ]
    if cogs:
        blocks += [
            {"kind": "head", "name": _("Cost of goods")},
            *[{"kind": "line", **row} for row in rows_of(cogs)],
            {
                "kind": "subtotal",
                "name": _("Gross profit"),
                "margin": fmt.pct(_ratio(gross_total, revenue_total)),
                **cells(gross_amounts, gross_total, gross_previous),
            },
        ]
    blocks += [
        {"kind": "head", "name": _("Running costs")},
        *[{"kind": "line", **row} for row in rows_of(running)],
        {
            "kind": "subtotal",
            "name": _("Total running costs"),
            **cells(running_amounts, running_total, running_previous),
        },
        {
            "kind": "subtotal",
            "name": _("Operating profit"),
            "margin": fmt.pct(_ratio(operating_total, revenue_total)),
            **cells(operating_amounts, operating_total, operating_previous),
        },
    ]
    if depreciation:
        blocks += [{"kind": "line", **row} for row in rows_of(depreciation)]
    if taxes:
        blocks += [{"kind": "line", **row} for row in rows_of(taxes)]
    blocks.append(
        {
            "kind": "total",
            "name": _("Net profit"),
            "margin": fmt.pct(_ratio(net_total, revenue_total)),
            **cells(net_amounts, net_total, net_previous),
        }
    )
    return {
        "columns": columns,
        "compare": compare,
        "blocks": blocks,
        "empty": not income and not expense,
        "gross_margin": _ratio(gross_total, revenue_total) if cogs else None,
        "operating": operating_total,
    }


def _change(total, previous, fmt: Fmt) -> str | None:
    if previous is None or not previous or total is None:
        return None
    change = (Decimal(total) - Decimal(previous)) / abs(Decimal(previous)) * HUNDRED
    if abs(change) > 999:
        return None
    sign = "+" if change > 0 else ("−" if change < 0 else "")
    return f"{sign}{fmt.pct(abs(change))}"


# Cash flow ----------------------------------------------------------------------------------------


FLOW_LABELS = {
    "operating": lambda: _("Operating: sales, purchases and running costs"),
    "investing": lambda: _("Equipment and investments"),
    "financing": lambda: _("Loans taken and repaid"),
    "owner": lambda: _("Owner money put in and taken out"),
    "opening": lambda: _("Opening balances"),
    "revaluation": lambda: _("Currency revaluation"),
    "transfers": lambda: _("Transfers and currency exchange"),
}


def _cash_flow_view(flow: dict, fmt: Fmt, compare: bool) -> dict:
    sections = []
    for row in flow["sections"]:
        if row["key"] not in ("operating",) and not (row["income"] or row["expense"]):
            continue
        sections.append(
            {
                "key": row["key"],
                "name": FLOW_LABELS[row["key"]](),
                "money_in": fmt.n(row["income"]),
                "money_out": fmt.n(-row["expense"]) if row["expense"] else fmt.n(ZERO),
                "net": fmt.n(row["net"]),
            }
        )
    months = [
        {
            "name": f"{fmt.month(date.fromisoformat(point['date']))}",
            "money_in": fmt.n(point["income"]),
            "money_out": fmt.n(-point["expense"]) if point["expense"] else fmt.n(ZERO),
            "net": fmt.n(point["net"]),
        }
        for point in flow["series"]
    ]
    return {
        "start_cash": fmt.n(flow["start_cash"], dash=False),
        "end_cash": fmt.n(flow["end_cash"], dash=False),
        "sections": sections,
        "months": months if len(months) > 1 else [],
        "totals": {
            "money_in": fmt.n(flow["totals"]["income"]),
            "money_out": fmt.n(-flow["totals"]["expense"]),
            "net": fmt.n(flow["totals"]["net"]),
        },
        "previous": (
            {
                "money_in": fmt.n(flow["previous"]["income"]),
                "money_out": fmt.n(-flow["previous"]["expense"]),
                "net": fmt.n(flow["previous"]["net"]),
            }
            if compare and flow.get("previous")
            else None
        ),
    }


# The balance sheet --------------------------------------------------------------------------------


def line_label(key: str) -> str:
    """The name of a balance sheet line, section or reconciliation line."""
    labels = {
        "cash": _("Cash and bank"),
        "cash_on_hand": _("Cash in the tills and safes"),
        "bank": _("Bank accounts and cards"),
        "in_transit": _("Card payments on their way to the bank"),
        "receivables": _("Owed to the business"),
        "customers": _("Customers"),
        "staff_owe_us": _("Staff advances"),
        "loans_given": _("Loans given"),
        "other_receivable": _("Other money owed to us"),
        "stock": _("Stock"),
        "stock_at_cost": _("Medicines and goods at cost"),
        "fixed_assets": _("Fixed assets"),
        "fixed_assets_book": _("Equipment and fit-out at book value"),
        "current": _("Due within a year"),
        "long_term": _("Due later"),
        "suppliers": _("Suppliers"),
        "loans_current": _("Loans, due within a year"),
        "loans_long": _("Loans, due after a year"),
        "taxes": _("Taxes owed"),
        "staff": _("Owed to staff"),
        "dividends": _("Dividends declared, not paid yet"),
        "other_payable": _("Other money we owe"),
        "owner_put_in": _("Owner money put in"),
        "owner_taken_out": _("Owner money taken out"),
        "retained": _("Retained earnings"),
        "net_assets": _("Net assets of these branches"),
        "profit_recorded": _("Profit recorded since the books started"),
        "opening_balances": _("Balances brought in when the books started"),
        "older_fixed_assets": _("Fixed assets owned before the books started"),
        "revaluation": _("Revaluation of foreign money"),
        "dividends_declared": _("Dividends declared, not paid yet"),
    }
    return labels.get(key, key)


def _balance_view(sheet: dict, before: dict | None, fmt: Fmt) -> dict:
    def previous_lines(side: str) -> dict:
        if before is None:
            return {}
        found = {}
        for section in before[side]["sections"]:
            found[section["key"]] = section["total"]
            for line in section["lines"]:
                found[line["key"]] = line["amount"]
        return found

    def side(key: str) -> list[dict]:
        old = previous_lines(key)
        sections = []
        for section in sheet[key]["sections"]:
            sections.append(
                {
                    "name": line_label(section["key"]),
                    "total": fmt.n(section["total"], dash=False),
                    "previous": fmt.n(old.get(section["key"])) if before else None,
                    "lines": [
                        {
                            "name": line_label(line["key"]),
                            "amount": fmt.n(line["amount"]),
                            "previous": fmt.n(old.get(line["key"])) if before else None,
                        }
                        for line in section["lines"]
                    ],
                }
            )
        return sections

    equity_before = {}
    if before is not None:
        equity_before = {line["key"]: line["amount"] for line in before["equity"]["lines"]}
    return {
        "on": fmt.day(sheet["on"]),
        "before_on": fmt.day(before["on"]) if before else None,
        "assets": side("assets"),
        "assets_total": fmt.n(sheet["assets"]["total"], dash=False),
        "assets_previous": fmt.n(before["assets"]["total"]) if before else None,
        "liabilities": side("liabilities"),
        "liabilities_total": fmt.n(sheet["liabilities"]["total"], dash=False),
        "liabilities_previous": fmt.n(before["liabilities"]["total"]) if before else None,
        "equity": [
            {
                "name": line_label(line["key"]),
                "amount": fmt.n(line["amount"]),
                "previous": fmt.n(equity_before.get(line["key"])) if before else None,
            }
            for line in sheet["equity"]["lines"]
        ],
        "equity_total": fmt.n(sheet["equity"]["total"], dash=False),
        "equity_previous": fmt.n(before["equity"]["total"]) if before else None,
        "total": fmt.n(sheet["check"]["liabilities_and_equity"], dash=False),
        "balanced": sheet["check"]["balanced"],
        "whole_company": sheet["whole_company"],
    }


# Loans --------------------------------------------------------------------------------------------


def _loans(company, start: date, end: date, *, branch_ids, fmt: Fmt) -> dict:
    """Loans the business owes on `end`: what is left, the next payments, and what was paid
    in the period (principal and interest)."""
    from apps.finance.models import DebtInstallment

    rows = []
    total_left = principal = interest = ZERO
    for debt, left in statements._debts_on(company, end, branch_ids=branch_ids):
        if debt.direction != Debt.Direction.PAYABLE or debt.kind != Debt.Kind.LOAN:
            continue
        left_value = queries.book_value(debt, left)
        total_left += left_value
        posted = Transaction.objects.filter(
            debt=debt, status=Transaction.Status.POSTED, occurred_on__range=(start, end)
        )
        paid = -sum(
            (row.base_amount for row in posted.filter(kind=Transaction.Kind.DEBT_PAYMENT)), ZERO
        )
        charged = -sum(
            (
                row.base_amount
                for row in posted.filter(kind=Transaction.Kind.EXPENSE, category__isnull=False)
            ),
            ZERO,
        )
        principal += paid
        interest += charged
        covered = debt.amount - left
        upcoming = []
        for installment in DebtInstallment.objects.filter(debt=debt).order_by("due_on", "pk"):
            share = min(covered, installment.amount)
            covered -= share
            rest = installment.amount - share
            if rest > 0 and installment.due_on > end and len(upcoming) < 3:
                upcoming.append(
                    f"{fmt.day(installment.due_on)}: {fmt.n(queries.book_value(debt, rest))}"
                )
        if not upcoming and debt.due_on:
            upcoming.append(f"{fmt.day(debt.due_on)}: {fmt.n(left_value)}")
        rows.append(
            {
                "lender": debt.counterparty.name if debt.counterparty_id else _("Staff"),
                "description": debt.description,
                "issued_on": fmt.day(debt.issued_on),
                "amount": fmt.n(queries.book_value(debt, debt.amount)),
                "currency": debt.currency if debt.currency != company.base_currency else "",
                "left": fmt.n(left_value),
                "due_on": fmt.day(debt.due_on),
                "next": upcoming,
                "paid": fmt.n(paid),
                "interest": fmt.n(charged),
            }
        )
    return {
        "rows": rows,
        "left": fmt.n(total_left),
        "paid": fmt.n(principal),
        "interest": fmt.n(interest),
        "raw": {"left": total_left, "paid": principal, "interest": interest},
    }


# Partners and dividends ---------------------------------------------------------------------------


def _partners_view(company, start: date, end: date, fmt: Fmt) -> dict | None:
    people = partners.partners_on(company, end)
    share = partners.profit_share(company, start, end)
    if not people and not share["partners"]:
        return None
    rounds = []
    for dividend in partners.dividends(company).filter(
        period_end__gte=start, period_start__lte=end
    ):
        status = partners.state(dividend)
        rounds.append(
            {
                "period": _("%(start)s – %(end)s")
                % {"start": fmt.day(dividend.period_start), "end": fmt.day(dividend.period_end)},
                "amount": fmt.n(dividend.amount),
                "status": str(Dividend.Status(status).label),
            }
        )
    return {
        "profit": fmt.n(share["profit"], dash=False),
        "rows": [
            {
                "name": row["name"],
                "share": fmt.pct(row["share"]),
                "profit": fmt.n(row["profit"]),
                "paid": fmt.n(row["dividends_paid"]),
                "due": fmt.n(row["dividends_due"]),
            }
            for row in share["partners"]
        ],
        "unassigned": fmt.pct(share["unassigned_share"]) if share["unassigned_share"] else None,
        "rounds": rounds,
    }


# What the business is worth -----------------------------------------------------------------------


def _width(left: str, right: str) -> str:
    """The width of a range bar in percent, never thinner than a hairline."""
    return f"{max(Decimal(right) - Decimal(left), Decimal('0.8')):.1f}"


def _valuation_view(worth: dict, fmt: Fmt) -> dict:
    made = worth["earnings"]
    method = worth["earnings_method"]
    labels = {
        "profit": _("Net profit"),
        "depreciation": _("Plus depreciation of fixed assets"),
        "interest": _("Plus interest on loans"),
        "equipment": _("Plus equipment bought and booked as a cost"),
    }
    lines = [
        {"name": labels[line["key"]], "amount": fmt.n(line["amount"])}
        for line in made["lines"]
        if line["key"] == "profit" or line["amount"]
    ]
    scaled = made["yearly"] is not None and made["days"] < statements.YEAR_DAYS
    reason = None
    if method["reason"] == "too_early":
        reason = ngettext(
            "The books cover only %(days)s day: too short to judge yearly earnings.",
            "The books cover only %(days)s days: too short to judge yearly earnings.",
            made["days"],
        ) % {"days": made["days"]}
    elif method["reason"] == "loss":
        reason = _(
            "The business made no profit over this time, so the earnings method gives no value."
        )
    net = worth["net_assets"]
    values = [net["value"]]
    if method["applies"]:
        values += [method["low"], method["high"]]
    scale_max = max((abs(v) for v in values), default=ZERO) or Decimal(1)

    def bar(value) -> str:
        return f"{max(min(Decimal(value) / scale_max * HUNDRED, HUNDRED), ZERO):.1f}"

    chart = []
    if method["applies"]:
        chart.append(
            {
                "name": _("Earnings"),
                "left": bar(method["low"]),
                "width": _width(bar(method["low"]), bar(method["high"])),
                "text": f"{fmt.n(method['low'])} – {fmt.n(method['high'])}",
                "range": True,
            }
        )
    chart.append(
        {
            "name": _("Net assets"),
            "left": bar(net["value"]),
            "width": "0",
            "text": fmt.n(net["value"]),
            "range": False,
        }
    )
    return {
        "range_low": fmt.money(worth["range"]["low"]),
        "range_high": fmt.money(worth["range"]["high"]),
        "single": worth["range"]["low"] == worth["range"]["high"],
        "earnings_from": fmt.day(made["from"]),
        "earnings_to": fmt.day(made["to"]),
        "earnings_days": made["days"],
        "lines": lines,
        "earnings": fmt.n(made["earnings"]),
        "yearly": fmt.n(made["yearly"]) if made["yearly"] is not None else None,
        "scaled": scaled,
        "applies": method["applies"],
        "reason": reason,
        "multiple_low": fmt.times(worth["multiple_low"]),
        "multiple_high": fmt.times(worth["multiple_high"]),
        "is_default": (worth["multiple_low"], worth["multiple_high"])
        == (worth["default_low"], worth["default_high"]),
        "business_low": fmt.n(method["business_low"]),
        "business_high": fmt.n(method["business_high"]),
        "cash": fmt.n(method["cash"]),
        "debt": fmt.n(method["debt"]),
        "low": fmt.n(method["low"]),
        "high": fmt.n(method["high"]),
        "net_assets": fmt.n(net["value"], dash=False),
        "assets": fmt.n(net["assets"]),
        "liabilities": fmt.n(net["liabilities"]),
        "stock": fmt.n(net["stock"]) if net["stock"] is not None else None,
        "fixed_assets": fmt.n(net["fixed_assets"]) if net["fixed_assets"] is not None else None,
        "chart": chart,
        "net_above": method["applies"] and net["value"] > method["high"],
    }


# The summary --------------------------------------------------------------------------------------


def _summary(
    company,
    *,
    start,
    end,
    books_start,
    branch_ids,
    fmt: Fmt,
    pnl,
    pnl_view,
    flow,
    sheet,
    loans,
) -> dict:
    revenue = pnl["income"]["total"]
    profit = pnl["profit"]["total"]
    receivable = _section_total(sheet["assets"]["sections"], "receivables")
    stock = _section_total(sheet["assets"]["sections"], "stock")
    cash = _section_total(sheet["assets"]["sections"], "cash")
    owed = sheet["liabilities"]["total"]
    tiles = [
        {"label": _("Revenue"), "value": fmt.n(revenue, dash=False), "hint": None},
        {
            "label": _("Net profit"),
            "value": fmt.n(profit, dash=False),
            "hint": _("Margin %(margin)s") % {"margin": fmt.pct(_ratio(profit, revenue))}
            if revenue
            else None,
        },
        {
            "label": _("Cash and bank"),
            "value": fmt.n(cash, dash=False),
            "hint": _("On %(day)s") % {"day": fmt.day(sheet["on"])},
        },
        {
            "label": _("Net assets")
            if sheet["whole_company"]
            else _("Net assets of these branches"),
            "value": fmt.n(sheet["equity"]["total"], dash=False),
            "hint": None,
        },
        {"label": _("Owed to the business"), "value": fmt.n(receivable, dash=False), "hint": None},
        {"label": _("The business owes"), "value": fmt.n(owed, dash=False), "hint": None},
        {"label": _("Loans left"), "value": fmt.n(loans["raw"]["left"], dash=False), "hint": None},
        {
            "label": _("Stock at cost"),
            "value": fmt.n(stock, dash=False) if stock is not None else DASH,
            "hint": None,
        },
    ]
    # Twelve months of trend up to the period's end, from the month the books started.
    trend_start = _add_months(date(end.year, end.month, 1), -(TREND_MONTHS - 1))
    if books_start is not None and books_start > trend_start:
        trend_start = date(books_start.year, books_start.month, 1)
    series = queries.totals(company, trend_start, end, "month", branch_ids=branch_ids)["series"]
    chart, trend = _trend(series, fmt)
    current_ratio = None
    if sheet["current_liabilities"]:
        current_ratio = sheet["current_assets"] / sheet["current_liabilities"]
    debt_to_equity = None
    if sheet["equity"]["total"] > 0:
        debt_to_equity = sheet["liabilities"]["total"] / sheet["equity"]["total"]
    months = max(Decimal((end - start).days + 1) / Decimal("30.4"), Decimal(1))
    operating = next((row for row in flow["sections"] if row["key"] == "operating"), None)
    monthly_out = operating["expense"] / months if operating and operating["expense"] else None
    cash_months = cash / monthly_out if monthly_out else None
    service = loans["raw"]["paid"] + loans["raw"]["interest"]
    coverage = None
    if service > 0:
        earned = pnl_view["operating"] + loans["raw"]["interest"]
        coverage = earned / service
    ratios = [
        (
            _("Gross margin"),
            fmt.pct(pnl_view["gross_margin"]),
            _("Revenue less the cost of goods, as a share of revenue."),
        ),
        (_("Net margin"), fmt.pct(_ratio(profit, revenue)), _("Net profit as a share of revenue.")),
        (
            _("Current ratio"),
            fmt.times(current_ratio),
            _("Cash, money owed to us and stock for each so‘m due within a year."),
        ),
        (
            _("Liabilities to net assets"),
            fmt.times(debt_to_equity),
            _("Everything the business owes for each so‘m of net assets."),
        ),
        (
            _("Cash cover"),
            ngettext("%(months)s month", "%(months)s months", _plural(cash_months))
            % {"months": fmt.decimal(cash_months)}
            if cash_months is not None
            else DASH,
            _("How many months of running payments the cash would pay for."),
        ),
    ]
    if coverage is not None:
        ratios.append(
            (
                _("Debt service cover"),
                fmt.times(coverage),
                _("Operating profit before interest for each so‘m of loan payments in the period."),
            )
        )
    return {
        "tiles": tiles,
        "trend": trend,
        "chart": chart,
        "ratios": ratios,
        "has_trend": len(trend) > 1,
    }


CHART_MM = Decimal(40)


def _trend(series: list[dict], fmt: Fmt) -> tuple[dict, list[dict]]:
    """Bar heights in millimetres: revenue and profit grow up from the axis, a loss hangs
    below it, on one scale."""
    up = max((max(Decimal(p["income"]), Decimal(p["profit"]), ZERO) for p in series), default=ZERO)
    down = max((max(-Decimal(p["profit"]), ZERO) for p in series), default=ZERO)
    scale = (up + down) or Decimal(1)
    up_mm = (CHART_MM * up / scale).quantize(Decimal("0.1"))
    down_mm = (CHART_MM * down / scale).quantize(Decimal("0.1"))

    def mm(value) -> str:
        return f"{max(CHART_MM * Decimal(value) / scale, ZERO):.1f}"

    trend = [
        {
            "label": fmt.short_month(date.fromisoformat(point["date"])),
            "revenue_mm": mm(point["income"]),
            "profit_mm": mm(point["profit"]) if point["profit"] > 0 else "0",
            "loss_mm": mm(-point["profit"]) if point["profit"] < 0 else "0",
            "loss": point["profit"] < 0,
            "revenue_text": _compact(point["income"], fmt),
            "profit_text": _compact(point["profit"], fmt),
        }
        for point in series
    ]
    return {"up": f"{up_mm}", "down": f"{down_mm}" if down else ""}, trend


def _plural(value) -> int:
    """The number ngettext picks a form by: a whole number of the value."""
    return int(abs(Decimal(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _compact(value, fmt: Fmt) -> str:
    """ "12.4M" style labels for the chart, in the language's words."""
    value = Decimal(value)
    millions = value / Decimal(1_000_000)
    if abs(millions) >= 1:
        text = f"{millions.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}"
        unit = {"uz": "mln", "ru": "млн", "en": "M"}[fmt.language]
    else:
        text = f"{(value / 1000).quantize(Decimal(1), rounding=ROUND_HALF_UP)}"
        unit = {"uz": "ming", "ru": "тыс.", "en": "K"}[fmt.language]
    if fmt.language != "en":
        text = text.replace(".", ",")
    text = text.replace("-", "−")
    return f"{text}{NBSP}{unit}" if fmt.language != "en" else f"{text}{unit}"


def _section_total(sections: list[dict], key: str) -> Decimal | None:
    for section in sections:
        if section["key"] == key:
            return section["total"]
    return None


# Notes --------------------------------------------------------------------------------------------


def _notes(company, *, start, end, branch_ids, fmt: Fmt, sheet, books_start, compare) -> dict:
    receivable, payable = _largest(company, end, branch_ids=branch_ids, fmt=fmt)
    fixed = None
    if company.has_feature("assets"):
        from apps.assets import queries as asset_queries

        report = asset_queries.movement(company, branch_ids=branch_ids, start=start, end=end)
        if report["lines"]:
            fixed = {
                "rows": [
                    {
                        "name": line["name"],
                        "open": fmt.n(line["open_book"]),
                        "added": fmt.n(line["in_cost"]),
                        "depreciation": fmt.n(-line["depreciation"] - line["written_down"]),
                        "out": fmt.n(-(line["out_cost"] - line["out_depreciation"])),
                        "close": fmt.n(line["close_book"]),
                    }
                    for line in report["lines"]
                    if any(
                        line[key]
                        for key in (
                            "open_book",
                            "in_cost",
                            "depreciation",
                            "out_cost",
                            "close_book",
                        )
                    )
                ],
                "total": {
                    "open": fmt.n(report["total"]["open_book"]),
                    "added": fmt.n(report["total"]["in_cost"]),
                    "depreciation": fmt.n(
                        -report["total"]["depreciation"] - report["total"]["written_down"]
                    ),
                    "out": fmt.n(
                        -(report["total"]["out_cost"] - report["total"]["out_depreciation"])
                    ),
                    "close": fmt.n(report["total"]["close_book"]),
                },
            }
    foreign = [
        {
            "currency": row["currency"],
            "amount": fmt.amount(row["amount"], row["currency"]),
            "rate": fmt.rate(row["rate"]),
            "rate_date": fmt.day(row["rate_date"]),
            "base": fmt.n(row["base"]),
            "stale": row["stale"],
        }
        for row in sheet["foreign"]
    ]
    reconciliation = None
    if sheet["reconciliation"] is not None:
        reconciliation = {
            "lines": [
                {"name": line_label(line["key"]), "amount": fmt.n(line["amount"])}
                for line in sheet["reconciliation"]["lines"]
            ],
            "retained": fmt.n(sheet["reconciliation"]["retained"], dash=False),
            "unexplained": fmt.n(sheet["reconciliation"]["unexplained"])
            if abs(sheet["reconciliation"]["unexplained"]) >= 1
            else None,
        }
    basis = [
        _(
            "Prepared from the company's own records in Daybook. The figures are not audited "
            "and are not an official tax report."
        ),
        _(
            "Amounts are in %(currency)s; money in another currency is valued at the company's "
            "rate on the day the statement is made up to."
        )
        % {"currency": fmt.unit},
        _(
            "Medicines and goods count as a cost when they arrive; the stock still on the "
            "shelves is shown at cost in the balance sheet."
        ),
        _(
            "Fixed assets bought through the books are spread over their useful life as "
            "depreciation."
        ),
        _("Owner money put in or taken out is never income or a cost."),
    ]
    if books_start is not None:
        basis.append(_("The books here start on %(day)s.") % {"day": fmt.day(books_start)})
    if compare is None:
        basis.append(_("The books don't go back to the same period a year before."))
    if sheet["rate"]["rate"] is not None and sheet["foreign"]:
        basis.append(
            _("USD rate used: %(rate)s on %(day)s.")
            % {"rate": fmt.rate(sheet["rate"]["rate"]), "day": fmt.day(sheet["rate"]["date"])}
        )
    return {
        "basis": basis,
        "receivable": receivable,
        "payable": payable,
        "fixed": fixed,
        "foreign": foreign,
        "reconciliation": reconciliation,
        "accounts": [
            {
                "name": row["name"],
                "currency": row["currency"],
                "balance": fmt.amount(row["balance"], row["currency"])
                if row["currency"] != company.base_currency
                else fmt.n(row["balance"]),
                "base": fmt.n(row["base"]),
            }
            for row in sheet["accounts"]
            if row["balance"]
        ],
        "gaps": [gap_text(gap, fmt) for gap in sheet["gaps"]],
    }


def _largest(company, end: date, *, branch_ids, fmt: Fmt) -> tuple[list[dict], list[dict]]:
    """The largest debts both ways on `end` (loans have their own note); what staff owe or are
    owed is one line, never by name: the pack goes outside the company."""
    groups: dict[tuple, dict] = {}
    for debt, left in statements._debts_on(company, end, branch_ids=branch_ids):
        if debt.kind == Debt.Kind.LOAN and debt.direction == Debt.Direction.PAYABLE:
            continue
        value = queries.book_value(debt, left)
        if debt.membership_id is not None:
            key = (debt.direction, "staff", 0)
            name = _("Staff")
        else:
            key = (debt.direction, "party", debt.counterparty_id)
            name = debt.counterparty.name
        entry = groups.setdefault(
            key, {"name": name, "amount": ZERO, "count": 0, "overdue": ZERO, "oldest_due": None}
        )
        entry["amount"] += value
        entry["count"] += 1
        if debt.due_on is not None and debt.due_on < end:
            entry["overdue"] += value
        if debt.due_on and (entry["oldest_due"] is None or debt.due_on < entry["oldest_due"]):
            entry["oldest_due"] = debt.due_on

    def top(direction: str) -> list[dict]:
        rows = sorted(
            (entry for key, entry in groups.items() if key[0] == direction),
            key=lambda entry: entry["amount"],
            reverse=True,
        )[:TOP_DEBTS]
        return [
            {
                "name": row["name"],
                "amount": fmt.n(row["amount"]),
                "count": row["count"],
                "overdue": fmt.n(row["overdue"]),
                "due": fmt.day(row["oldest_due"]),
            }
            for row in rows
        ]

    return top(Debt.Direction.RECEIVABLE), top(Debt.Direction.PAYABLE)


def gap_text(gap: dict, fmt: Fmt) -> str:
    """What a gap of the books means, in plain words."""
    params = gap["params"]
    key = gap["key"]
    if key == "no_books":
        return _("Nothing has been recorded in the books yet.")
    if key == "no_opening":
        return _(
            "No opening balances were entered: money and debts from before %(day)s are missing."
        ) % {"day": fmt.day(params["day"])}
    if key == "no_rate":
        return _("No exchange rate was found for %(currencies)s: that money is left out.") % {
            "currencies": ", ".join(params["currencies"])
        }
    if key == "negative_account":
        return _(
            "%(account)s is below zero on that day: an entry of money coming in is probably "
            "missing."
        ) % {"account": params["account"]}
    if key == "no_stock_module":
        return _("Stock isn't kept in Daybook: the medicines on the shelves are not counted.")
    if key == "stock_history":
        return _("The stock history before that day is incomplete: stock is shown as zero.")
    if key == "no_assets_module":
        if params.get("equipment"):
            return _(
                "Fixed assets aren't kept in Daybook: equipment bought for %(amount)s was "
                "booked as a cost and is not among the assets."
            ) % {"amount": fmt.money(params["equipment"])}
        return _("Fixed assets aren't kept in Daybook: equipment is not among the assets.")
    if key == "pending":
        return ngettext(
            "%(count)s entry of %(amount)s waits for approval and is not included.",
            "%(count)s entries of %(amount)s wait for approval and are not included.",
            params["count"],
        ) % {"count": params["count"], "amount": fmt.money(params["amount"])}
    if key == "unexplained":
        return _(
            "%(amount)s of retained earnings can't be traced to the books: check the opening "
            "balances and transfers."
        ) % {"amount": fmt.money(params["amount"])}
    return key
