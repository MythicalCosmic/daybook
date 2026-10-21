"""Read functions of company setup, for the owner API, the bots and other apps.

A function returning branch-bound data takes the required keyword
`branch_ids: list[int] | None` (callers pass `apps.members.scope.branch_ids(member)`).
"""

from django.conf import settings
from django.db.models import Count, Q, QuerySet

from apps.companies.models import Branch, Company
from apps.members import scope
from apps.members.models import Membership


def branches(company: Company, *, branch_ids: list[int] | None) -> QuerySet[Branch]:
    """The company's branches inside the scope, open and closed, in display order, with
    `people` (approved members working there) and `manager` loaded."""
    rows = (
        Branch.objects.for_company(company)
        .select_related("manager", "manager__user")
        .annotate(
            people=Count(
                "members",
                filter=Q(members__status=Membership.Status.APPROVED),
                distinct=True,
            )
        )
        .order_by("-is_active", "order", "name")
    )
    return scope.restrict(rows, branch_ids, field="id")


def branch_done(company: Company) -> bool:
    """The "Branches" step of Get started: an open branch has an address or a map point."""
    return (
        Branch.objects.for_company(company)
        .filter(is_active=True)
        .filter(~Q(address="") | Q(latitude__isnull=False))
        .exists()
    )


def staff_invited(company: Company) -> bool:
    """The "Invite staff" step of Get started: someone besides the owners joined or asked to."""
    return (
        Membership.objects.for_company(company)
        .exclude(role__is_owner=True)
        .filter(status__in=(Membership.Status.APPROVED, Membership.Status.PENDING))
        .exists()
    )


def modules_chosen(company: Company) -> bool:
    return bool(company.features)


def invite(company: Company) -> dict:
    """What the invite page and the poster show."""
    counts = Membership.objects.for_company(company).aggregate(
        approved=Count("pk", filter=Q(status=Membership.Status.APPROVED)),
        pending=Count("pk", filter=Q(status=Membership.Status.PENDING)),
    )
    return {
        "link": company.invite_link,
        "start_param": company.invite_start_param,
        "bot_username": settings.EMPLOYEE_BOT_USERNAME,
        "company": {
            "name": company.name,
            "logo": company.logo.url if company.logo else None,
        },
        "branches": list(
            Branch.objects.for_company(company)
            .filter(is_active=True)
            .order_by("order", "name")
            .values_list("name", flat=True)
        ),
        "members": counts,
    }


def owned_count(user) -> int:
    """How many companies count against `MAX_COMPANIES_PER_USER` for `user`: every approved
    owner membership, switched-off companies included (the same count `create_company` uses)."""
    return Membership.objects.filter(
        user=user, status=Membership.Status.APPROVED, role__is_owner=True
    ).count()


def owned_companies(user) -> list[Company]:
    """Active companies where `user` is an approved owner, by name."""
    return list(
        Company.objects.filter(
            is_active=True,
            memberships__user=user,
            memberships__status=Membership.Status.APPROVED,
            memberships__role__is_owner=True,
        ).order_by("name")
    )
