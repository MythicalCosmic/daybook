"""Creating and setting up companies: create_company, setup_company, company_created."""

import pytest

from apps.accounts.tests.factories import UserFactory
from apps.companies.models import Company
from apps.companies.services import create_company, setup_company, slug_for
from apps.companies.signals import company_created
from apps.core.exceptions import DomainError
from apps.members.models import AccessRole, Membership
from apps.members.scope import branch_ids
from apps.reminders.models import ReminderPolicy

pytestmark = pytest.mark.django_db


@pytest.fixture
def announced():
    """Every company_created the test sends, as (company, by)."""
    calls = []

    def receiver(sender, company, by, **kwargs):
        calls.append((company, by))

    company_created.connect(receiver, dispatch_uid="test_setup")
    yield calls
    company_created.disconnect(dispatch_uid="test_setup")


def test_a_new_company_starts_with_roles_policy_and_a_branch(
    announced, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        company = create_company(name="Oqqayin Dorixona", timezone="Asia/Samarkand", language="ru")

    assert company.slug == "oqqayin-dorixona"
    assert (company.timezone, company.default_language, company.base_currency) == (
        "Asia/Samarkand",
        "ru",
        "UZS",
    )
    assert company.features == []
    assert set(company.accessroles.values_list("name", flat=True)) == {
        "Owner",
        "Manager",
        "Accountant",
        "Pharmacist",
        "Cashier",
        "Employee",
    }
    assert ReminderPolicy.objects.filter(company=company, is_default=True).count() == 1
    assert [branch.name for branch in company.branches.all()] == ["Oqqayin Dorixona"]
    assert announced == [(company, None)]


def test_company_created_waits_for_the_commit(announced, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks() as callbacks:
        create_company(name="Shop")

    assert announced == []
    assert len(callbacks) == 1


def test_the_owner_gets_an_approved_onboarded_owner_membership(
    announced, django_capture_on_commit_callbacks
):
    owner = UserFactory(first_name="Olim", last_name="Karimov")
    acting = None

    with django_capture_on_commit_callbacks(execute=True):
        company = create_company(name="Shop", owner=owner, by=acting)

    membership = Membership.objects.get(company=company, user=owner)
    assert membership.status == Membership.Status.APPROVED
    assert membership.role.is_owner
    assert membership.is_onboarded
    assert (membership.first_name, membership.last_name) == ("Olim", "Karimov")
    branch = company.branches.get()
    assert membership.home_branch == branch
    assert list(membership.branches.all()) == [branch]
    assert branch_ids(membership) is None  # owners see every branch
    assert announced == [(company, None)]


def test_by_is_passed_on(announced, company, member, django_capture_on_commit_callbacks):
    owner = member.registered(company, "Owner")

    with django_capture_on_commit_callbacks(execute=True):
        second = create_company(name="Second shop", owner=owner.user, by=owner)

    assert announced == [(second, owner)]


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Acme", "acme"),
        ("Ромашка", "romashka"),
        ("Oʻzbekiston Gʻalla", "ozbekiston-galla"),
        ("Дорихона «Ўрта»", "dorixona-orta"),
        ("!!!", "company"),
    ],
)
def test_slugs_come_from_the_name(name, slug):
    assert slug_for(name) == slug


def test_slugs_stay_unique():
    first = create_company(name="Acme")
    second = create_company(name="Acme")
    third = create_company(name="ACME!")

    assert [first.slug, second.slug, third.slug] == ["acme", "acme-2", "acme-3"]


def test_a_given_slug_is_used():
    assert create_company(name="Acme", slug="the-acme").slug == "the-acme"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "  "},
        {"name": "Acme", "timezone": "Mars/Olympus"},
        {"name": "Acme", "language": "de"},
        {"name": "Acme", "base_currency": "EUR"},
    ],
)
def test_bad_input_is_refused(kwargs):
    with pytest.raises(DomainError):
        create_company(**kwargs)
    assert not Company.objects.exists()


def test_one_person_owns_at_most_the_limit(settings):
    settings.MAX_COMPANIES_PER_USER = 2
    owner = UserFactory()
    create_company(name="One", owner=owner)
    create_company(name="Two", owner=owner)

    with pytest.raises(DomainError, match="2 companies"):
        create_company(name="Three", owner=owner)
    assert Company.objects.count() == 2


def test_platform_admins_have_no_limit(settings):
    settings.MAX_COMPANIES_PER_USER = 1
    admin = UserFactory(is_superuser=True)
    create_company(name="One", owner=admin)

    assert create_company(name="Two", owner=admin).pk


def test_setup_can_run_again_without_making_anything_twice(
    announced, django_capture_on_commit_callbacks
):
    company = create_company(name="Shop")
    roles = set(AccessRole.objects.filter(company=company).values_list("pk", flat=True))

    with django_capture_on_commit_callbacks(execute=True):
        setup_company(company, None)

    assert set(AccessRole.objects.filter(company=company).values_list("pk", flat=True)) == roles
    assert company.branches.count() == 1
    assert ReminderPolicy.objects.filter(company=company).count() == 1
    assert AccessRole.objects.filter(company=company, is_default=True).count() == 1


def test_a_failing_receiver_does_not_undo_the_company(django_capture_on_commit_callbacks):
    def broken(**kwargs):
        raise RuntimeError("a module's defaults failed")

    company_created.connect(broken, dispatch_uid="broken")
    try:
        with django_capture_on_commit_callbacks(execute=True):
            company = create_company(name="Shop")
    finally:
        company_created.disconnect(dispatch_uid="broken")

    assert Company.objects.filter(pk=company.pk).exists()
