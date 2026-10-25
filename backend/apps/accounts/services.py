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
    """Return the User for a Telegram account, creating it or refreshing its profile.

    A new account speaks Uzbek, whatever language Telegram is in (the owner's "Uzbek first"):
    the person picks another one in the bot or the mini app. A user made just now carries
    `just_created = True` (not stored), for the bot's first greeting."""
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
            language=Language.UZ,
            **profile,
        )
        user.set_unusable_password()
        try:
            with transaction.atomic():
                user.save()
        except IntegrityError:
            # Another update from the same person created it first.
            return User.objects.get(telegram_id=telegram_id)
        user.just_created = True
        return user

    changed = [field for field, value in profile.items() if getattr(user, field) != value]
    if changed:
        for field in changed:
            setattr(user, field, profile[field])
        user.save(update_fields=changed)
    return user


def set_language(user: User, code: str) -> bool:
    """The person's own choice of language (uz, ru or en), which then beats Telegram's
    interface language for good. True when it changed."""
    if code not in Language.values:
        raise ValueError(f"Unknown language {code!r}.")
    if user.language == code:
        return False
    user.language = code
    User.objects.filter(pk=user.pk).update(language=code)
    return True


def approved_memberships(user: User) -> list:
    """The person's approved memberships in active companies, by company name."""
    from apps.members.models import Membership

    return list(
        Membership.objects.filter(
            user=user, status=Membership.Status.APPROVED, company__is_active=True
        )
        .select_related("company", "user", "role", "position")
        .order_by("company__name", "pk")
    )


def bot_membership(user: User):
    """The membership the employee bot works in for this person when nothing else says which
    (lists, new tasks, the menu): for someone in several companies the one they picked last
    (`User.bot_company`), else the one with the most open work for them; otherwise the latest
    approved one, else the latest of any status (so newcomers get their status)."""
    from apps.members.models import Membership

    memberships = list(
        Membership.objects.filter(user=user, company__is_active=True)
        .select_related("company", "user", "role", "position")
        .order_by("-updated_at")
    )
    approved = [m for m in memberships if m.status == Membership.Status.APPROVED]
    if len(approved) > 1:
        chosen = next((m for m in approved if m.company_id == user.bot_company_id), None)
        return chosen or first_choice(approved)
    return (approved or memberships or [None])[0]


def membership_in(user: User, company_id: int):
    """The person's approved membership in `company_id` (the company of a task they tapped),
    or None."""
    from apps.members.models import Membership

    return (
        Membership.objects.filter(
            user=user,
            company_id=company_id,
            status=Membership.Status.APPROVED,
            company__is_active=True,
        )
        .select_related("company", "user", "role", "position")
        .first()
    )


def remember_company(user: User, company_id: int) -> None:
    """The company the person last worked in through the bot: it stays theirs until they pick
    or act in another one."""
    if user.bot_company_id != company_id:
        user.bot_company_id = company_id
        User.objects.filter(pk=user.pk).update(bot_company_id=company_id)


def first_choice(memberships: list):
    """Of several approved memberships, the company someone sees first, the same in the bot,
    the mini app and the dashboard: one they own, the one with the most branches, then the one
    with the most open work for them (their open tasks and the work waiting for their check);
    the latest updated wins a tie."""
    from django.db.models import Count

    from apps.companies.models import Branch
    from apps.tasks import queries
    from apps.tasks.models import Task

    branches = dict(
        Branch.objects.filter(company_id__in=[m.company_id for m in memberships])
        .values("company_id")
        .annotate(count=Count("pk"))
        .values_list("company_id", "count")
    )

    def rank(member) -> tuple:
        owns = member.role is not None and member.role.is_owner
        mine = Task.objects.filter(assignee=member, status__in=Task.OPEN_STATUSES).count()
        work = mine + queries.awaiting_review_by(member).count()
        return owns, branches.get(member.company_id, 0), work

    return max(memberships, key=rank)


def save_verified_phone(user: User, *, contact_user_id: int | None, phone_number: str) -> bool:
    """Store the phone from a shared Telegram contact, but only if it's the person's own."""
    if contact_user_id is None or contact_user_id != user.telegram_id:
        return False
    user.phone = "+" + "".join(char for char in phone_number if char.isdigit())
    user.save(update_fields=["phone"])
    return True


