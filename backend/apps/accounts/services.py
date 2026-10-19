from django.db import IntegrityError, transaction

from apps.accounts.models import User
from apps.core.models import Language


def sync_telegram_user(
    *,
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    language_code: str | None,
) -> User:
    """Return the User for a Telegram account, creating it or refreshing its profile."""
    profile = {
        "telegram_username": username or "",
        "first_name": (first_name or "")[:150],
        "last_name": (last_name or "")[:150],
    }
    user = User.objects.filter(telegram_id=telegram_id).first()
    if user is None:
        user = User(
            username=f"tg{telegram_id}",
            telegram_id=telegram_id,
            language=_language(language_code),
            **profile,
        )
        user.set_unusable_password()
        try:
            with transaction.atomic():
                user.save()
        except IntegrityError:
            # Another update from the same person created it first.
            return User.objects.get(telegram_id=telegram_id)
        return user

    changed = [field for field, value in profile.items() if getattr(user, field) != value]
    if changed:
        for field in changed:
            setattr(user, field, profile[field])
        user.save(update_fields=changed)
    return user


def save_verified_phone(user: User, *, contact_user_id: int | None, phone_number: str) -> bool:
    """Store the phone from a shared Telegram contact, but only if it's the person's own."""
    if contact_user_id is None or contact_user_id != user.telegram_id:
        return False
    user.phone = "+" + "".join(char for char in phone_number if char.isdigit())
    user.save(update_fields=["phone"])
    return True


def _language(language_code: str | None) -> str:
    code = (language_code or "")[:2].lower()
    return code if code in Language.values else Language.UZ
