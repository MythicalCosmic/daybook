from django.db import transaction

from apps.companies.models import Company
from apps.members.services import create_default_roles


@transaction.atomic
def create_company(*, name: str, slug: str, **fields) -> Company:
    company = Company.objects.create(name=name, slug=slug, **fields)
    create_default_roles(company)
    return company
