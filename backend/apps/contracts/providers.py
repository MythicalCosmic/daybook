"""What business contracts give the shared registries (`hooks.py` registers them):

    may_open_file      `contracts.file`: who may open a contract's file at download time
    calendar_events    the agenda: ends, renewals and notice deadlines
    search             the command palette
    decision_count/_items   Egasi paneli's "waits for your decision": renewals to decide
    lease_ending       the insight rule: a lease ending (or due for its renewal decision)
                       within 60 days, with `lease_ending_texts` its words

Reading needs `finance.view` (contracts carry rent and payments); changing them `finance.view`
and `finance.manage`, as Finance's recurring payments do.
"""

from __future__ import annotations

from datetime import date

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext

from apps.console.perms import AllOf, holds
from apps.console.registry import CalendarItem, QueueAction, QueueItem, SearchHit
from apps.contracts import conf, queries, services
from apps.contracts.models import BusinessContract, ContractFile
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm

READ = Perm.FINANCE_VIEW
MANAGE = AllOf(Perm.FINANCE_VIEW, Perm.FINANCE_MANAGE)
IN_FORCE = BusinessContract.IN_FORCE


def _url(contract: BusinessContract) -> str:
    return f"/c/{contract.company_id}/contracts/{contract.pk}"


def _name(contract: BusinessContract) -> str:
    return f"{contract.title} ({contract.branch.name})" if contract.branch_id else contract.title


# Files ------------------------------------------------------------------------------------------


def may_open_file(user, company_id: int, file_id: int) -> bool:
    """`contracts.file`: whoever may read contracts and sees the contract's branch."""
    row = (
        ContractFile.objects.filter(company_id=company_id, pk=file_id)
        .select_related("contract")
        .first()
    )
    if row is None:
        return False
    viewer = (
        Membership.objects.filter(
            company_id=company_id, user=user, status=Membership.Status.APPROVED
        )
        .select_related("role", "company")
        .first()
    )
    if viewer is None or not holds(viewer, READ):
        return False
    return scope.allows(scope.branch_ids(viewer), row.contract.branch_id)


# The agenda -------------------------------------------------------------------------------------


def calendar_events(company, start: date, end: date, member: Membership) -> list[CalendarItem]:
    items: list[CalendarItem] = []
    rows = (
        queries.visible(member)
        .filter(status__in=IN_FORCE, ends_on__isnull=False)
        .select_related("branch")
    )
    for contract in rows:
        name = _name(contract)
        if start <= contract.ends_on <= end:
            renews = contract.auto_renews and contract.terminated_on is None
            items.append(
                CalendarItem(
                    id=f"end:{contract.pk}",
                    kind="contracts.renews" if renews else "contracts.end",
                    title=(
                        _("Contract renews: %(contract)s")
                        if renews
                        else _("Contract ends: %(contract)s")
                    )
                    % {"contract": name},
                    start=contract.ends_on,
                    end=None,
                    all_day=True,
                    color="info" if renews else "danger",
                    url=_url(contract),
                )
            )
        deadline = contract.notice_deadline
        if deadline is not None and start <= deadline <= end:
            items.append(
                CalendarItem(
                    id=f"notice:{contract.pk}",
                    kind="contracts.notice",
                    title=_("Notice deadline: %(contract)s") % {"contract": name},
                    start=deadline,
                    end=None,
                    all_day=True,
                    color="warning",
                    url=_url(contract),
                )
            )
    return items


# Search -----------------------------------------------------------------------------------------


def search(member: Membership, q: str, limit: int) -> list[SearchHit]:
    from django.db.models import Q

    text = (q or "").strip()
    if not text:
        return []
    rows = (
        queries.visible(member)
        .filter(
            Q(title__icontains=text)
            | Q(number__icontains=text)
            | Q(counterparty__name__icontains=text)
        )
        .select_related("branch", "counterparty")
        .order_by("status", "ends_on", "title")[:limit]
    )
    hits = []
    for contract in rows:
        parts = [
            str(contract.get_kind_display()),
            contract.counterparty.name if contract.counterparty_id else "",
            contract.number,
            contract.ends_on.strftime("%d.%m.%Y") if contract.ends_on else "",
        ]
        hits.append(
            SearchHit(
                type="contracts.contract",
                id=contract.pk,
                title=contract.title,
                subtitle=" · ".join(part for part in parts if part),
                url=_url(contract),
            )
        )
    return hits


# Decisions (Egasi paneli) -----------------------------------------------------------------------


def _renewals(member: Membership) -> list[BusinessContract]:
    company = member.company
    settings = conf.get_settings(company)
    today = services.local_today(company)
    rows = (
        queries.visible(member)
        .filter(status__in=IN_FORCE, auto_renews=True, ends_on__isnull=False)
        .select_related("branch", "counterparty")
    )
    found = [row for row in rows if services.notice_due(row, today, settings.notice_remind_days)]
    return sorted(found, key=lambda row: (row.notice_deadline, row.title))


