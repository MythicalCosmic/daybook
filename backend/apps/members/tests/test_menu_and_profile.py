"""What the mini app learns about a membership, and the bot menu registry."""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.companies.tests.factories import BranchFactory
from apps.members import bot_menu
from apps.members.bot_messages import main_menu, miniapp_url

pytestmark = pytest.mark.django_db


def me(membership) -> dict:
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(membership.user)}")
    [entry] = api.get("/api/v1/me/").data["memberships"]
    return entry


def test_the_company_and_branches_reach_the_mini_app(company, member):
    worker = member.registered(company)
    here = company.branches.get()
    there = BranchFactory(company=company, name="Yunusobod")
    worker.branches.set([here, there])
    worker.home_branch = here
    worker.save()
    company.features = ["sales", "hr"]
    company.team_directory_phones = False
    company.save()

    entry = me(worker)

    assert entry["company"] == {
        "id": company.pk,
        "name": company.name,
        "timezone": company.timezone,
        "features": ["sales", "hr"],
        "owner_sees_personal_tasks": True,
        "base_currency": "UZS",
        "team_directory_phones": False,
    }
    assert entry["home_branch"] == {"id": here.pk, "name": here.name}
    assert entry["branch_ids"] == sorted([here.pk, there.pk])
    assert entry["suspended_until"] is None


def test_new_permissions_are_listed(company, member):
    accountant = member.registered(company, "Accountant")

    permissions = me(accountant)["permissions"]

    assert "payroll.view" in permissions
    assert "finance.manage" in permissions
    assert "hr.sensitive" not in permissions


@pytest.fixture
def no_buttons(monkeypatch):
    monkeypatch.setattr(bot_menu, "_buttons", {})


def texts(markup) -> list[list[str]]:
    return [[button.text for button in row] for row in markup.keyboard]


def test_registered_buttons_join_the_menu_for_the_people_who_should_see_them(
    company, member, no_buttons, settings
):
    settings.EMPLOYEE_MINIAPP_URL = "https://app.example.com/app/"
    worker = member.registered(company)
    bot_menu.register_menu_button(
        "📍 Check in", order=10, visible=lambda m: True, web_app_screen="attendance"
    )
    bot_menu.register_menu_button("💸 Expense", order=20, visible=lambda m: True)
    bot_menu.register_menu_button("🔒 Hidden", order=5, visible=lambda m: False)

    markup = main_menu(worker)

    assert texts(markup) == [
        ["📋 My tasks", "➕ New task"],
        ["📍 Check in", "💸 Expense"],
        ["📱 Open app"],
    ]
    check_in = markup.keyboard[1][0]
    assert check_in.web_app.url == "https://app.example.com/app/?screen=attendance"
    assert markup.keyboard[1][1].web_app is None


def test_without_a_member_or_the_app_buttons_stay_plain(company, member, no_buttons):
    bot_menu.register_menu_button(
        "📍 Check in", order=1, visible=lambda m: True, web_app_screen="x"
    )

    assert texts(main_menu()) == [["📋 My tasks", "➕ New task"]]
    markup = main_menu(member.registered(company))
    assert markup.keyboard[1][0].web_app is None  # no mini app configured


def test_a_broken_visibility_check_only_hides_its_own_button(company, member, no_buttons):
    def broken(member):
        raise RuntimeError("module bug")

    bot_menu.register_menu_button("A", order=1, visible=broken)
    bot_menu.register_menu_button("B", order=2, visible=lambda m: True)

    assert [b.msgid for b in bot_menu.buttons_for(member.registered(company))] == ["B"]


def test_a_button_is_registered_once(no_buttons):
    bot_menu.register_menu_button("A", order=1, visible=lambda m: True)

    with pytest.raises(bot_menu.DuplicateMenuButton):
        bot_menu.register_menu_button("A", order=2, visible=lambda m: True)


def test_miniapp_links_to_a_screen(settings):
    settings.EMPLOYEE_MINIAPP_URL = "https://app.example.com/app/?v=2"

    assert miniapp_url("payslip:12") == "https://app.example.com/app/?v=2&screen=payslip%3A12"
    assert miniapp_url() == "https://app.example.com/app/?v=2"
