"""The person's chat with the employee bot: the language follows a change made in the mini app
(contract 11), and someone in several companies works in the one they picked (audit X-1)."""

import pytest
from asgiref.sync import async_to_sync
from django.utils import timezone

from apps.accounts import services, telegram_chat
from apps.accounts.tests.factories import UserFactory
from apps.companies.tests.factories import CompanyFactory
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def relabels(monkeypatch):
    queued = []
    monkeypatch.setattr(
        "apps.accounts.api.relabel_employee_chat.delay", lambda user_id: queued.append(user_id)
    )
    return queued


def test_a_new_language_relabels_the_bot_chat_once(
    api_as, company, member, relabels, django_capture_on_commit_callbacks
):
    worker = member.registered(company, user__language="uz")
    client = api_as(worker)

    with django_capture_on_commit_callbacks(execute=True):
        client.patch("/api/v1/me/", {"language": "ru"}, format="json")
        client.patch("/api/v1/me/", {"language": "ru"}, format="json")  # unchanged: nothing

    assert relabels == [worker.user.pk]


def test_set_language():
    user = UserFactory(language="uz")
    assert services.set_language(user, "ru") is True
    assert services.set_language(user, "ru") is False
    user.refresh_from_db()
    assert user.language == "ru"
    with pytest.raises(ValueError):
        services.set_language(user, "de")


def test_someone_in_two_companies_works_in_the_one_they_picked(member):
    first, second = CompanyFactory(name="Demo Dorixona"), CompanyFactory(name="Demo Distribyutor")
    shop = member.registered(first)
    supplier = member.registered(second, user=shop.user)
    TaskFactory(assignee=shop)  # the shop has the open work

    assert services.bot_membership(shop.user) == shop  # the busiest company first

    services.remember_company(shop.user, second.pk)
    assert services.bot_membership(shop.user) == supplier
    assert services.membership_in(shop.user, first.pk) == shop


def test_one_company_is_just_that_one(company, member):
    worker = member.registered(company)
    assert services.bot_membership(worker.user) == worker


def test_relabel_sets_the_menus_and_sends_the_new_keyboard(bot_double, company, member):
    worker = member.registered(company, user__language="ru")

    async_to_sync(telegram_chat.relabel)(
        bot_double, worker.user.telegram_id, worker.user, worker, silent=True
    )

    calls = {type(call).__name__: call for call in bot_double.calls}
    assert calls["SetMyCommands"].scope.chat_id == worker.user.telegram_id
    assert [c.command for c in calls["SetMyCommands"].commands][-2:] == ["language", "help"]
    message = calls["SendMessage"]
    assert message.text.startswith("Теперь пишу по-русски")
    assert message.disable_notification is True
    assert message.reply_markup.keyboard  # the main menu, in Russian


def test_people_in_several_companies_get_company_in_their_menu(bot_double, member):
    first, second = CompanyFactory(), CompanyFactory()
    shop = member.registered(first)
    member.registered(second, user=shop.user)

    async_to_sync(telegram_chat.relabel)(bot_double, 1, shop.user, shop, confirm=False)

    [commands] = [call for call in bot_double.calls if type(call).__name__ == "SetMyCommands"]
    assert "company" in [command.command for command in commands.commands]


def test_the_mini_app_change_reaches_only_members(settings, company, member, monkeypatch):
    sent = []
    monkeypatch.setattr(telegram_chat, "asyncio", type("A", (), {"run": sent.append}))
    settings.EMPLOYEE_BOT_TOKEN = "42:TEST"
    settings.TELEGRAM_DRY_RUN = False
    worker = member.registered(company)
    newcomer = member(company, status="pending")

    telegram_chat.relabel_employee_chat(worker.user.pk)
    telegram_chat.relabel_employee_chat(newcomer.user.pk)

    assert len(sent) == 1
    sent[0].close()  # the coroutine that would have run


def test_tasks_stay_untouched(company, member):
    """Nothing here writes tasks: a smoke check that the helpers only read."""
    worker = member.registered(company)
    TaskFactory(assignee=worker, due_at=timezone.now())
    services.bot_membership(worker.user)
    assert Task.objects.count() == 1


class _BotDouble:
    def __init__(self):
        self.calls = []

    async def __call__(self, method):
        self.calls.append(method)
        return True

    async def set_my_commands(self, commands, scope=None, language_code=None):
        from aiogram.methods import SetMyCommands

        self.calls.append(SetMyCommands(commands=commands, scope=scope))

    async def set_chat_menu_button(self, chat_id=None, menu_button=None):
        from aiogram.methods import SetChatMenuButton

        self.calls.append(SetChatMenuButton(chat_id=chat_id, menu_button=menu_button))

    async def send_message(self, chat_id, text, reply_markup=None, disable_notification=None):
        from aiogram.methods import SendMessage

        self.calls.append(
            SendMessage(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                disable_notification=disable_notification,
            )
        )


@pytest.fixture
def bot_double():
    return _BotDouble()


def test_me_shows_and_switches_the_company(api_as, member):
    from apps.companies.models import Branch

    shop, supplier = CompanyFactory(name="Demo Dorixona"), CompanyFactory(name="Demo Distribyutor")
    Branch.objects.create(company=shop, name="Yunusobod")  # the shop has two branches
    owner = member.registered(shop, "Owner")
    member.registered(supplier, "Owner", user=owner.user)
    client = api_as(owner)

    # A first visit: the company they own with the most branches, as the dashboard opens.
    assert client.get("/api/v1/me/").json()["bot_company"] == shop.pk

    response = client.patch("/api/v1/me/", {"bot_company": supplier.pk}, format="json")
    assert response.json()["bot_company"] == supplier.pk
    owner.user.refresh_from_db()
    assert owner.user.bot_company_id == supplier.pk

    stranger = CompanyFactory()
    refused = client.patch("/api/v1/me/", {"bot_company": stranger.pk}, format="json")
    assert refused.status_code == 400
