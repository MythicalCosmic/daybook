"""The organization's bot (docs/DAVOMAT.md §1.5): the token, the test message, one-time link
codes and `claim_link`, and every notification through the one bot. Telegram is never called:
`getMe` and sending are replaced."""

from datetime import timedelta

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramUnauthorizedError
from aiogram.methods import SendMessage
from django.db import connection
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.core import redis as core_redis
from apps.davomat import queries, services
from apps.davomat import telegram as tg
from apps.davomat.audit_actions import DavomatAction
from apps.davomat.models import DavomatSettings, TelegramLink
from apps.inbox import delivery
from apps.notifications import telegram as bots
from apps.notifications.telegram import BotName

pytestmark = pytest.mark.django_db

TOKEN = "7701234567:AAFakeTokenForTestsOnly-abcdefghijkl"


@pytest.fixture
def get_me(monkeypatch):
    """Telegram's getMe: our bot, unless told otherwise."""
    calls = []

    def answer(token):
        calls.append(token)
        if answer.error is not None:
            raise answer.error
        return tg.BotInfo(id=7701234567, username="namuna_davomat_bot", name="Namuna Davomat")

    answer.error = None
    answer.calls = calls
    monkeypatch.setattr(tg, "get_me", answer)
    return answer


@pytest.fixture
def connected(org, get_me, fake_redis):
    return services.connect_bot(org.company, by=org.owner, token=TOKEN)


# The token ---------------------------------------------------------------------------------


