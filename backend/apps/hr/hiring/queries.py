"""What members see of hiring: vacancies and applicants inside their branches (a vacancy with no
branch is the company's, seen only with every branch, docs/PLAN-OWNER.md §2.6), how many are at
each stage, the sidebar's count of new applicants, and the command palette's search."""

import re

from django.db.models import Case, Count, IntegerField, Q, QuerySet, Value, When
from django.utils.translation import gettext as _

from apps.console.registry import SearchHit
from apps.hr.models import Applicant, Vacancy
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm

STAGES = tuple(Applicant.Stage.values)
OPEN_STAGES = (
    Applicant.Stage.NEW,
    Applicant.Stage.SCREENING,
    Applicant.Stage.INTERVIEW,
    Applicant.Stage.OFFER,
)
# The list shows working vacancies first: open, paused, drafts, then closed ones.
STATUS_ORDER = {
    Vacancy.Status.OPEN: 0,
    Vacancy.Status.PAUSED: 1,
    Vacancy.Status.DRAFT: 2,
    Vacancy.Status.CLOSED: 3,
}


def vacancies(company, *, branch_ids: list[int] | None) -> QuerySet[Vacancy]:
    rows = Vacancy.objects.for_company(company).select_related(
        "company", "position__role", "branch", "created_by__user"
    )
    return scope.restrict(rows, branch_ids)


def with_counts(rows: QuerySet[Vacancy]) -> QuerySet[Vacancy]:
    """Each vacancy with `count_<stage>` for every stage and `count_total`."""
    counts = {
        f"count_{stage}": Count("applicants", filter=Q(applicants__stage=stage)) for stage in STAGES
    }
    return rows.annotate(count_total=Count("applicants"), **counts)


def ordered(rows: QuerySet[Vacancy]) -> QuerySet[Vacancy]:
    order = Case(
        *(When(status=status, then=Value(rank)) for status, rank in STATUS_ORDER.items()),
        output_field=IntegerField(),
    )
    return rows.annotate(status_rank=order).order_by("status_rank", "-created_at", "-pk")


def vacancy(company, vacancy_id, *, branch_ids: list[int] | None) -> Vacancy | None:
    try:
        vacancy_id = int(vacancy_id)
    except TypeError, ValueError:
        return None
    return vacancies(company, branch_ids=branch_ids).filter(pk=vacancy_id).first()


def find_by_code(code: str) -> Vacancy | None:
    """The vacancy a bot link names, of an active company."""
    if not code:
        return None
    return (
        Vacancy.objects.select_related("company", "branch", "position")
        .filter(code=code, company__is_active=True)
        .first()
    )


def applicants(
    company,
    *,
    branch_ids: list[int] | None,
    vacancy_id: int | None = None,
    stages: list[str] | None = None,
    q: str | None = None,
    source: str | None = None,
) -> QuerySet[Applicant]:
    rows = Applicant.objects.for_company(company).select_related(
        "vacancy__branch", "vacancy__position", "membership__user", "user"
    )
    rows = scope.restrict(rows, branch_ids, field="vacancy__branch")
    if vacancy_id is not None:
        rows = rows.filter(vacancy_id=vacancy_id)
    if stages:
        rows = rows.filter(stage__in=stages)
    if source:
        rows = rows.filter(source=source)
    if q and (text := q.strip()):
        match = Q(name__icontains=text) | Q(telegram_username__icontains=text.lstrip("@"))
        digits = re.sub(r"\D", "", text)
        if len(digits) >= 3:
            match |= Q(phone__contains=digits)
        rows = rows.filter(match)
    return rows


def applicant(company, applicant_id, *, branch_ids: list[int] | None) -> Applicant | None:
    try:
        applicant_id = int(applicant_id)
    except TypeError, ValueError:
        return None
    return applicants(company, branch_ids=branch_ids).filter(pk=applicant_id).first()


def application_of(vacancy: Vacancy, user) -> Applicant | None:
    return Applicant.objects.filter(vacancy=vacancy, user=user).first()


# The sidebar and the command palette ---------------------------------------------------------


def new_count(member: Membership) -> int:
    """Applicants nobody has looked at yet (the Hiring item's badge)."""
    if not member.has_perm(Perm.HR_HIRING):
        return 0
    return (
        applicants(member.company, branch_ids=scope.branch_ids(member))
        .filter(stage=Applicant.Stage.NEW)
        .count()
    )


def url(applicant: Applicant) -> str:
    return f"/c/{applicant.company_id}/hr/hiring/{applicant.vacancy_id}?applicant={applicant.pk}"


def search(member: Membership, q: str, limit: int) -> list[SearchHit]:
    rows = applicants(member.company, branch_ids=scope.branch_ids(member), q=q).order_by(
        "-created_at", "-pk"
    )[:limit]
    return [
        SearchHit(
            type="hr.applicant",
            id=row.pk,
            title=row.name,
            subtitle=" · ".join(
                part
                for part in (
                    row.vacancy.title,
                    str(Applicant.Stage(row.stage).label),
                    row.vacancy.branch.name if row.vacancy.branch else "",
                )
                if part
            ),
            url=url(row),
        )
        for row in rows
    ]


def stage_counts(rows: QuerySet[Applicant]) -> dict[str, int]:
    found = dict(rows.order_by().values_list("stage").annotate(n=Count("pk")))
    return {stage: found.get(stage, 0) for stage in STAGES}


def summary_line(vacancy: Vacancy) -> str:
    """ "Farmatsevt · Chilonzor" """
    return " · ".join(part for part in (vacancy.title, _branch(vacancy)) if part)


def _branch(vacancy: Vacancy) -> str:
    return vacancy.branch.name if vacancy.branch_id else _("Any branch")
