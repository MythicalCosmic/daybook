"""`run_action`: the one path for bot and dashboard buttons."""

import pytest
from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext_lazy as _

from apps.core.exceptions import DomainError
from apps.inbox import delivery, services
from apps.inbox.models import Notification
from apps.inbox.services import NotificationAction, notify, run_action

pytestmark = pytest.mark.django_db

APPROVE = NotificationAction("approve", _("Approve"), "primary")
REJECT = NotificationAction("reject", _("Reject"), "danger", needs_reason=True)
PAY = NotificationAction("pay", _("Pay"))


@pytest.fixture
def approvers(company, member):
    return [member(company, "Owner"), member(company, "Owner", user__language="ru")]


@pytest.fixture
def claim(company, member):
    return member(company)  # stands in for the record the notification is about


def sent(approvers, claim, telegram):
    items = notify(
        approvers, "inbox.claim", title="Claim", target=claim, actions=[APPROVE, REJECT, PAY]
    )
    for item in items:
        delivery.deliver(item.pk)
    return items


def test_the_registered_handler_runs_and_every_copy_is_settled(
    approvers, claim, handlers, telegram, django_capture_on_commit_callbacks
):
    mine, colleagues = sent(approvers, claim, telegram)

    with django_capture_on_commit_callbacks(execute=True):
        message = run_action(mine.pk, "approve", by=approvers[0])

    assert message == "Claim approved"
    assert handlers.calls == [("approve", mine.pk, approvers[0].pk, "")]
    mine.refresh_from_db()
    colleagues.refresh_from_db()
    assert mine.acted_by == approvers[0].user and mine.read_at is not None
    assert colleagues.acted_at is not None  # nobody else can approve it twice
    edits = {edit["message_id"]: edit for edit in telegram.edited}
    assert edits[mine.telegram_message_id]["text"].endswith(f"✅ Claim approved · {approvers[0]}")
    # Each copy is settled in its reader's language; the colleague reads Russian.
    assert edits[colleagues.telegram_message_id]["text"].endswith(f"✅ Одобрить · {approvers[0]}")
    assert all(edit["markup"] is None for edit in telegram.edited)  # the buttons are gone


def test_a_business_rule_in_the_handler_changes_nothing(approvers, claim, handlers, telegram):
    mine, _colleagues = sent(approvers, claim, telegram)

    with pytest.raises(DomainError, match="already paid"):
        run_action(mine.pk, "pay", by=approvers[0])

    mine.refresh_from_db()
    assert mine.acted_at is None


def test_only_the_recipient_may_act(company, member, approvers, claim, handlers, telegram):
    mine, _colleagues = sent(approvers, claim, telegram)

    with pytest.raises(PermissionDenied):
        run_action(mine.pk, "approve", by=approvers[1])
    with pytest.raises(PermissionDenied):
        run_action(mine.pk, "approve", by=member(company, "Owner"))


def test_a_recipient_who_lost_approval_may_not_act(approvers, claim, handlers, telegram):
    mine, _colleagues = sent(approvers, claim, telegram)
    approvers[0].status = approvers[0].Status.BLOCKED
    approvers[0].save()

    with pytest.raises(PermissionDenied):
        run_action(mine.pk, "approve", by=approvers[0])


def test_acting_twice_is_refused(approvers, claim, handlers, telegram):
    mine, colleagues = sent(approvers, claim, telegram)
    run_action(mine.pk, "approve", by=approvers[0])

    with pytest.raises(DomainError, match="already been handled"):
        run_action(colleagues.pk, "approve", by=approvers[1])


def test_unknown_actions_are_refused(approvers, claim, handlers, telegram):
    mine, _colleagues = sent(approvers, claim, telegram)

    with pytest.raises(DomainError):
        run_action(mine.pk, "delete", by=approvers[0])


def test_an_action_that_needs_a_reason_gets_one(approvers, claim, handlers, telegram):
    mine, _colleagues = sent(approvers, claim, telegram)

    with pytest.raises(DomainError, match="reason"):
        run_action(mine.pk, "reject", by=approvers[0], reason="  ")

    assert run_action(mine.pk, "reject", by=approvers[0], reason="No receipt") is None
    assert handlers.calls[-1] == ("reject", mine.pk, approvers[0].pk, "No receipt")