def decision_count(member: Membership) -> int:
    return len(_renewals(member))


def decision_items(member: Membership, limit: int) -> list[QueueItem]:
    items = []
    for contract in _renewals(member)[:limit]:
        party = contract.counterparty.name if contract.counterparty_id else ""
        subtitle = _("Notice by %(day)s, or it renews after %(renews)s") % {
            "day": contract.notice_deadline.strftime("%d.%m.%Y"),
            "renews": contract.ends_on.strftime("%d.%m.%Y"),
        }
        items.append(
            QueueItem(
                kind="contracts.renewals",
                id=contract.pk,
                title=f"{_name(contract)} · {party}" if party else _name(contract),
                subtitle=subtitle,
                created_at=None,
                url=_url(contract),
                actions=(
                    QueueAction(
                        key="keep",
                        label=_("Keep it renewing"),
                        style="primary",
                        method="POST",
                        endpoint=f"contracts/{contract.pk}/keep-renewing/",
                    ),
                    QueueAction(
                        key="stop",
                        label=_("We give notice"),
                        style="danger",
                        method="POST",
                        endpoint=f"contracts/{contract.pk}/stop-renewing/",
                    ),
                ),
            )
        )
    return items


# The briefing and Get started -------------------------------------------------------------------

BRIEF_LINES = 3


def brief_section(company, day: date, now, branch_ids: list[int] | None) -> dict | None:
    """What the contracts need soon: those ending within the warning days and the renewals to
    decide before their notice deadline, soonest first. Nothing when all is well."""
    found = queries.attention(company, branch_ids=branch_ids, today=day)
    if not found:
        return None
    settings = conf.get_settings(company)
    lines = []
    for contract in found[:BRIEF_LINES]:
        name = _name(contract)
        if services.notice_due(contract, day, settings.notice_remind_days):
            text = _("%(contract)s: notice deadline %(day)s") % {
                "contract": name,
                "day": contract.notice_deadline.strftime("%d.%m.%Y"),
            }
        else:
            text = _("%(contract)s ends %(day)s") % {
                "contract": name,
                "day": contract.ends_on.strftime("%d.%m.%Y"),
            }
        lines.append(text)
    rest = len(found) - BRIEF_LINES
    if rest > 0:
        lines.append(
            ngettext("And %(count)d more contract", "And %(count)d more contracts", rest)
            % {"count": rest}
        )
    return {"title": _("Contracts"), "lines": lines}


def setup_done(company) -> bool:
    return BusinessContract.objects.for_company(company).exists()


# The export -------------------------------------------------------------------------------------

REGISTER_COLUMNS = (
    ("title", gettext_lazy("Contract")),
    ("kind", gettext_lazy("Kind")),
    ("counterparty", gettext_lazy("Party")),
    ("number", gettext_lazy("Number")),
    ("branch", gettext_lazy("Branch")),
    ("status", gettext_lazy("Status")),
    ("signed_on", gettext_lazy("Signed"), "date"),
    ("starts_on", gettext_lazy("Starts"), "date"),
    ("ends_on", gettext_lazy("Ends"), "date"),
    ("auto_renews", gettext_lazy("Renews by itself"), "bool"),
    ("notice_deadline", gettext_lazy("Notice deadline"), "date"),
    ("amount", gettext_lazy("Amount"), "money"),
    ("currency", gettext_lazy("Currency")),
    ("period", gettext_lazy("Paid")),
    ("per_month", gettext_lazy("A month"), "money"),
    ("in_forecast", gettext_lazy("In the cash forecast"), "bool"),
    ("responsible", gettext_lazy("Looks after it")),
    ("files", gettext_lazy("Files"), "number"),
    ("notes", gettext_lazy("Notes")),
)


def register_rows(member: Membership, params: dict):
    """Every contract in the caller's branch scope, soonest end first."""
    from django.db.models import Count

    rows = (
        queries.visible(member)
        .select_related("branch", "counterparty", "responsible")
        .annotate(file_count=Count("files"))
        .order_by("ends_on", "title", "pk")
    )
    for contract in rows:
        yield {
            "title": contract.title,
            "kind": contract.get_kind_display(),
            "counterparty": contract.counterparty.name if contract.counterparty_id else "",
            "number": contract.number,
            "branch": contract.branch.name if contract.branch_id else "",
            "status": contract.get_status_display(),
            "signed_on": contract.signed_on,
            "starts_on": contract.starts_on,
            "ends_on": contract.ends_on,
            "auto_renews": contract.auto_renews,
            "notice_deadline": contract.notice_deadline,
            "amount": contract.amount,
            "currency": contract.currency,
            "period": contract.get_period_display(),
            "per_month": queries.per_month(contract),
            "in_forecast": contract.in_forecast,
            "responsible": str(contract.responsible) if contract.responsible_id else "",
            "files": contract.file_count,
            "notes": contract.notes,
        }


