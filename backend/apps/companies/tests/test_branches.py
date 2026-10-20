import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.companies.models import Branch, Feature
from apps.companies.tests.factories import BranchFactory

pytestmark = pytest.mark.django_db


def test_new_companies_start_with_no_modules_and_sensible_defaults(company):
    assert company.features == []
    assert company.workdays == [0, 1, 2, 3, 4, 5]  # Monday to Saturday
    assert company.base_currency == "UZS"
    assert company.owner_sees_personal_tasks is True
    assert company.team_directory_phones is True
    assert company.setup_completed_at is None
    assert not company.has_feature(Feature.SALES)


def test_features_are_the_known_modules(company):
    company.features = [Feature.SALES, Feature.FINANCE]
    company.full_clean()
    assert company.has_feature("sales")

    company.features = ["casino"]
    with pytest.raises(ValidationError):
        company.full_clean()


def test_workdays_are_weekdays(company):
    company.workdays = [0, 6]
    company.full_clean()

    company.workdays = [7]
    with pytest.raises(ValidationError):
        company.full_clean()


def test_a_branch_is_open_every_day_until_told_otherwise(company):
    branch = Branch.objects.create(company=company, name="Chilonzor")

    assert branch.open_weekdays == [0, 1, 2, 3, 4, 5, 6]
    assert branch.geofence_m == 150
    assert branch.is_active
    assert set(company.branches.all()) == {company.branches.get(name=company.name), branch}
    assert str(branch) == "Chilonzor"


def test_branch_names_are_unique_per_company(company, other_company):
    BranchFactory(company=company, name="Center")
    BranchFactory(company=other_company, name="Center")

    with pytest.raises(IntegrityError), transaction.atomic():
        BranchFactory(company=company, name="Center")


def test_the_branch_manager_works_for_the_same_company(company, other_company, member):
    branch = BranchFactory(company=company)
    branch.manager = member(other_company)

    with pytest.raises(ValidationError) as error:
        branch.full_clean()
    assert "manager" in error.value.message_dict

    branch.manager = member(company)
    branch.full_clean()
