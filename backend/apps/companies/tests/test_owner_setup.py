"""O setup/ ("Get started") and O invite/ (§4.4, §6.2)."""

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.companies import services
from apps.companies.audit_actions import CompanyAction
from apps.groups.models import TelegramGroup
from apps.members import queries as members_queries

pytestmark = pytest.mark.django_db


def url(company, path):
    return f"/api/v1/owner/companies/{company.pk}/{path}"


@pytest.fixture
def owner(company, member):
    return member(company, "Owner")


def steps_by_key(response) -> dict:
    return {step["key"]: step for step in response.json()["steps"]}


def test_get_started_lists_the_registered_steps_with_done_flags(company, owner, owner_api, member):
    response = owner_api(owner).get(url(company, "setup/"))

    assert response.status_code == 200
    steps = steps_by_key(response)
    for key in ("companies.branches", "companies.invite", "companies.modules", "groups.connect"):
        assert key in steps and steps[key]["done"] is False
    assert steps["companies.branches"]["url"] == "settings/branches"
    data = response.json()
    assert data["dismissed"] is False and data["can_dismiss"] is True
    assert data["done"] == 0 and data["total"] == len(data["steps"])
    orders = [step["order"] for step in data["steps"]]
    assert orders == sorted(orders)

    # Each step turns done when its condition is met.
    branch = company.branches.get()
    branch.address = "Bunyodkor 12"
    branch.save()
    member(company, "Employee")
    services.set_features(company, by=owner, features=["finance"])
    TelegramGroup.objects.create(company=company, chat_id=-100123, title="Jamoa")

    steps = steps_by_key(owner_api(owner).get(url(company, "setup/")))
    for key in ("companies.branches", "companies.invite", "companies.modules", "groups.connect"):
        assert steps[key]["done"] is True, key


def test_steps_follow_the_callers_permissions(company, member, owner_api):
    manager = member(company, "Manager")  # groups.manage and members.approve, no company.settings

    steps = steps_by_key(owner_api(manager).get(url(company, "setup/")))

    assert "groups.connect" in steps and "companies.invite" in steps
    assert "companies.branches" not in steps and "companies.modules" not in steps
    assert owner_api(manager).get(url(company, "setup/")).json()["can_dismiss"] is False


def test_switched_off_modules_hide_their_steps(company, owner, owner_api, isolated_registries):
    isolated_registries.register_setup_step(
        "companies.test_sales",
        perm=None,
        order=50,
        label="Registers",
        description="",
        url="sales/registers",
        done=lambda company: False,
        feature="sales",
    )

    assert "companies.test_sales" not in steps_by_key(owner_api(owner).get(url(company, "setup/")))
    services.set_features(company, by=owner, features=["sales"])
    assert "companies.test_sales" in steps_by_key(owner_api(owner).get(url(company, "setup/")))


def test_dismiss_and_resume(company, owner, owner_api):
    dismissed = owner_api(owner).post(url(company, "setup/dismiss/"))

    assert dismissed.status_code == 200 and dismissed.json()["dismissed"] is True
    company.refresh_from_db()
    assert company.setup_completed_at is not None
    me = owner_api(owner).get("/api/v1/owner/me/").json()
    assert next(c for c in me["companies"] if c["id"] == company.pk)["setup_completed"] is True
    assert AuditLog.objects.filter(action=CompanyAction.SETUP_DISMISSED).count() == 1

    resumed = owner_api(owner).post(url(company, "setup/resume/"))
    assert resumed.json()["dismissed"] is False


def test_the_today_brief_shows_get_started_until_it_is_done_or_dismissed(company, owner):
    """The owner bot's /today (and briefings) get a "Get started" line from the section."""
    from django.utils import timezone

    from apps.console import registry

    def brief():
        now = timezone.now()
        return dict(registry.collect_brief_sections(owner, now.date(), now, branch_ids=None))

    section = brief()["companies.setup"]
    total = int(section["lines"][0].split(" of ")[1].split()[0])
    assert section["title"] == "Get started" and section["lines"][0].startswith("0 of")

    branch = company.branches.get()
    branch.address = "Bunyodkor 12"
    branch.save()
    assert brief()["companies.setup"]["lines"][0] == f"1 of {total} steps done"

    services.dismiss_setup(company, by=owner)
    owner.company.refresh_from_db()
    assert "companies.setup" not in brief()


def test_only_company_settings_may_dismiss(company, member, owner_api, other_company):
    manager = member(company, "Manager")

    assert owner_api(manager).post(url(company, "setup/dismiss/")).status_code == 403
    owner = member(company, "Owner")
    assert owner_api(owner).get(url(other_company, "setup/")).status_code == 404


def test_invite_page_data(company, owner, owner_api, member, settings):
    settings.EMPLOYEE_BOT_USERNAME = "daybook_test_bot"
    member(company, "Employee")
    member(company, "Employee", status="pending", onboarded_at=timezone.now())
    # Still filling in their details: nothing to decide yet, like the Join requests badge.
    member(company, "Employee", status="pending", onboarded_at=None)

    response = owner_api(owner).get(url(company, "invite/"))

    assert response.status_code == 200
    data = response.json()
    assert data["link"] == f"https://t.me/daybook_test_bot?start=c_{company.invite_code}"
    assert data["start_param"] == f"c_{company.invite_code}"
    assert data["company"]["name"] == company.name
    assert data["members"] == {"approved": 2, "pending": 1}
    assert data["members"]["pending"] == members_queries.pending_count(company)
    assert data["branches"] == [company.branches.get().name]


def test_regenerating_the_invite_kills_the_old_link(company, owner, owner_api, settings):
    settings.EMPLOYEE_BOT_USERNAME = "daybook_test_bot"
    old = company.invite_code

    response = owner_api(owner).post(url(company, "invite/regenerate/"))

    assert response.status_code == 200
    company.refresh_from_db()
    assert company.invite_code != old
    assert response.json()["link"].endswith(company.invite_code)
    assert AuditLog.objects.filter(action=CompanyAction.INVITE_REGENERATED).exists()


def test_the_invite_needs_members_approve(company, member, owner_api, other_company):
    accountant = member(company, "Accountant")
    manager = member(company, "Manager")

    assert owner_api(accountant).get(url(company, "invite/")).status_code == 403
    assert owner_api(manager).get(url(company, "invite/")).status_code == 200
    assert owner_api(manager).get(url(other_company, "invite/")).status_code == 404


def test_without_a_bot_username_the_link_is_empty(company, owner, owner_api, settings):
    settings.EMPLOYEE_BOT_USERNAME = ""

    assert owner_api(owner).get(url(company, "invite/")).json()["link"] == ""
