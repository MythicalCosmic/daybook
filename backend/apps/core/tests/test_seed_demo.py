from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.accounts.models import User
from apps.companies.models import Company, Feature
from apps.core.management.commands import seed_demo
from apps.members.models import Membership
from apps.reports import kpis
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db

REAL_OWNER = 6_589_960_007


def seed(**options) -> str:
    out = StringIO()
    call_command("seed_demo", stdout=out, **options)
    return out.getvalue()


@pytest.fixture
def debug(settings):
    settings.DEBUG = True


@pytest.fixture
def demo_calls(monkeypatch):
    """Records which apps' demo.py and defaults.ensure ran, and for which company."""
    calls = []
    for label in ("sales", "finance"):

        def demo(company, people, now, label=label):
            calls.append(("demo", label, company.slug, sorted(people)))

        def ensure(company, label=label):
            calls.append(("ensure", label, company.slug))

        monkeypatch.setattr(f"apps.{label}.demo.seed", demo)
        monkeypatch.setattr(f"apps.{label}.defaults.ensure", ensure)
    return calls


def demos(calls) -> list[str]:
    return [call[1] for call in calls if call[0] == "demo"]


def test_the_demo_builds_and_rebuilds(debug):
    seed()
    seed(reset=True)  # everything the demo made can be removed again

    company = Company.objects.get(slug="demo-shop")
    assert company.memberships.filter(status=Membership.Status.APPROVED).count() == 6
    today = timezone.localdate()
    report = kpis.team(company, today - timedelta(days=14), today, timezone.now())
    with_work = {str(person): score for person, score in report.rows if score.total}
    assert {"Alisher Valiyev", "Madina Saidova", "Jasur Tursunov", "Nigora Azimova"} <= set(
        with_work
    )
    assert with_work["Nigora Azimova"].on_time_percent == 100
    assert with_work["Jasur Tursunov"].missed == 2


def test_the_demo_stays_out_of_production():
    with pytest.raises(CommandError):
        seed()


def test_an_existing_demo_needs_reset(debug):
    seed()
    with pytest.raises(CommandError, match="--reset"):
        seed()


def test_the_shop_has_two_branches_and_every_module(debug):
    seed()

    shop = Company.objects.get(slug="demo-shop")
    assert sorted(shop.features) == sorted(Feature.values)
    assert [b.code for b in shop.branches.order_by("order")] == ["CHL", "YNS"]
    approved = shop.memberships.filter(status=Membership.Status.APPROVED)
    assert all(m.home_branch_id and m.branches.filter(pk=m.home_branch_id) for m in approved)
    owner = approved.get(user__telegram_id=seed_demo.OWNER)
    assert owner.branches.count() == 2
    # Every task belongs to its assignee's home branch, as the create paths do it.
    tasks = Task.objects.for_company(shop).select_related("assignee")
    assert tasks.exists()
    assert all(task.branch_id == task.assignee.home_branch_id for task in tasks)
    assert tasks.filter(branch__code="YNS").exists()


def test_the_cafe_is_a_second_smaller_company_with_the_same_owner(debug):
    seed()

    cafe = Company.objects.get(slug="demo-cafe")
    assert sorted(cafe.features) == sorted(seed_demo.CAFE_FEATURES)
    assert cafe.memberships.filter(status=Membership.Status.APPROVED).count() == 4
    [branch] = cafe.branches.all()
    assert branch.manager.user.telegram_id == seed_demo.CAFE_MANAGER
    owner = User.objects.get(telegram_id=seed_demo.OWNER)
    owned = Membership.objects.filter(user=owner, role__is_owner=True, status="approved")
    assert sorted(owned.values_list("company__slug", flat=True)) == ["demo-cafe", "demo-shop"]
    assert Task.objects.for_company(cafe).filter(branch=branch).count() > 14


