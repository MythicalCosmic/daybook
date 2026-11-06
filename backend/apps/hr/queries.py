"""Read functions of HR records, for other apps, the dashboard and the AI tools.

A function returning branch-bound data takes the required keyword
`branch_ids: list[int] | None` (callers pass `apps.members.scope.branch_ids(member)`).
People are bound to the branches they work in (`Membership.branches`).
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db.models import F, QuerySet
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.hr import conf
from apps.hr.models import (
    Contract,
    DocumentKind,
    EmployeeDocument,
    EmployeeProfile,
    RequiredDocument,
)
from apps.members.models import Membership

# Working here now (a suspended person keeps their file); and everyone who ever worked here.
CURRENT = (Membership.Status.APPROVED, Membership.Status.SUSPENDED)
GONE = (Membership.Status.LEFT, Membership.Status.BLOCKED)
EMPLOYED = (*CURRENT, *GONE)

# A document's state on a day.
VALID, EXPIRING, EXPIRED, NO_EXPIRY = "valid", "expiring", "expired", "no_expiry"
DOCUMENT_STATES = (VALID, EXPIRING, EXPIRED, NO_EXPIRY)
# A required document's state for a person (the compliance matrix).
OK, UNVERIFIED, MISSING = "ok", "unverified", "missing"
CHECK_STATES = (OK, UNVERIFIED, EXPIRING, EXPIRED, MISSING)
# Levels that rank above others of the same family: a higher diploma satisfies "college".
LEVEL_RANK = {"college": 1, "higher": 2, "second": 1, "first": 2, "highest": 3}
LEVEL_FAMILY = {"college": "diploma", "higher": "diploma"}


def today(company, now: datetime | None = None) -> date:
    return timezone.localtime(now or timezone.now(), ZoneInfo(company.timezone)).date()


# People ---------------------------------------------------------------------------------


def people(
    company, *, branch_ids: list[int] | None, statuses: Iterable[str] = CURRENT
) -> QuerySet[Membership]:
    """Members of `company` with one of `statuses` who work in one of `branch_ids` (everyone
    when None)."""
    rows = Membership.objects.for_company(company).filter(status__in=list(statuses))
    if branch_ids is not None:
        rows = Membership.objects.filter(pk__in=rows.filter(branches__in=branch_ids).values("pk"))
    return rows


def person(company, member_id, *, branch_ids: list[int] | None) -> Membership | None:
    """Someone who works or worked here, inside the branch scope; None otherwise (another
    company's id, a join request, outside the scope)."""
    try:
        member_id = int(member_id)
    except TypeError, ValueError:
        return None
    return (
        people(company, branch_ids=branch_ids, statuses=EMPLOYED)
        .filter(pk=member_id)
        .select_related("user", "company", "position", "home_branch", "department", "role")
        .first()
    )


def profile_of(membership: Membership) -> EmployeeProfile:
    """The person's profile, or an unsaved one with the defaults and their hire date as the
    membership tells it (someone whose profile was never made: it is made on the first edit)."""
    found = EmployeeProfile.objects.filter(membership=membership).first()
    if found is not None:
        return found
    start, _end = _membership_dates(membership.company, [membership]).get(
        membership.pk, (None, None)
    )
    return EmployeeProfile(company_id=membership.company_id, membership=membership, hire_date=start)


def passport_shared(profile: EmployeeProfile) -> bool:
    """Whether another person of the company has the same passport number on file."""
    if not profile.passport_digest:
        return False
    return (
        EmployeeProfile.objects.filter(
            company_id=profile.company_id, passport_digest=profile.passport_digest
        )
        .exclude(pk=profile.pk)
        .exists()
    )


# Documents ------------------------------------------------------------------------------


def documents(company, *, branch_ids: list[int] | None) -> QuerySet[EmployeeDocument]:
    """Documents of people who work or worked here, inside the branch scope."""
    rows = EmployeeDocument.objects.for_company(company).filter(membership__status__in=EMPLOYED)
    if branch_ids is not None:
        rows = rows.filter(
            membership_id__in=people(company, branch_ids=branch_ids, statuses=EMPLOYED).values("pk")
        )
    return rows


def state(document: EmployeeDocument, day: date, warn_days: int) -> str:
    """valid, expiring (within `warn_days`), expired or no_expiry on `day`."""
    if document.expires_on is None:
        return NO_EXPIRY
    if document.expires_on < day:
        return EXPIRED
    if document.expires_on <= day + timedelta(days=warn_days):
        return EXPIRING
    return VALID


def latest_documents(rows: QuerySet[EmployeeDocument]) -> QuerySet[EmployeeDocument]:
    """Each person's newest document of each kind in `rows`: the one that runs longest (no end
    counts as longest), then the latest issued. An older medical book replaced by a new one is
    left out, so it raises no warning."""
    newest = (
        rows.order_by(
            "membership_id",
            "kind",
            F("expires_on").desc(nulls_first=True),
            F("issued_on").desc(nulls_last=True),
            "-pk",
        )
        .distinct("membership_id", "kind")
        .values("pk")
    )
    return EmployeeDocument.objects.filter(pk__in=newest)


def expiring_documents(
    company, *, branch_ids: list[int] | None, day: date, within: int
) -> QuerySet[EmployeeDocument]:
    """Current people's newest documents that ended or end within `within` days of `day`,
    soonest first."""
    rows = documents(company, branch_ids=branch_ids).filter(membership__status__in=CURRENT)
    return (
        latest_documents(rows)
        .filter(expires_on__isnull=False, expires_on__lte=day + timedelta(days=within))
        .select_related("membership__user", "membership__position", "membership__home_branch")
        .order_by("expires_on", "pk")
    )


def expiring_count(member: Membership) -> int:
    """The `hr.expiring` badge: documents, contracts and probations that end within the
    company's warning days (or already ended), in the member's branch scope."""
    from apps.members import scope

    company = member.company
    settings = conf.get_settings(company)
    day = today(company)
    branch_ids = scope.branch_ids(member)
    return (
        expiring_documents(
            company, branch_ids=branch_ids, day=day, within=settings.document_warn_days
        ).count()
        + ending_contracts(
            company, branch_ids=branch_ids, day=day, within=settings.contract_warn_days
        ).count()
        + probation_endings(
            company, branch_ids=branch_ids, day=day, within=settings.probation_warn_days
        ).count()
    )


# Contracts -------------------------------------------------------------------------------


def contracts(company, *, branch_ids: list[int] | None) -> QuerySet[Contract]:
    """Contracts of people who work or worked here, inside the branch scope."""
    rows = Contract.objects.for_company(company)
    if branch_ids is not None:
        rows = rows.filter(
            membership_id__in=people(company, branch_ids=branch_ids, statuses=EMPLOYED).values("pk")
        )
    return rows


def ending_contracts(
    company, *, branch_ids: list[int] | None, day: date, within: int
) -> QuerySet[Contract]:
    """Contracts in force whose end date is within `within` days of `day` (or has passed
    while they are still in force), soonest first."""
    return (
        contracts(company, branch_ids=branch_ids)
        .filter(
            status=Contract.Status.ACTIVE,
            ends_on__isnull=False,
            ends_on__lte=day + timedelta(days=within),
        )
        .select_related("membership__user")
        .order_by("ends_on", "pk")
    )


def probation_endings(
    company, *, branch_ids: list[int] | None, day: date, within: int
) -> QuerySet[Contract]:
    """Contracts in force whose probation ends within `within` days of `day` (or ended
    without anyone confirming it), soonest first."""
    return (
        contracts(company, branch_ids=branch_ids)
        .filter(
            status=Contract.Status.ACTIVE,
            probation_until__isnull=False,
            probation_passed_at__isnull=True,
            probation_until__lte=day + timedelta(days=within),
        )
        .select_related("membership__user")
        .order_by("probation_until", "pk")
    )


def org(company) -> dict:
    """The company's structure (`hr.queries.org`, fixed for the lifecycle's org chart):
    departments with their head and headcount, and every current person with their department
    and manager (their nearest head)."""
    from apps.members import departments

    tree = departments.Org(company.pk)
    counts = departments.counts(company.pk)
    rows = []
    for pk in tree.order:
        department = tree.departments[pk]
        rows.append(
            {
                "id": pk,
                "name": department.name,
                "parent_id": department.parent_id,
                "depth": tree.depths[pk],
                "head_id": department.head_id,
                "headcount": counts.get(pk, 0),
            }
        )
    members = list(
        people(company, branch_ids=None).select_related("user", "position", "department")
    )
    staff = []
    for member in members:
        manager = departments.manager_of(member, tree)
        staff.append(
            {
                "id": member.pk,
                "name": str(member),
                "position": member.position.name if member.position_id else None,
                "department_id": member.department_id,
                "manager_id": manager.pk if manager else None,
            }
        )
    return {"departments": rows, "people": staff}


def required_for(company) -> dict[int | None, list[RequiredDocument]]:
    """{position id (None: everyone): its required documents}."""
    found: dict[int | None, list[RequiredDocument]] = defaultdict(list)
    for row in RequiredDocument.objects.for_company(company).order_by("kind", "pk"):
        found[row.position_id].append(row)
    return found


def satisfies(document: EmployeeDocument, required: RequiredDocument) -> bool:
    """Whether `document` is of the kind (or an alternative) and at the level asked."""
    if document.kind != required.kind and document.kind not in (required.alternatives or []):
        return False
    if not required.level:
        return True
    asked, have = required.level, document.level
    if not have or LEVEL_FAMILY.get(asked, "category") != LEVEL_FAMILY.get(have, "category"):
        return False
    return LEVEL_RANK.get(have, 0) >= LEVEL_RANK.get(asked, 0)


@dataclass(frozen=True)
class Check:
    """One required document for one person: its state and the document that decides it."""

    required: RequiredDocument
    status: str  # ok, unverified, expiring, expired, missing
    document: EmployeeDocument | None


def check(
    required: RequiredDocument, held: list[EmployeeDocument], day: date, warn_days: int
) -> Check:
    """The best of `held` (one person's documents) for `required` on `day`: a document that
    hasn't expired, the one running longest; else the expired one that ended last."""
    matching = [document for document in held if satisfies(document, required)]
    if not matching:
        return Check(required, MISSING, None)
    alive = [d for d in matching if d.expires_on is None or d.expires_on >= day]
    if not alive:
        last = max(matching, key=lambda d: (d.expires_on, d.pk))
        return Check(required, EXPIRED, last)
    best = max(alive, key=lambda d: (d.expires_on is None, d.expires_on or day, d.pk))
    if state(best, day, warn_days) == EXPIRING:
        return Check(required, EXPIRING, best)
    return Check(required, OK if best.verified_at else UNVERIFIED, best)


def compliance(
    company,
    *,
    branch_ids: list[int] | None,
    day: date,
    position_ids: list[int] | None = None,
    branch: list[int] | None = None,
) -> dict:
    """Who lacks what: for every current person in scope, each document their position (or
    everyone) must have, with its state. `kinds` are the matrix's columns."""
    settings = conf.get_settings(company)
    required = required_for(company)
    members = people(company, branch_ids=branch_ids)
    if position_ids:
        members = members.filter(position_id__in=position_ids)
    if branch:
        members = Membership.objects.filter(pk__in=members.filter(branches__in=branch).values("pk"))
    members = list(
        members.select_related("user", "position", "home_branch").order_by(
            "first_name", "last_name", "pk"
        )
    )
    held: dict[int, list[EmployeeDocument]] = defaultdict(list)
    for document in EmployeeDocument.objects.filter(membership__in=members):
        held[document.membership_id].append(document)
    rows = []
    kinds: list[str] = []
    totals = {"people": 0, "complete": 0, MISSING: 0, EXPIRED: 0, EXPIRING: 0, UNVERIFIED: 0}
    for member in members:
        needed = [*required.get(None, []), *required.get(member.position_id, [])]
        checks = [check(row, held[member.pk], day, settings.document_warn_days) for row in needed]
        for each in checks:
            if each.required.kind not in kinds:
                kinds.append(each.required.kind)
            if each.status in totals:
                totals[each.status] += 1
        totals["people"] += 1
        if not any(each.status in (MISSING, EXPIRED) for each in checks):
            totals["complete"] += 1
        rows.append((member, checks))
    order = list(DocumentKind.values)
    kinds.sort(key=order.index)
    return {"kinds": kinds, "rows": rows, "totals": totals}


# Qualified pharmacists (the coverage rule, docs/PLAN-OWNER.md §14.9) ---------------------

# Why someone doesn't count as a qualified pharmacist on a day (the worst reason first).
NOT_APPROVED, NOT_PHARMACIST = "not_approved", "not_pharmacist"
DOCUMENT_REASONS = (MISSING, EXPIRED, UNVERIFIED)
REASONS = (NOT_APPROVED, NOT_PHARMACIST, *DOCUMENT_REASONS)


@dataclass(frozen=True)
class Verdict:
    """Whether one person counts as a qualified pharmacist on one day, and if not, why:
    `reason` is one of REASONS and `kinds` the required documents that fail it."""

    member_id: int
    counts: bool
    reason: str | None = None
    kinds: tuple[str, ...] = ()


def standing(required: RequiredDocument, held: list[EmployeeDocument], day: date) -> str:
    """ok, unverified, expired or missing: the best of `held` (one person's documents) for
    `required` on `day`. A document issued after `day` doesn't count yet."""
    matching = [
        document
        for document in held
        if satisfies(document, required)
        and (document.issued_on is None or document.issued_on <= day)
    ]
    if not matching:
        return MISSING
    alive = [d for d in matching if d.expires_on is None or d.expires_on >= day]
    if not alive:
        return EXPIRED
    return OK if any(d.verified_at for d in alive) else UNVERIFIED


class Qualifier:
    """Answers "does this person count as a qualified pharmacist on this day?" for many people
    and days with one read of the settings, the required documents and the documents.

    Someone counts when they are approved (a suspended person never counts), their position is
    one of `pharmacist_positions`, and, with `coverage_needs_documents`, they meet every
    document their position requires on that day: one of the kind or an alternative, at the
    level asked, verified, issued and not expired."""

    def __init__(self, company, member_ids: Iterable[int], *, settings=None):
        self.settings = settings or conf.get_settings(company)
        self.positions = conf.pharmacist_position_ids(self.settings)
        self.members = {
            member.pk: member
            for member in Membership.objects.for_company(company).filter(pk__in=list(member_ids))
        }
        self.required: dict[int | None, list[RequiredDocument]] = (
            required_for(company) if self.settings.coverage_needs_documents else {}
        )
        self.held: dict[int, list[EmployeeDocument]] = defaultdict(list)
        if self.settings.coverage_needs_documents:
            pharmacists = [m.pk for m in self.members.values() if m.position_id in self.positions]
            for document in EmployeeDocument.objects.filter(membership_id__in=pharmacists):
                self.held[document.membership_id].append(document)
        self._memo: dict[tuple[int, date], Verdict] = {}

    def verdict(self, member_id: int, day: date) -> Verdict:
        key = (member_id, day)
        if key not in self._memo:
            self._memo[key] = self._judge(member_id, day)
        return self._memo[key]

    def counts(self, member_id: int | None, day: date) -> bool:
        return member_id is not None and self.verdict(member_id, day).counts

    def is_pharmacist(self, member_id: int | None) -> bool:
        member = self.members.get(member_id)
        return member is not None and member.position_id in self.positions

    def _judge(self, member_id: int, day: date) -> Verdict:
        member = self.members.get(member_id)
        if member is None or member.status != Membership.Status.APPROVED:
            return Verdict(member_id, False, NOT_APPROVED)
        if member.position_id not in self.positions:
            return Verdict(member_id, False, NOT_PHARMACIST)
        if not self.settings.coverage_needs_documents:
            return Verdict(member_id, True)
        failing: dict[str, list[str]] = defaultdict(list)
        for required in self.required.get(member.position_id, []):
            status = standing(required, self.held[member_id], day)
            if status != OK:
                failing[status].append(required.kind)
        for reason in DOCUMENT_REASONS:
            if failing[reason]:
                kinds = tuple(dict.fromkeys(kind for each in failing.values() for kind in each))
                return Verdict(member_id, False, reason, kinds)
        return Verdict(member_id, True)


def qualified(company, member_ids: Iterable[int], day: date) -> set[int]:
    """The members of `member_ids` who count as a qualified pharmacist on `day`."""
    ids = list(member_ids)
    qualifier = Qualifier(company, ids)
    return {member_id for member_id in ids if qualifier.counts(member_id, day)}


def qualified_staff(company, *, branch_ids: list[int] | None, day: date) -> list[dict]:
    """The people in pharmacist positions in scope with what qualifies them on `day` (the
    inspection pack's staff list, docs/PLAN-OWNER.md §14.16): name, position, whether they
    count and why not, and for each document their position requires the one on file with its
    dates. Identity documents are never part of it."""
    settings = conf.get_settings(company)
    positions = conf.pharmacist_position_ids(settings)
    members = list(
        people(company, branch_ids=branch_ids, statuses=(Membership.Status.APPROVED,))
        .filter(position_id__in=positions)
        .select_related("user", "position", "home_branch")
        .order_by("position__order", "first_name", "last_name", "pk")
    )
    qualifier = Qualifier(company, [member.pk for member in members], settings=settings)
    required = required_for(company)
    held: dict[int, list[EmployeeDocument]] = defaultdict(list)
    for document in EmployeeDocument.objects.filter(membership__in=members):
        held[document.membership_id].append(document)
    rows = []
    for member in members:
        verdict = qualifier.verdict(member.pk, day)
        documents = []
        for row in required.get(member.position_id, []):
            best = _best(row, held[member.pk], day)
            documents.append(
                {
                    "kind": row.kind,
                    "level_asked": row.level,
                    "status": standing(row, held[member.pk], day),
                    "document_id": best.pk if best else None,
                    "title": best.title if best else "",
                    "number": best.number if best else "",
                    "level": best.level if best else "",
                    "specialty": best.specialty if best else "",
                    "issuer": best.issuer if best else "",
                    "issued_on": best.issued_on if best else None,
                    "expires_on": best.expires_on if best else None,
                    "verified": bool(best and best.verified_at),
                }
            )
        rows.append(
            {
                "member": member,
                "position": member.position.name if member.position_id else None,
                "home_branch": member.home_branch,
                "qualified": verdict.counts,
                "reason": verdict.reason,
                "documents": documents,
            }
        )
    return rows


def _best(required: RequiredDocument, held: list[EmployeeDocument], day: date):
    """The document that decides `required` on `day`: verified and in force first, then in force,
    then the one that ended last."""
    matching = [d for d in held if satisfies(d, required)]
    if not matching:
        return None
    return max(
        matching,
        key=lambda d: (
            d.expires_on is None or d.expires_on >= day,
            d.verified_at is not None,
            d.expires_on or date.max,
            d.pk,
        ),
    )


# Employment dates (the contract payroll and the people pages read) ----------------------


def employment_dates(company, member_ids: Iterable[int]) -> dict[int, tuple[date, date | None]]:
    """membership id -> (first day, last day or None while employed), in company-local dates.
    Payroll prorates pay with it. People who never joined (pending, rejected) are left out.

    The first day is the profile's `hire_date` (the day they were approved, unless HR wrote
    another), the last day its `terminated_on` (the last day given when they left). Someone
    without those on file falls back on the membership itself: their latest approval (from the
    audit log, else the approval on the record) and the last day recorded when they were last
    offboarded or blocked (else the day that happened).
    """
    members = list(
        Membership.objects.for_company(company)
        .filter(pk__in=list(member_ids))
        .exclude(status__in=(Membership.Status.PENDING, Membership.Status.REJECTED))
    )
    profiles = {
        row["membership_id"]: (row["hire_date"], row["terminated_on"])
        for row in EmployeeProfile.objects.filter(membership__in=members).values(
            "membership_id", "hire_date", "terminated_on"
        )
    }
    fallback = _membership_dates(
        company,
        [
            member
            for member in members
            if profiles.get(member.pk, (None, None))[0] is None
            or (member.status in GONE and profiles.get(member.pk, (None, None))[1] is None)
        ],
    )
    dates = {}
    for member in members:
        hired, terminated = profiles.get(member.pk, (None, None))
        start = hired or fallback[member.pk][0]
        end = None
        if member.status in GONE:
            end = terminated or fallback[member.pk][1]
        dates[member.pk] = (start, end)
    return dates


def _membership_dates(company, members: list[Membership]) -> dict[int, tuple[date, date | None]]:
    """(first day, last day) from the membership and the audit log alone."""
    if not members:
        return {}
    tz = ZoneInfo(company.timezone)
    ids = [member.pk for member in members]
    approved_at = _latest(company, ids, (AuditLog.Action.MEMBER_APPROVED,))
    # The latest departure only: someone who left, came back and was blocked ended on the block.
    departures = _latest_rows(
        company, ids, (AuditLog.Action.MEMBER_LEFT, AuditLog.Action.MEMBER_BLOCKED)
    )
    dates = {}
    for member in members:
        started = approved_at.get(member.pk)
        if started is None and member.status not in GONE:
            started = member.decided_at
        started = started or member.onboarded_at or member.created_at
        end = None
        if member.status in GONE:
            departure = departures.get(member.pk)
            end = _terminated_on(departure) or _local(
                departure.created_at if departure else member.decided_at or member.updated_at, tz
            )
        dates[member.pk] = (_local(started, tz), end)
    return dates


def _latest(company, ids: list[int], actions: tuple[str, ...]) -> dict[int, datetime]:
    return {pk: row.created_at for pk, row in _latest_rows(company, ids, actions).items()}


def _latest_rows(company, ids: list[int], actions: tuple[str, ...]) -> dict[int, AuditLog]:
    rows = AuditLog.objects.filter(
        company=company, action__in=actions, target_type="membership", target_id__in=ids
    ).order_by("target_id", "-created_at", "-pk")
    latest: dict[int, AuditLog] = {}
    for row in rows:
        latest.setdefault(row.target_id, row)
    return latest


def _terminated_on(row: AuditLog | None) -> date | None:
    value = row.details.get("terminated_on") if row is not None else None
    try:
        return date.fromisoformat(value) if value else None
    except TypeError, ValueError:
        return None


def _local(moment: datetime, tz: ZoneInfo) -> date:
    return timezone.localtime(moment, tz).date()
