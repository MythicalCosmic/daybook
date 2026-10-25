import pytest

from apps.accounts.models import User
from apps.accounts.services import sync_telegram_user

pytestmark = pytest.mark.django_db


def sync(**overrides) -> User:
    params = {
        "telegram_id": 777,
        "username": "ali",
        "first_name": "Ali",
        "last_name": "Valiyev",
        "language_code": "ru",
    }
    return sync_telegram_user(**(params | overrides))


def test_first_contact_creates_a_user_without_a_password():
    user = sync()

    assert user.username == "tg777"
    assert user.telegram_username == "ali"
    assert user.get_full_name() == "Ali Valiyev"
    assert user.language == "ru"
    assert not user.has_usable_password()


def test_profile_changes_are_saved():
    sync()

    user = sync(username="ali_new", first_name="Alisher")

    user.refresh_from_db()
    assert (user.telegram_username, user.first_name) == ("ali_new", "Alisher")
    assert User.objects.count() == 1


def test_language_is_only_taken_from_telegram_on_first_contact():
    user = sync(language_code="ru")
    user.language = "en"
    user.save()

    assert sync(language_code="ru").language == "en"


@pytest.mark.parametrize("language_code", ["de", None, ""])
def test_unsupported_language_falls_back_to_uzbek(language_code):
    assert sync(language_code=language_code).language == "uz"
