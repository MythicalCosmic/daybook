"""Excel/CSV exports of the finance ledger (`apps.exports.registry.register_exporter`).

`rows(member, params)` apply the member's branch scope and the same filters as the screens
(`params` are the page's own query parameters). Ledger rows and debts carry per-person detail,
so those exporters are `sensitive` (the dashboard warns before sending them to Telegram), and
salary-type rows keep their amount but lose the person without payroll access.
"""

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.exports.registry import Column
from apps.finance import access, filters, queries
from apps.finance.models import Debt
from apps.members import scope
from apps.reports.periods import RangeError, parse_range

TRANSACTION_COLUMNS = [
    Column("occurred_on", _("Date"), "date"),
    Column("kind", _("Kind")),
    Column("status", _("Status")),
    Column("account", _("Account")),
    Column("category", _("Category")),
    Column("counterparty", _("Counterparty")),
    Column("person", _("Person")),
    Column("branch", _("Branch")),
    Column("description", _("Description")),
    Column("amount", _("Amount"), "money"),
    Column("currency", _("Currency")),
    Column("rate", _("Rate"), "number"),
    Column("base_amount", _("Amount in base currency"), "money"),
    Column("recorded_by", _("Recorded by")),
    Column("source", _("Source")),
]

PNL_COLUMNS = [
    Column("period", _("Period")),
    Column("section", _("Section")),
    Column("category", _("Category")),
    Column("subcategory", _("Subcategory")),
    Column("amount", _("Amount"), "money"),
]

CASH_FLOW_COLUMNS = [
    Column("line", _("Line")),
    Column("money_in", _("Money in"), "money"),
    Column("money_out", _("Money out"), "money"),
    Column("net", _("Net"), "money"),
]

DEBT_COLUMNS = [
    Column("direction", _("Direction")),
    Column("kind", _("Kind")),
    Column("party", _("Who")),
    Column("issued_on", _("Issued"), "date"),
    Column("due_on", _("Due"), "date"),
    Column("currency", _("Currency")),
    Column("amount", _("Amount"), "money"),
    Column("paid", _("Paid"), "money"),
    Column("outstanding", _("Outstanding"), "money"),
    Column("days_overdue", _("Days overdue"), "number"),
    Column("status", _("Status")),
    Column("branch", _("Branch")),
    Column("responsible", _("Responsible")),
    Column("description", _("Description")),
]


def transaction_rows(member, params: dict):
    from apps.finance import sources

    parsed = filters.transaction_filters(params)
    parsed["mask_sensitive"] = not access.sees_salary_detail(member)
    rows = queries.filter_transactions(access.visible_transactions(member), parsed)
    rows = rows.select_related(
        "account", "category__parent", "counterparty", "membership", "branch", "created_by", "debt"
    ).order_by("-occurred_on", "-pk")
    for row in rows.iterator(chunk_size=500):
        masked = access.masks_row(member, row)
        yield {
            "occurred_on": row.occurred_on,
            "kind": str(row.get_kind_display()),
            "status": str(row.get_status_display()),
            "account": row.account.name if row.account_id else "",
            "category": _category_label(row.category),
            "counterparty": "" if masked or not row.counterparty_id else row.counterparty.name,
            "person": "" if masked or not row.membership_id else str(row.membership),
            "branch": row.branch.name if row.branch_id else "",
            "description": "" if masked else row.description,
            "amount": row.amount,
            "currency": row.currency,
            "rate": row.rate,
            "base_amount": row.base_amount,
            "recorded_by": str(row.created_by) if row.created_by_id else "",
            "source": str(sources.label(row.source_type)) if row.source_type else "",
        }


def _category_label(category) -> str:
    if category is None:
        return ""
    return f"{category.parent.name} › {category.name}" if category.parent_id else category.name


def _range(member, params: dict):
    try:
        return parse_range(params, member.company, timezone.now())
    except RangeError:
        return parse_range({}, member.company, timezone.now())


