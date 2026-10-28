"""The job titles a new company starts with, in its own language, and for older companies that
have none."""

import importlib

import pytest
from django.apps import apps

from apps.accounts.tests.factories import UserFactory
from apps.companies.services import create_company_for
from apps.members.models import Position
from apps.members.positions import DEFAULT_POSITIONS

pytestmark = pytest.mark.django_db


def names(company) -> list[str]:
    return list(
        Position.objects.filter(company=company).order_by("order").values_list("name", flat=True)
    )


def test_a_new_company_starts_with_the_usual_job_titles_in_uzbek(settings):
    settings.COMPANY_SIGNUP = "open"

    company, _ = create_company_for(UserFactory(), name="Shifo Dorixona", language="uz")

    assert names(company)[:3] == ["Bosh menejer", "Menejer", "Bo‘lim boshlig‘i"]
    assert {"Kassir", "Ombor xodimi", "Ombor mudiri", "Farmatsevt"} <= set(names(company))
    assert len(names(company)) == len(DEFAULT_POSITIONS)


def test_a_russian_company_gets_them_in_russian(settings):
    settings.COMPANY_SIGNUP = "open"

    company, _ = create_company_for(UserFactory(), name="Аптека", language="ru")

    assert {"Кассир", "Топ-менеджер", "Работник склада"} <= set(names(company))


def test_positions_copied_from_another_company_are_kept_alone(settings, company, member):
    settings.COMPANY_SIGNUP = "open"
    owner = member.registered(company, "Owner")
    Position.objects.create(company=company, name="Smena boshlig‘i")

    copy, _ = create_company_for(
        owner.user, name="Ikkinchi", copy_from=company, parts=["members.positions"]
    )

    assert names(copy) == ["Smena boshlig‘i"]


def test_older_companies_without_positions_get_them_and_others_keep_theirs(company, other_company):
    Position.objects.create(company=other_company, name="Ofis")
    migration = importlib.import_module("apps.members.migrations.0012_default_positions")

    migration.add_positions(apps, None)

    assert "Cashier" in names(company)  # test companies speak English
    assert names(other_company) == ["Ofis"]
