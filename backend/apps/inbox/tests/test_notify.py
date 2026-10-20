"""`notify()`: one row per recipient, in their language, Telegram per kind and preference."""

import pytest
from django.core.cache import cache
from django.utils.translation import gettext_lazy as _

from apps.console import pulse
from apps.inbox.models import Notification, NotificationPreference
from apps.inbox.services import NotificationAction, notify
from apps.members.models import Membership

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("handlers")]

APPROVE = NotificationAction("approve", _("Approve"), "primary")


@pytest.fixture
def owners(company, member):
    return [member(company, "Owner"), member(company, "Owner", user__language="ru")]


def test_one_row_per_approved_recipient(company, member, owners, telegram):
    pending = member(company, "Owner", status=Membership.Status.PENDING)

    created = notify([*owners, pending, owners[0]], "inbox.claim", title="Claim from Ali")

    assert len(created) == 2
    assert {n.recipient_id for n in created} == {o.pk for o in owners}
    assert all(n.company_id == company.pk and n.in_app for n in created)
    assert all(n.severity == "info" for n in created)


def test_texts_and_labels_are_in_each_recipients_language(owners, telegram):
    def title(person):
        return f"{person.user.language}: claim"

    notify(owners, "inbox.claim", title=title, body=_("Approve"), actions=[APPROVE])

    by_language = {
        n.recipient.user.language: n for n in Notification.objects.select_related("recipient__user")
    }
    assert by_language["en"].title == "en: claim"
    assert by_language["ru"].title == "ru: claim"
    assert by_language["en"].actions == [
        {"key": "approve", "label": "Approve", "style": "primary", "needs_reason": False}
    ]


def test_target_actor_and_data_are_kept(company, member, owners, telegram):
    actor = member(company)

    [first, *_rest] = notify(
        owners,
        "inbox.claim",
        title="Claim",
        url="/c/1/finance/claims/7",
        app_screen="claim:7",
        target=actor,
        actor=actor,
        data={"amount": "450000.00"},
        severity="critical",
    )

    assert (first.target_type, first.target_id, first.actor) == ("membership", actor.pk, actor)
    assert first.data == {"amount": "450000.00"}
    assert first.severity == "critical"


def test_a_dedupe_key_sends_once_per_recipient(owners, telegram):
    notify(owners, "inbox.claim", title="Late", dedupe_key="late:7")
    again = notify(owners, "inbox.claim", title="Late", dedupe_key="late:7")

    assert again == []
    assert Notification.objects.count() == 2


def test_kinds_that_live_in_needs_you_get_a_telegram_copy_only(
    owners, telegram, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        created = notify(owners, "inbox.request", title="Ali: 3 days off", actions=[APPROVE])

    assert all(not n.in_app for n in created)
    assert all(n.severity == "warning" for n in created)
    assert len(telegram.sent) == 2


def test_preferences_decide_in_app_and_telegram(
    owners, telegram, django_capture_on_commit_callbacks
):
    quiet, muted = owners
    NotificationPreference.objects.create(
        membership=quiet, kind="inbox.claim", in_app=True, telegram=False
    )
    NotificationPreference.objects.create(
        membership=muted, kind="inbox.claim", in_app=False, telegram=False
    )

    with django_capture_on_commit_callbacks(execute=True):
        created = notify(owners, "inbox.claim", title="Claim")

    assert [n.recipient for n in created] == [quiet]
    assert telegram.sent == []


def test_default_telegram_off_sends_nothing(
    company, member, telegram, django_capture_on_commit_callbacks
):
    worker = member(company)

    with django_capture_on_commit_callbacks(execute=True):
        notify([worker], "inbox.digest", title="Your week")

    assert Notification.objects.filter(recipient=worker, in_app=True).exists()
    assert telegram.sent == []


def test_telegram_copies_and_the_badge_go_out_after_commit(
    company, owners, telegram, django_capture_on_commit_callbacks
):
    cache.clear()
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        notify(owners, "inbox.claim", title="Claim")
        assert telegram.sent == []

    for callback in callbacks:
        callback()
    assert len(telegram.sent) == 2
    assert pulse.versions(company.pk, ["inbox.unread"]) == {"inbox.unread": "1"}


def test_an_action_without_a_handler_is_refused(owners):
    with pytest.raises(LookupError, match="No handler"):
        notify(
            owners, "inbox.claim", title="Claim", actions=[NotificationAction("delete", "Delete")]
        )


def test_an_unregistered_kind_is_refused(owners):
    with pytest.raises(LookupError):
        notify(owners, "inbox.unknown", title="?")


def test_action_specs_are_checked():
    with pytest.raises(ValueError):
        NotificationAction("Approve!", "Approve")
    with pytest.raises(ValueError):
        NotificationAction("approve", "Approve", style="huge")


def test_nobody_to_tell_creates_nothing(telegram):
    assert notify([], "inbox.claim", title="Claim") == []
