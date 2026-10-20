from django.db import transaction
from django.utils.translation import gettext as _

from apps.companies.models import Company
from apps.core.exceptions import DomainError
from apps.members.services import create_default_roles
from apps.reminders.policies import default_policy


@transaction.atomic
def create_company(*, name: str, slug: str, **fields) -> Company:
    company = Company.objects.create(name=name, slug=slug, **fields)
    create_default_roles(company)
    default_policy(company.pk)
    return company


def find_by_invite(start_param: str) -> Company:
    """Resolve a /start deep-link parameter to an active company."""
    code = start_param.removeprefix(Company.INVITE_PREFIX)
    company = None
    if code != start_param:
        company = Company.objects.filter(invite_code=code, is_active=True).first()
    if company is None:
        raise DomainError(
            _("This invite link is invalid or has expired. Ask your manager for a new one.")
        )
    return company