def _branches(member, params: dict):
    return access.branch_filter(scope.branch_ids(member), filters.ints(params, "branch"))


def pnl_rows(member, params: dict):
    range_ = _range(member, params)
    group = params.get("group") if params.get("group") in ("month", "quarter") else "month"
    data = queries.pnl(
        member.company, range_.start, range_.end, group, branch_ids=_branches(member, params)
    )
    labels = {"income": str(_("Income")), "expense": str(_("Expenses"))}
    for index, period in enumerate(data["periods"]):
        for section in ("income", "expense"):
            for node in data[section]["nodes"]:
                if node["children"]:
                    for child in node["children"]:
                        yield {
                            "period": period["key"],
                            "section": labels[section],
                            "category": node["name"],
                            "subcategory": child["name"],
                            "amount": child["amounts"][index],
                        }
                    if node["own"][index]:
                        yield {
                            "period": period["key"],
                            "section": labels[section],
                            "category": node["name"],
                            "subcategory": "",
                            "amount": node["own"][index],
                        }
                else:
                    yield {
                        "period": period["key"],
                        "section": labels[section],
                        "category": node["name"],
                        "subcategory": "",
                        "amount": node["amounts"][index],
                    }
        yield {
            "period": period["key"],
            "section": str(_("Profit")),
            "category": "",
            "subcategory": "",
            "amount": data["profit"]["amounts"][index],
        }


def cash_flow_rows(member, params: dict):
    range_ = _range(member, params)
    group = params.get("group")
    if group not in ("day", "week", "month"):
        group = queries.auto_group(range_.start, range_.end)
    data = queries.cash_flow(
        member.company, range_.start, range_.end, group, branch_ids=_branches(member, params)
    )
    yield {
        "line": str(_("Opening cash")),
        "money_in": None,
        "money_out": None,
        "net": data["start_cash"],
    }
    for point in data["series"]:
        yield {
            "line": point["date"],
            "money_in": point["income"],
            "money_out": point["expense"],
            "net": point["net"],
        }
    labels = {
        "operating": _("Operating"),
        "investing": _("Equipment and investments"),
        "financing": _("Loans"),
        "owner": _("Owner money"),
        "transfers": _("Transfers and exchange"),
        "opening": _("Opening balances"),
    }
    for section in data["sections"]:
        yield {
            "line": str(labels[section["key"]]),
            "money_in": section["income"],
            "money_out": section["expense"],
            "net": section["net"],
        }
    yield {
        "line": str(_("Closing cash")),
        "money_in": None,
        "money_out": None,
        "net": data["end_cash"],
    }


def debt_rows(member, params: dict):
    parsed = filters.debt_filters(params)
    today = queries.local_today(member.company)
    rows = access.visible_debts(member).select_related(
        "counterparty", "membership", "branch", "responsible", "company"
    )
    if parsed["direction"]:
        rows = rows.filter(direction=parsed["direction"])
    if "all" not in parsed["status"]:
        rows = rows.filter(status__in=parsed["status"])
    if parsed["kind"]:
        rows = rows.filter(kind__in=parsed["kind"])
    if parsed["overdue"]:
        rows = rows.filter(status=Debt.Status.OPEN, due_on__lt=today)
    for debt in rows.order_by("direction", "due_on", "pk").iterator(chunk_size=500):
        masked = access.masks_debt(member, debt)
        party = "" if masked else str(debt.counterparty or debt.membership)
        yield {
            "direction": str(debt.get_direction_display()),
            "kind": str(debt.get_kind_display()),
            "party": party,
            "issued_on": debt.issued_on,
            "due_on": debt.due_on,
            "currency": debt.currency,
            "amount": debt.amount,
            "paid": debt.paid,
            "outstanding": debt.amount - debt.paid,
            "days_overdue": queries.days_overdue(debt, today),
            "status": str(debt.get_status_display()),
            "branch": debt.branch.name if debt.branch_id else "",
            "responsible": str(debt.responsible) if debt.responsible_id else "",
            "description": "" if masked else debt.description,
        }
