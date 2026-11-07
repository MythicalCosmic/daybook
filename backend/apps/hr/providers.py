"""What HR hands the shared registries: file checks, inbox actions, the brief section and the
company calendar's dates."""

from datetime import date, timedelta

from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.console.registry import CalendarItem
from apps.core.exceptions import DomainError
from apps.hr import bot_messages, conf, coverage, overview, queries, services
from apps.hr.models import Celebration, Contract, DocumentKind, EmployeeDocument
from apps.members import scope
from apps.members.models import Membership

# The calendar shows a year at most per request.
CALENDAR_DAYS = 366


def may_open_document(user, company_id: int, document_id: int) -> bool:
    """`hr.document` files: the person's own (when shown to them, also while suspended), or
    anyone's for `hr.view` in scope (`hr.sensitive` for an ID). Every opening is audited."""
    document = (
        EmployeeDocument.objects.filter(company_id=company_id, pk=document_id)
        .select_related("membership__company")
        .first()
    )
    viewer = _viewer(user, company_id)
    if document is None or viewer is None:
        return False
    own = document.membership_id == viewer.pk
    if not own and viewer.status != Membership.Status.APPROVED:
        return False
    if not services.may_see_document(viewer, document):
        return False
    services.document_opened(document, user)
    return True


def may_open_contract(user, company_id: int, contract_id: int) -> bool:
    """`hr.contract` files: the person's own signed contract (also while suspended), or
    anyone's for `hr.view` in scope; one with the pay in it needs `payroll.view` too."""
    contract = Contract.objects.filter(company_id=company_id, pk=contract_id).first()
    viewer = _viewer(user, company_id)
    if contract is None or viewer is None:
        return False
    if contract.membership_id != viewer.pk and viewer.status != Membership.Status.APPROVED:
        return False
    return services.may_see_contract_file(viewer, contract)


def _viewer(user, company_id: int) -> Membership | None:
    return (
        Membership.objects.filter(company_id=company_id, user=user)
        .select_related("company", "role")
        .first()
    )


# Buttons on "probation ends" ----------------------------------------------------------------


def keep_from_inbox(notification, by: Membership, reason: str) -> str:
    services.pass_probation(_contract(notification), by=by)
    return bot_messages.probation_kept()


def extend_from_inbox(notification, by: Membership, reason: str) -> str:
    contract = _contract(notification)
    if not contract.on_probation:
        raise DomainError(_("This contract has no probation running."))
    until = _month_later(contract.probation_until)
    if contract.ends_on is not None:
        until = min(until, contract.ends_on)
    contract = services.extend_probation(contract, by=by, until=until)
    return bot_messages.probation_extended(contract.probation_until)


def _contract(notification) -> Contract:
    contract = Contract.objects.filter(
        pk=notification.target_id, company_id=notification.company_id
    ).first()
    if contract is None:
        raise DomainError(_("This contract no longer exists."))
    return contract


def _month_later(day: date) -> date:
    month = day.month % 12 + 1
    year = day.year + (day.month == 12)
    for last in (31, 30, 29, 28):
        try:
            return date(year, month, min(day.day, last))
        except ValueError:
            continue
    return day + timedelta(days=30)


# Briefings and the owner bot's /today ---------------------------------------------------------


def brief_section(company, day: date, now, branch_ids: list[int] | None) -> dict | None:
    """Today's birthdays and anniversaries, and what runs out soon, in the reader's words."""
    settings = conf.get_settings(company)
    lines = []
    if settings.celebrations_enabled:
        people = queries.people(company, branch_ids=branch_ids).select_related("user")
        for row in overview.celebrations_between(
            company, people, day, day, anniversaries=settings.celebrate_anniversaries
        ):
            if row["kind"] == Celebration.Kind.BIRTHDAY:
                lines.append(_("Birthday: %(name)s") % {"name": row["member"]})
            else:
                lines.append(
                    ngettext(
                        "Work anniversary: %(name)s, %(years)d year",
                        "Work anniversary: %(name)s, %(years)d years",
                        row["years"],
                    )
                    % {"name": row["member"], "years": row["years"]}
                )
    documents = queries.expiring_documents(
        company, branch_ids=branch_ids, day=day, within=settings.document_warn_days
    ).count()
    if documents:
        lines.append(_("Documents to renew: %(count)d") % {"count": documents})
    contracts = queries.ending_contracts(
        company, branch_ids=branch_ids, day=day, within=settings.contract_warn_days
    ).count()
    if contracts:
        lines.append(_("Contracts ending: %(count)d") % {"count": contracts})
    probations = queries.probation_endings(
        company, branch_ids=branch_ids, day=day, within=settings.probation_warn_days
    ).count()
    if probations:
        lines.append(_("Probations ending: %(count)d") % {"count": probations})
    if not lines:
        return None
    return {"title": _("HR"), "lines": lines}


BRIEF_GAPS = 3
# The documents a pharmacist renews (diplomas don't expire).
RENEWED_KINDS = (
    DocumentKind.PHARMACIST_CERTIFICATE,
    DocumentKind.QUALIFICATION_CATEGORY,
    DocumentKind.STATE_REGISTRATION,
)


