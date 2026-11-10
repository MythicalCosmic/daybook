"""Registrations of hiring, imported by `apps/hr/hooks.py` (so by `AppConfig.ready()`)."""

from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.console import registry
from apps.core.files import register_file_check
from apps.hr.hiring import queries, services
from apps.hr.hiring.actions import HiringAction
from apps.hr.models import Applicant, Vacancy
from apps.inbox.registry import register_kind
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm

FEATURE = "hr"
HIRING = Perm.HR_HIRING

audit_registry.register(HiringAction)


def _sees_vacancy(member: Membership, vacancy_id: int) -> bool:
    found = Vacancy.objects.filter(company_id=member.company_id, pk=vacancy_id).first()
    return found is not None and scope.allows(scope.branch_ids(member), found.branch_id)


def _sees_applicant(member: Membership, applicant_id: int) -> bool:
    found = (
        Applicant.objects.filter(company_id=member.company_id, pk=applicant_id)
        .select_related("vacancy")
        .first()
    )
    return found is not None and scope.allows(scope.branch_ids(member), found.vacancy.branch_id)


def may_open_document(user, company_id: int, applicant_id: int) -> bool:
    """`hr.applicant` files (an applicant's diploma photo): `hr.hiring` in the vacancy's branch."""
    viewer = (
        Membership.objects.filter(company_id=company_id, user=user)
        .select_related("company", "role")
        .first()
    )
    if viewer is None or not viewer.has_perm(HIRING):
        return False
    return _sees_applicant(viewer, applicant_id)


audit_registry.register_target("vacancy", HIRING, check=_sees_vacancy)
audit_registry.register_target("applicant", HIRING, check=_sees_applicant)
register_file_check("hr.applicant", may_open_document)

# The Hiring item's badge (applicants nobody has looked at yet) and the page's version key.
registry.register_pulse(
    services.PULSE_APPLICANTS, perm=HIRING, count=queries.new_count, feature=FEATURE
)
registry.register_pulse(services.PULSE_VACANCIES, perm=HIRING, count=None, feature=FEATURE)
registry.register_search("hr.applicant", perm=HIRING, search=queries.search, feature=FEATURE)

# To the hiring team: someone applied (the owner bot for owners and top managers).
register_kind(
    services.NEW_APPLICANT,
    label=_("New applicants for vacancies"),
    audience="owner",
    default_telegram=True,
)
