import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.companies.services import create_company
from apps.members.models import AccessRole

pytestmark = pytest.mark.django_db


def test_create_company_adds_default_roles():
    company = create_company(name="Acme", slug="acme")

    roles = {role.name: role for role in company.accessroles.all()}
    assert set(roles) == {"Owner", "Manager", "Employee"}
    assert roles["Owner"].is_owner
    assert roles["Employee"].is_default
    assert roles["Employee"].permissions == []


def test_invite_link_uses_bot_username(settings, company):
    settings.EMPLOYEE_BOT_USERNAME = "trello911_bot"

    assert company.invite_link == f"https://t.me/trello911_bot?start=c_{company.invite_code}"


def test_invite_link_is_empty_without_bot_username(settings, company):
    settings.EMPLOYEE_BOT_USERNAME = ""

    assert company.invite_link == ""


def test_regenerating_invite_code_invalidates_the_old_one(company):
    old_code = company.invite_code

    company.regenerate_invite_code()

    company.refresh_from_db()
    assert company.invite_code != old_code


def test_unknown_timezone_is_rejected(company):
    company.timezone = "Mars/Olympus"

    with pytest.raises(ValidationError):
        company.full_clean()


def test_company_has_only_one_default_role(company):
    with pytest.raises(IntegrityError), transaction.atomic():
        AccessRole.objects.create(company=company, name="Second default", is_default=True)