# The insight ------------------------------------------------------------------------------------

LEASE_KIND = "contracts_lease_ending"  # Insight.Kind.CONTRACTS_LEASE_ENDING
LEASE_WINDOW = 60  # days
LEASE_WARNING = 30  # days: amber from here, blue before


def lease_ending(ctx) -> list:
    """Leases in force that end within 60 days, or (renewing by themselves) whose notice
    deadline is within 60 days and not decided: one finding per lease and end date."""
    from apps.insights.detectors import Finding
    from apps.insights.models import Insight

    today = ctx.today
    rows = (
        BusinessContract.objects.for_company(ctx.company)
        .filter(kind=BusinessContract.Kind.LEASE, status__in=IN_FORCE, ends_on__gte=today)
        .select_related("branch", "counterparty")
    )
    found = []
    for contract in rows:
        if contract.auto_renews and contract.terminated_on is None:
            deadline = contract.notice_deadline
            if contract.renewal_confirmed_for == contract.ends_on or deadline < today:
                continue
            days = (deadline - today).days
        else:
            deadline = None
            days = (contract.ends_on - today).days
        if days > LEASE_WINDOW:
            continue
        found.append(
            Finding(
                key=f"{LEASE_KIND}:{contract.pk}:{contract.ends_on.isoformat()}",
                severity=(
                    Insight.Severity.WARNING if days <= LEASE_WARNING else Insight.Severity.INFO
                ),
                metrics={
                    "days": days,
                    "ends_on": contract.ends_on.isoformat(),
                    "auto_renews": deadline is not None,
                    "notice_deadline": deadline.isoformat() if deadline else None,
                    "amount": str(contract.amount) if contract.amount else None,
                    "currency": contract.currency,
                    "period": contract.period,
                    "party": contract.counterparty.name if contract.counterparty_id else "",
                    "url": _url(contract),
                },
                branch_id=contract.branch_id,
                subject_type="businesscontract",
                subject_id=contract.pk,
                subject_label=contract.title,
                window_start=today,
                window_end=contract.ends_on,
            )
        )
    return found


def _period_amount(metrics: dict) -> str:
    from apps.insights import display

    amount = metrics.get("amount")
    if not amount:
        return ""
    money = display.money(amount, metrics.get("currency") or "UZS")
    period = metrics.get("period")
    if period == BusinessContract.Period.MONTHLY:
        return _("Rent: %(amount)s a month.") % {"amount": money}
    if period == BusinessContract.Period.QUARTERLY:
        return _("Rent: %(amount)s a quarter.") % {"amount": money}
    if period == BusinessContract.Period.YEARLY:
        return _("Rent: %(amount)s a year.") % {"amount": money}
    return ""


def lease_ending_texts(metrics: dict, branch: str, subject: str):
    """The words of a `contracts_lease_ending` insight (`apps.insights.texts.Texts`)."""
    from apps.insights import display
    from apps.insights.texts import Texts

    days = int(metrics.get("days") or 0)
    name = f"{subject} ({branch})" if branch else subject
    party = metrics.get("party") or ""
    rent = _period_amount(metrics)
    if metrics.get("auto_renews"):
        title = ngettext(
            "Lease renewal to decide in %(count)d day: %(lease)s",
            "Lease renewal to decide in %(count)d days: %(lease)s",
            days,
        ) % {"count": days, "lease": name}
        explanation = _(
            "It renews by itself after %(day)s unless you give notice by %(deadline)s."
        ) % {
            "day": display.day(metrics["ends_on"]),
            "deadline": display.day(metrics["notice_deadline"]),
        }
        action = _("Decide now: keep it, ask for a better rent, or give notice in writing.")
    else:
        title = ngettext(
            "Lease ends in %(count)d day: %(lease)s",
            "Lease ends in %(count)d days: %(lease)s",
            days,
        ) % {"count": days, "lease": name}
        if party:
            explanation = _("The lease with %(party)s ends on %(day)s.") % {
                "party": party,
                "day": display.day(metrics["ends_on"]),
            }
        else:
            explanation = _("The lease ends on %(day)s.") % {"day": display.day(metrics["ends_on"])}
        action = _(
            "Agree the renewal with the landlord now, or start looking for a new place: a move "
            "takes time."
        )
    if rent:
        explanation = f"{explanation} {rent}"
    return Texts(title=title, explanation=explanation, action=action)
