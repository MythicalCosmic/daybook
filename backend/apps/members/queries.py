from django.db.models import Q, QuerySet

from apps.companies.models import Company
from apps.members.models import Membership
from apps.members.permissions import Perm


def members_with_perm(company: Company, perm: Perm) -> QuerySet[Membership]:
    """Approved members whose role grants `perm`."""
    return (
        Membership.objects.for_company(company)
        .filter(status=Membership.Status.APPROVED)
        .filter(Q(role__is_owner=True) | Q(role__permissions__contains=[str(perm)]))
    )
