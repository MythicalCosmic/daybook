"""One company everywhere: a company switch in the mini app or the dashboard moves the bot too,
and the bot's chat hears where the person works now, with that company's main menu."""

import pytest
from django.utils import translation

from apps.accounts import company_switch
from apps.companies.models import Branch
from apps.companies.tests.factories import CompanyFactory

pytestmark = pytest.mark.django_db

OWNER_ME = "/api/v1/owner/me/"


@pytest.fixture
def two_companies(member):
    """An owner of a pharmacy (two branches, so it opens first) and of a distributor."""
    shop, supplier = CompanyFactory(name="Demo Dorixona"), CompanyFactory(name="Demo Distribyutor")
    Branch.objects.create(company=shop, name="Yunusobod")
    owner = member.registered(shop, "Owner", user__language="uz", user__telegram_id=1001)
    member.registered(supplier, "Owner", user=owner.user)
    return owner, shop, supplier


@pytest.fixture
def announced(monkeypatch):
    """The Celery jobs queued: (user id, company id)."""
    queued = []
    monkeypatch.setattr(
        "apps.accounts.tasks.announce_company.delay",
        lambda user_id, company_id: queued.append((user_id, company_id)),
    )
    return queued


@pytest.fixture
def sent(monkeypatch):
    """What the bot would send: (bot, chat id, text, markup)."""
    messages = []
    monkeypatch.setattr(
        "apps.notifications.tasks.send_telegram_message.delay",
        lambda bot, chat_id, text, markup=None, *rest: messages.append(
            (bot, chat_id, text, markup)
        ),
    )
    return messages


def test_a_switch_in_the_mini_app_moves_the_bot_once(
    api_as, two_companies, announced, django_capture_on_commit_callbacks
):
    owner, _shop, supplier = two_companies
    client = api_as(owner)

    with django_capture_on_commit_callbacks(execute=True):
        client.patch("/api/v1/me/", {"bot_company": supplier.pk}, format="json")
        client.patch("/api/v1/me/", {"bot_company": supplier.pk}, format="json")  # already there
        client.patch("/api/v1/me/", {"language": "ru"}, format="json")  # no company change

    assert announced == [(owner.user_id, supplier.pk)]


def test_picking_the_company_the_bot_already_works_in_says_nothing(
    api_as, two_companies, announced, django_capture_on_commit_callbacks
):
    owner, shop, _supplier = two_companies

    with django_capture_on_commit_callbacks(execute=True):
        response = api_as(owner).patch("/api/v1/me/", {"bot_company": shop.pk}, format="json")

    assert response.status_code == 200
    assert announced == []


def test_the_dashboards_me_shows_and_switches_the_same_company(
    owner_api, two_companies, announced, django_capture_on_commit_callbacks
):
    owner, shop, supplier = two_companies
    client = owner_api(owner)

    assert client.get(OWNER_ME).json()["bot_company"] == shop.pk
    with django_capture_on_commit_callbacks(execute=True):
        response = client.patch(OWNER_ME, {"bot_company": supplier.pk}, format="json")

    assert response.status_code == 200
    assert response.json()["bot_company"] == supplier.pk
    owner.user.refresh_from_db()
    assert owner.user.bot_company_id == supplier.pk
    assert announced == [(owner.user_id, supplier.pk)]


def test_the_dashboard_refuses_a_company_the_person_doesnt_work_in(
    owner_api, two_companies, announced
):
    owner, _shop, _supplier = two_companies

    response = owner_api(owner).patch(OWNER_ME, {"bot_company": CompanyFactory().pk}, format="json")

    assert response.status_code == 400
    assert announced == []


def test_the_dashboard_still_changes_only_the_language(owner_api, two_companies, announced):
    owner, _shop, _supplier = two_companies

    response = owner_api(owner).patch(OWNER_ME, {"language": "ru"}, format="json")

    assert response.status_code == 200
    assert response.json()["language"] == "ru"
    assert announced == []


@pytest.mark.parametrize(
    ("language", "line"),
    [
        ("uz", "Endi <b>Demo Distribyutor</b> kompaniyasida ishlayapsiz."),
        ("ru", "Теперь вы работаете в компании «<b>Demo Distribyutor</b>»."),
        ("en", "Now working in <b>Demo Distribyutor</b>."),
    ],
)
def test_the_bot_says_where_they_work_now_with_that_companys_menu(
    two_companies, sent, language, line
):
    owner, _shop, supplier = two_companies
    owner.user.language = language
    owner.user.bot_company = supplier
    owner.user.save()

    company_switch.announce(owner.user_id, supplier.pk)

    [(bot, chat_id, text, markup)] = sent
    assert (bot, chat_id, text) == ("employee", 1001, line)
    assert markup["keyboard"]  # the main menu: a reply keyboard
    with translation.override(language):
        assert not any(ord(char) > 0x2FFF for char in text)  # plain text, no emoji


def test_a_switch_overtaken_by_another_says_nothing(two_companies, sent):
    owner, shop, supplier = two_companies
    owner.user.bot_company = shop
    owner.user.save()

    company_switch.announce(owner.user_id, supplier.pk)  # queued for supplier, back on shop since

    assert sent == []
