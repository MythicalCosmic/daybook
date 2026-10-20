import pytest
from aiogram.methods import SendMessage

from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize(
    ("telegram_language", "greeting"),
    [("ru", "Привет"), ("uz", "Salom"), ("en", "Hi"), ("de", "Salom")],  # unknown: Uzbek
)
async def test_the_bot_speaks_the_persons_language(dp, bot, telegram_language, greeting):
    person = updates.tg_user(9_001, language_code=telegram_language)

    await dp.feed_update(bot, updates.message(person, "/start"))

    [reply] = [r for r in bot.requests if isinstance(r, SendMessage)]
    assert reply.text.startswith(f"👋 {greeting}")