def test_connect_the_bot(org, owner_api, get_me, fake_redis, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        response = owner_api(org.owner).put(org.url("telegram/"), {"token": f" {TOKEN} "})

    assert response.status_code == 200, response.content
    assert response.json() | {"checked_at": None} == {
        "configured": True,
        "bot_username": "namuna_davomat_bot",
        "bot_name": "Namuna Davomat",
        "status": "ok",
        "checked_at": None,
    }
    assert get_me.calls == [TOKEN]
    row = DavomatSettings.objects.get(company=org.company)
    assert row.bot_token == TOKEN and row.token_version == 1
    assert queries.bot_token() == TOKEN
    assert core_redis.get_redis().get(core_redis.key("davomat", "bot_token_version")) == "1"
    assert queries.token_version() == 1
    assert AuditLog.objects.filter(action=DavomatAction.TELEGRAM_CONNECTED).exists()


def test_the_token_is_encrypted_and_never_shown(org, owner_api, connected):
    with connection.cursor() as cursor:
        cursor.execute("SELECT bot_token FROM davomat_davomatsettings")
        (stored,) = cursor.fetchone()

    assert stored and TOKEN not in stored
    body = owner_api(org.owner).get(org.url("telegram/")).content.decode()
    assert TOKEN not in body and "token" not in body
    assert TOKEN not in str(AuditLog.objects.values_list("details", flat=True))


def test_a_token_telegram_refuses_is_not_kept(org, owner_api, get_me):
    get_me.error = TelegramUnauthorizedError(method=None, message="Unauthorized")

    refused = owner_api(org.owner).put(org.url("telegram/"), {"token": TOKEN})
    malformed = owner_api(org.owner).put(org.url("telegram/"), {"token": "not a token"})

    assert refused.status_code == malformed.status_code == 400
    assert "token" in refused.json() and "token" in malformed.json()
    assert DavomatSettings.objects.get(company=org.company).bot_token == ""


def test_telegram_out_of_reach_keeps_nothing(org, owner_api, get_me):
    get_me.error = OSError("network down")

    response = owner_api(org.owner).put(org.url("telegram/"), {"token": TOKEN})

    assert response.status_code == 400 and "detail" in response.json()
    assert DavomatSettings.objects.get(company=org.company).bot_status == "not_set"


def test_the_same_token_again_keeps_the_version(org, connected, get_me):
    row = services.connect_bot(org.company, by=org.owner, token=TOKEN)

    assert row.token_version == 1


def test_disconnect_the_bot(org, owner_api, connected):
    response = owner_api(org.owner).delete(org.url("telegram/"))

    assert response.status_code == 204
    row = DavomatSettings.objects.get(company=org.company)
    assert (row.bot_token, row.bot_username, row.bot_status) == ("", "", "not_set")
    assert row.token_version == 2 and queries.bot_token() == ""


def test_only_settings_holders_touch_the_bot(org, owner_api, get_me):
    manager = org.user("manager", "bekzod")
    api = owner_api(manager)

    assert api.get(org.url("telegram/")).status_code == 403
    assert api.put(org.url("telegram/"), {"token": TOKEN}).status_code == 403
    assert api.post(org.url("telegram/test/")).status_code == 403
    assert get_me.calls == []


def test_daybook_has_no_bot_settings(org, owner_api, settings):
    settings.EDITION = "daybook"

    assert owner_api(org.owner).get(org.url("telegram/")).status_code == 404


# The test message ------------------------------------------------------------------------------


def test_a_test_message_reaches_you(org, owner_api, connected, sent_messages):
    org.owner.user.telegram_id = 99001
    org.owner.user.save()

    response = owner_api(org.owner).post(org.url("telegram/test/"))

    assert response.status_code == 200 and response.json() == {"sent": True}
    assert [(m["bot"], m["chat_id"], m["text"]) for m in sent_messages] == [
        (BotName.OWNER, 99001, "Test message from Davomat.")
    ]


def test_no_test_message_without_your_telegram_or_a_bot(org, owner_api, get_me, fake_redis):
    api = owner_api(org.owner)

    no_bot = api.post(org.url("telegram/test/"))
    services.connect_bot(org.company, by=org.owner, token=TOKEN)
    not_linked = api.post(org.url("telegram/test/"))

    assert no_bot.status_code == not_linked.status_code == 400


def test_a_bot_you_never_started_says_so(org, owner_api, connected, monkeypatch):
    org.owner.user.telegram_id = 99001
    org.owner.user.save()

    def refuse(*args, **kwargs):
        raise TelegramForbiddenError(method=SendMessage(chat_id=1, text="x"), message="blocked")

    monkeypatch.setattr(bots, "send_message", refuse)

    response = owner_api(org.owner).post(org.url("telegram/test/"))

    assert response.status_code == 400 and "Start" in response.json()["detail"]


def test_a_revoked_token_marks_the_bot(org, owner_api, connected, monkeypatch):
    org.owner.user.telegram_id = 99001
    org.owner.user.save()

    def refuse(*args, **kwargs):
        raise TelegramUnauthorizedError(method=SendMessage(chat_id=1, text="x"), message="no")

    monkeypatch.setattr(bots, "send_message", refuse)

    assert owner_api(org.owner).post(org.url("telegram/test/")).status_code == 400
    assert DavomatSettings.objects.get(company=org.company).bot_status == "invalid"


# Link codes --------------------------------------------------------------------------------


def test_a_link_for_an_employee_links_their_telegram(org, owner_api, connected):
    person = org.employee("Aziza")

    response = owner_api(org.owner).post(org.url(f"employees/{person.pk}/telegram-link/"))

    assert response.status_code == 201, response.content
    data = response.json()
    assert data["url"] == f"https://t.me/namuna_davomat_bot?start=link_{data['code']}"
    assert len(f"link_{data['code']}") <= 64
    link = TelegramLink.objects.get()
    assert link.code_hash != data["code"] and link.expires_at > timezone.now() + timedelta(hours=23)
    claimed = services.claim_link(f"link_{data['code']}", 4242, "aziza_k", "Aziza")
    assert claimed == person
    person.user.refresh_from_db()
    assert (person.user.telegram_id, person.user.telegram_username) == (4242, "aziza_k")
    assert person.first_name == "Aziza"  # the administrator's names stay
    row = owner_api(org.owner).get(org.url(f"employees/{person.pk}/")).json()
    assert row["telegram_linked"] is True
    assert AuditLog.objects.filter(action=DavomatAction.TELEGRAM_LINKED).exists()


def test_a_link_works_once(org, connected):
    person = org.employee("Aziza")
    made = services.make_link(person, by=org.owner)
    services.claim_link(made.code, 4242, None, None)

    again = services.claim_link(made.code, 4242, None, None)  # the same account: fine

    assert again == person
    with pytest.raises(services.LinkRefused) as refused:
        services.claim_link(made.code, 5353, None, None)
    assert refused.value.code == "used"


def test_an_old_or_unknown_link_is_refused(org, connected, monkeypatch):
    person = org.employee("Aziza")
    made = services.make_link(person, by=org.owner)
    later = timezone.now() + timedelta(hours=25)
    monkeypatch.setattr("django.utils.timezone.now", lambda: later)

    with pytest.raises(services.LinkRefused) as expired:
        services.claim_link(made.code, 4242, None, None)
    with pytest.raises(services.LinkRefused) as unknown:
        services.claim_link("link_nothing", 4242, None, None)

    assert (expired.value.code, unknown.value.code) == ("expired", "not_found")
    assert str(expired.value)  # a message the bot can show


def test_a_new_link_replaces_the_old_one(org, connected):
    person = org.employee("Aziza")
    old = services.make_link(person, by=org.owner)
    services.make_link(person, by=org.owner)

    with pytest.raises(services.LinkRefused):
        services.claim_link(old.code, 4242, None, None)


def test_someone_who_left_cant_link(org, connected):
    person = org.employee("Aziza")
    made = services.make_link(person, by=org.owner)
    services.leave(person, by=org.owner)

    with pytest.raises(services.LinkRefused) as refused:
        services.claim_link(made.code, 4242, None, None)

    assert refused.value.code == "inactive"


def test_a_telegram_account_moves_to_its_new_owner(org, connected):
    first = org.employee("Aziza")
    second = org.employee("Bobur")
    services.claim_link(services.make_link(first, by=org.owner).code, 4242, None, None)

    services.claim_link(services.make_link(second, by=org.owner).code, 4242, None, None)

    first.user.refresh_from_db()
    second.user.refresh_from_db()
    assert first.user.telegram_id is None and second.user.telegram_id == 4242


def test_unlink(org, owner_api, connected):
    person = org.employee("Aziza")
    services.claim_link(services.make_link(person, by=org.owner).code, 4242, None, None)

    response = owner_api(org.owner).delete(org.url(f"employees/{person.pk}/telegram-link/"))

    assert response.status_code == 204
    person.user.refresh_from_db()
    assert person.user.telegram_id is None


def test_no_link_without_a_bot(org, owner_api):
    person = org.employee("Aziza")

    response = owner_api(org.owner).post(org.url(f"employees/{person.pk}/telegram-link/"))

    assert response.status_code == 400


# One bot for everything --------------------------------------------------------------------------


def test_every_message_goes_through_the_organizations_bot(org, connected, settings):
    settings.EMPLOYEE_BOT_TOKEN, settings.OWNER_BOT_TOKEN = "1:EMPLOYEE", "2:OWNER"

    assert bots._token(BotName.EMPLOYEE) == bots._token(BotName.OWNER) == TOKEN
    assert delivery.bots_for(org.owner.user, "employee") == [BotName.OWNER]
    assert delivery.bots_for(org.owner.user, "owner", org.owner) == [BotName.OWNER]


def test_daybook_keeps_its_two_bots(org, connected, settings):
    settings.EDITION = "daybook"
    settings.EMPLOYEE_BOT_TOKEN, settings.OWNER_BOT_TOKEN = "1:EMPLOYEE", "2:OWNER"

    assert bots._token(BotName.EMPLOYEE) == "1:EMPLOYEE"
    assert bots._token(BotName.OWNER) == "2:OWNER"
    assert delivery.bots_for(org.owner.user, "employee") == [BotName.EMPLOYEE]


def test_no_bot_connected_means_nothing_is_sent(org, settings):
    settings.TELEGRAM_DRY_RUN = False

    assert bots._token(BotName.EMPLOYEE) == ""
    assert bots.send_message("employee", 99001, "Hello") is None