def coverage_brief(company, day: date, now, branch_ids: list[int] | None) -> dict | None:
    """Pharmacist coverage for the morning brief and /today: a branch licensed for controlled
    substances without that licence in force on file, and (once the rule is set up) hours
    without a qualified pharmacist in the next 7 days of the roster, a pharmacy without one
    right now, tills opened by someone not qualified, and pharmacist certificates that end
    within 30 days."""
    lines = permit_lines(company, day, branch_ids)
    settings = conf.coverage_settings(company)
    if settings is None:
        return {"title": _("Pharmacist coverage"), "lines": lines} if lines else None
    names = {
        branch.pk: branch.name for branch in coverage.pharmacies(company, branch_ids=branch_ids)
    }
    live = [gap for gap in coverage.live(company, now) if gap.branch_id in names]
    for gap in live:
        lines.append(
            _("No qualified pharmacist now: %(branch)s, since %(time)s")
            % {"branch": names[gap.branch_id], "time": bot_messages.clock(gap.since)}
        )
    gaps = coverage.upcoming(company, now, 7, branch_ids=branch_ids)
    if gaps:
        lines.append(
            _("Roster gaps without a qualified pharmacist, next 7 days: %(count)d")
            % {"count": len(gaps)}
        )
        for gap in gaps[:BRIEF_GAPS]:
            when = bot_messages.planned_gap_when(gap.start, gap.end)
            lines.append(f"{names.get(gap.branch_id, '')}: {when}")
    for row in coverage.unqualified_sellers(company, day, branch_ids=branch_ids):
        lines.append(
            _("Till opened by someone not qualified: %(name)s (%(branch)s)")
            % {"name": row["cashier"], "branch": row["branch"]}
        )
    positions = conf.pharmacist_position_ids(settings)
    expiring = (
        queries.expiring_documents(company, branch_ids=branch_ids, day=day, within=30)
        .filter(kind__in=RENEWED_KINDS, membership__position_id__in=positions)
        .count()
    )
    if expiring:
        lines.append(
            _("Pharmacist certificates to renew within 30 days: %(count)d") % {"count": expiring}
        )
    if not lines:
        return None
    return {"title": _("Pharmacist coverage"), "lines": lines}


def permit_lines(company, day: date, branch_ids: list[int] | None) -> list[str]:
    lines = []
    for row in queries.permit_warnings(company, branch_ids=branch_ids, day=day):
        lines.append(permit_warning_text(row))
    return lines


def permit_warning_text(row: dict) -> str:
    if row["problem"] == queries.PERMIT_EXPIRED:
        # Translators: %(date)s is dd.mm.yyyy, %(branch)s a pharmacy's name.
        return _("Controlled substances licence ended on %(date)s: %(branch)s") % {
            "date": bot_messages.day(row["valid_until"]),
            "branch": row["branch"].name,
        }
    return _("Controlled substances licence not on file: %(branch)s") % {
        "branch": row["branch"].name
    }


def pharmacists_done(company) -> bool:
    """The setup step hr.pharmacists: the pharmacist positions are chosen and someone in them
    is qualified today (their diplomas and certificates are in). Nothing to do for a company
    with the rule off or without a pharmacy."""
    settings = conf.get_settings(company)
    if not settings.coverage_enabled or not coverage.pharmacies(company, branch_ids=None):
        return True
    positions = conf.pharmacist_position_ids(settings)
    if not positions:
        return False
    people = Membership.objects.filter(
        company=company, status=Membership.Status.APPROVED, position_id__in=positions
    ).values_list("pk", flat=True)
    return bool(queries.qualified(company, list(people), queries.today(company)))


# The company calendar -----------------------------------------------------------------------------


def calendar_celebrations(company, start: date, end: date, member: Membership) -> list:
    end = min(end, start + timedelta(days=CALENDAR_DAYS - 1))
    people = queries.people(company, branch_ids=scope.branch_ids(member)).select_related("user")
    items = []
    for row in overview.celebrations_between(company, people, start, end):
        if row["kind"] == Celebration.Kind.BIRTHDAY:
            title = _("Birthday: %(name)s") % {"name": row["member"]}
        else:
            title = ngettext(
                "Work anniversary: %(name)s, %(years)d year",
                "Work anniversary: %(name)s, %(years)d years",
                row["years"],
            ) % {"name": row["member"], "years": row["years"]}
        items.append(
            CalendarItem(
                id=f"hr.{row['kind']}:{row['member'].pk}:{row['date'].isoformat()}",
                kind=f"hr.{row['kind']}",
                title=title,
                start=row["date"],
                end=None,
                all_day=True,
                color="chart-5",
                url=f"/c/{company.pk}/hr/celebrations",
            )
        )
    return items


def calendar_contracts(company, start: date, end: date, member: Membership) -> list:
    rows = queries.contracts(company, branch_ids=scope.branch_ids(member)).filter(
        status=Contract.Status.ACTIVE
    )
    items = []
    for contract in rows.filter(ends_on__range=(start, end)).select_related("membership__user"):
        items.append(
            _contract_item(company, contract, "hr.contract_end", contract.ends_on, "warning")
        )
    probation = rows.filter(
        probation_until__range=(start, end), probation_passed_at__isnull=True
    ).select_related("membership__user")
    for contract in probation:
        items.append(
            _contract_item(company, contract, "hr.probation_end", contract.probation_until, "info")
        )
    return items


def _contract_item(company, contract: Contract, kind: str, day: date, color: str) -> CalendarItem:
    if kind == "hr.contract_end":
        title = _("Contract ends: %(name)s") % {"name": contract.membership}
    else:
        title = _("Probation ends: %(name)s") % {"name": contract.membership}
    return CalendarItem(
        id=f"{kind}:{contract.pk}",
        kind=kind,
        title=title,
        start=day,
        end=None,
        all_day=True,
        color=color,
        url=f"/c/{company.pk}/hr/contracts?contract={contract.pk}",
    )