def test_owner_tg_makes_a_real_account_owner_of_both_companies(debug):
    seed(owner_tg=REAL_OWNER)

    user = User.objects.get(telegram_id=REAL_OWNER)
    memberships = Membership.objects.filter(user=user).select_related("company", "role")
    assert sorted(m.company.slug for m in memberships) == ["demo-cafe", "demo-shop"]
    for membership in memberships:
        assert membership.status == Membership.Status.APPROVED
        assert membership.role.is_owner
        assert membership.is_onboarded
        assert membership.home_branch is not None
        assert membership.branches.count() == membership.company.branches.count()

    # A rebuild keeps the real account (only the demo people go) and makes it owner again.
    user.first_name = "Real"
    user.save()
    seed(reset=True, owner_tg=REAL_OWNER)
    assert User.objects.get(telegram_id=REAL_OWNER).first_name == "Real"
    assert Membership.objects.filter(user=user).count() == 2

    # A rebuild without it removes the memberships but still not the account.
    seed(reset=True)
    assert User.objects.filter(telegram_id=REAL_OWNER).exists()
    assert not Membership.objects.filter(user=user).exists()


def test_owner_tg_on_an_existing_demo_only_adds_the_owner(debug):
    seed()
    shop = Company.objects.get(slug="demo-shop")
    tasks = Task.objects.for_company(shop).count()

    output = seed(owner_tg=REAL_OWNER)
    seed(owner_tg=REAL_OWNER)  # twice is fine

    assert "Owner of Demo Café, Demo Shop" in output
    assert Company.objects.get(slug="demo-shop").pk == shop.pk
    assert Task.objects.for_company(shop).count() == tasks
    assert Membership.objects.filter(user__telegram_id=REAL_OWNER).count() == 2


def test_owner_tg_cant_be_one_of_the_demo_people(debug):
    with pytest.raises(CommandError, match="demo people"):
        seed(owner_tg=seed_demo.WORKER)


def test_module_demos_and_defaults_run(debug, demo_calls):
    seed(owner_tg=REAL_OWNER)

    people = ["jasur", "madina", "manager", "nigora", "owner", "worker"]
    assert ("demo", "sales", "demo-shop", people) in demo_calls
    assert ("demo", "finance", "demo-shop", people) in demo_calls
    # Module demos fill the shop only; defaults are made for both companies, before the demos.
    assert {call[2] for call in demo_calls if call[0] == "demo"} == {"demo-shop"}
    ensured = [call for call in demo_calls if call[0] == "ensure"]
    assert {(call[1], call[2]) for call in ensured} >= {
        ("sales", "demo-shop"),
        ("sales", "demo-cafe"),
        ("finance", "demo-shop"),
        ("finance", "demo-cafe"),
    }
    first_demo = next(i for i, call in enumerate(demo_calls) if call[0] == "demo")
    assert all(demo_calls.index(call) < first_demo for call in ensured)


def test_module_demos_never_see_the_real_owner(debug, monkeypatch):
    seen = []

    def demo(company, people, now):
        seen.append(Membership.objects.filter(user__telegram_id=REAL_OWNER).count())

    monkeypatch.setattr("apps.sales.demo.seed", demo)
    seed(owner_tg=REAL_OWNER)

    assert seen == [0]
    assert Membership.objects.filter(user__telegram_id=REAL_OWNER).count() == 2


def test_only_runs_the_listed_apps_demos(debug, demo_calls):
    output = seed(only="sales")

    assert demos(demo_calls) == ["sales"]
    assert "Module demo data: sales." in output
    # Defaults are not narrowed: a module's demo may rely on another module's rows.
    assert {call[1] for call in demo_calls if call[0] == "ensure"} == {"sales", "finance"}


def test_demo_apps_from_the_environment(debug, demo_calls, monkeypatch):
    monkeypatch.setenv("DEMO_APPS", "finance, sales")
    seed()
    assert sorted(demos(demo_calls)) == ["finance", "sales"]

    demo_calls.clear()
    seed(reset=True, only="finance")  # --only wins over the environment
    assert demos(demo_calls) == ["finance"]


def test_unknown_demo_apps_are_refused(debug, monkeypatch):
    with pytest.raises(CommandError, match="nope"):
        seed(only="sales,nope")
    monkeypatch.setenv("DEMO_APPS", "nope")
    with pytest.raises(CommandError, match="nope"):
        seed()
    assert not Company.objects.filter(slug="demo-shop").exists()