def test_a_notification_without_a_target_settles_alone(approvers, handlers, telegram):
    mine, colleagues = notify(approvers, "inbox.claim", title="Claim", actions=[APPROVE])

    run_action(mine.pk, "approve", by=approvers[0])

    colleagues.refresh_from_db()
    assert colleagues.acted_at is None


def test_a_missing_notification(approvers, handlers):
    with pytest.raises(Notification.DoesNotExist):
        run_action(999_999, "approve", by=approvers[0])


def test_from_the_bot_the_answer_is_a_short_message(approvers, claim, handlers, telegram):
    mine, colleagues = sent(approvers, claim, telegram)

    done = services.act_from_bot(mine.pk, "approve", user=approvers[0].user)
    again = services.act_from_bot(colleagues.pk, "approve", user=approvers[1].user)
    stranger = services.act_from_bot(mine.pk, "approve", user=approvers[1].user)

    assert done == services.BotActionResult(True, "Claim approved")
    assert again.ok is False and "already" in again.message
    assert stranger == services.BotActionResult(False, "You don't have access to this.")


def test_from_the_bot_a_handler_without_a_message_says_done(approvers, handlers, telegram):
    [mine, _other] = notify(
        approvers, "inbox.claim", title="Claim", actions=[NotificationAction("reject", "Reject")]
    )

    assert services.act_from_bot(mine.pk, "reject", user=approvers[0].user) == (
        services.BotActionResult(True, "Done.")
    )


def test_from_the_bot_a_reason_is_asked_for_in_the_dashboard(approvers, claim, handlers, telegram):
    mine, _colleagues = sent(approvers, claim, telegram)

    result = services.act_from_bot(mine.pk, "reject", user=approvers[0].user)

    assert result.ok is False and "reason" in result.message


# settle: decided somewhere else ---------------------------------------------------------


def test_settle_closes_every_open_copy_and_edits_telegram(
    company, member, approvers, claim, handlers, telegram, django_capture_on_commit_callbacks
):
    first, second = sent(approvers, claim, telegram)
    other_claim = member(company)
    [untouched] = notify(approvers[:1], "inbox.claim", title="Other", target=other_claim)
    decider = member(company, "Manager")

    with django_capture_on_commit_callbacks(execute=True):
        closed = services.settle(claim, outcome=_("Approve"), by=decider)

    assert closed == 2
    for item in (first, second):
        item.refresh_from_db()
        assert item.acted_at is not None and item.acted_by == decider.user
    untouched.refresh_from_db()
    assert untouched.acted_at is None
    edits = {edit["message_id"]: edit for edit in telegram.edited}
    assert edits[first.telegram_message_id]["text"].endswith(f"✅ Approve · {decider}")
    assert edits[second.telegram_message_id]["markup"] is None  # the buttons are gone
    assert services.settle(claim, outcome="Approved", by=decider) == 0  # nothing left open
    with pytest.raises(DomainError, match="already been handled"):
        run_action(first.pk, "approve", by=approvers[0])
    assert handlers.calls == []


def test_settle_by_the_system_names_nobody_and_renders_per_recipient(
    approvers, claim, handlers, telegram, django_capture_on_commit_callbacks
):
    first, second = sent(approvers, claim, telegram)

    with django_capture_on_commit_callbacks(execute=True):
        services.settle(claim, outcome=lambda person: f"Expired for {person.pk}")

    first.refresh_from_db()
    second.refresh_from_db()
    edits = {edit["message_id"]: edit["text"] for edit in telegram.edited}
    assert edits[first.telegram_message_id].endswith(f"✅ Expired for {approvers[0].pk}")
    assert edits[second.telegram_message_id].endswith(f"✅ Expired for {approvers[1].pk}")
    # nobody decided: no actor
    assert first.acted_by is None


def test_settle_can_be_narrowed_to_one_kind(approvers, claim, handlers, telegram):
    [claim_note] = notify(approvers[:1], "inbox.claim", title="Claim", target=claim)
    [digest] = notify(approvers[:1], "inbox.digest", title="Digest", target=claim)

    assert services.settle(claim, outcome="Done", kind="inbox.claim") == 1

    claim_note.refresh_from_db()
    digest.refresh_from_db()
    assert claim_note.acted_at is not None and digest.acted_at is None


def test_a_settled_notification_is_never_sent_to_telegram(approvers, claim, handlers, telegram):
    [item] = notify(approvers[:1], "inbox.claim", title="Claim", target=claim)
    services.settle(claim, outcome="Done")

    delivery.deliver(item.pk)

    assert telegram.sent == []
