import pytest
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from apps.accounts.models import User
from apps.members.models import Membership
from bot import deeplinks
from bot.deeplinks import StartParamError, register_start_param, resolve, unregister_start_param
from tests import updates


@pytest.fixture
def opened():
    """A `test_` deep link that records what it was given."""
    calls = []

    async def handler(message: Message, payload: str, *, user: User, state: FSMContext) -> None:
        calls.append({"payload": payload, "user": user, "state": state})
        await message.answer(f"opened {payload}")

    register_start_param("test_", handler)
    yield calls
    unregister_start_param("test_")


@pytest.mark.parametrize("prefix", ["login", "Login_", "lo-gin_", "a_b_", "_", "9job_", ""])
def test_malformed_prefixes_are_refused(prefix):
    with pytest.raises(StartParamError):
        register_start_param(prefix, lambda *args, **kwargs: None)


def test_the_invite_prefix_is_reserved():
    with pytest.raises(StartParamError, match="reserved"):
        register_start_param("c_", lambda *args, **kwargs: None)


def test_a_prefix_is_registered_once(opened):
    with pytest.raises(StartParamError, match="already"):
        register_start_param("test_", lambda *args, **kwargs: None)


def test_resolve_finds_the_handler_and_the_payload():
    async def handler(message, payload, *, user, state):
        pass

    register_start_param("res_", handler)
    try:
        assert resolve("res_Ab-12") == (handler, "Ab-12")
        assert resolve("res_") == (handler, "")  # the handler explains an incomplete link
        assert "res_" in deeplinks.registered_prefixes()
        for unclaimed in (None, "", "c_abc", "other_1", "res", "res_ab cd", "res_" + "x" * 64):
            assert resolve(unclaimed) is None, unclaimed
    finally:
        unregister_start_param("res_")


def test_unregistering_frees_the_prefix(opened):
    unregister_start_param("test_")
    assert resolve("test_1") is None
    unregister_start_param("test_")  # forgetting twice is fine


# Handlers reach the ORM from worker threads, so test data must really be committed.
@pytest.mark.django_db(transaction=True)
async def test_start_sends_a_registered_deep_link_to_its_handler(dp, bot, opened):
    # Someone the bot has never seen: deep links run before the member gate.
    await dp.feed_update(bot, updates.message(updates.tg_user(701), "/start test_42"))

    [call] = opened
    assert call["payload"] == "42"
    assert call["user"].telegram_id == 701
    assert isinstance(call["state"], FSMContext)
    assert bot.sent_texts() == ["opened 42"]  # no invite answer on top
    assert not await Membership.objects.filter(user__telegram_id=701).aexists()


@pytest.mark.django_db(transaction=True)
async def test_an_unclaimed_parameter_is_still_an_invite(dp, bot, opened, company):
    stranger = updates.tg_user(702)
    await dp.feed_update(bot, updates.message(stranger, "/start other_42"))
    await dp.feed_update(bot, updates.pick_language(stranger))  # a new person picks first
    assert "invalid or has expired" in bot.sent_texts()[-1]

    tg = updates.tg_user(703)
    await dp.feed_update(bot, updates.message(tg, f"/start {company.invite_start_param}"))
    await dp.feed_update(bot, updates.pick_language(tg))  # a new person picks first
    assert await Membership.objects.filter(user__telegram_id=703, company=company).aexists()
    assert opened == []


@pytest.mark.django_db(transaction=True)
async def test_deep_links_only_open_in_private_chats(dp, bot, opened):
    await dp.feed_update(
        bot, updates.message(updates.tg_user(704), "/start test_42", chat_type="supergroup")
    )

    assert opened == []
