"""Kudos (PLAN-LEARNING §7.5): limits, never oneself, same company and approved, the receiver's
points and bot message with "Say thanks back", hiding, group posts."""

from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied

from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.inbox.models import Notification
from apps.recognition import conf, queries, services
from apps.recognition.models import Kudos, PointsEntry
from apps.recognition.tests.conftest import DAY, at

pytestmark = pytest.mark.django_db


def thank(giver, receiver, **kwargs):
    return services.send_kudos(giver, to=receiver, **kwargs)


def test_kudos_gives_points_and_the_bot_message(
    shop, madina, ali, sent_messages, settings, django_capture_on_commit_callbacks
):
    settings.EMPLOYEE_MINIAPP_URL = "https://app.example.uz/app/"
    with django_capture_on_commit_callbacks(execute=True):
        kudos = thank(madina, ali, badge="careful", message="Sovutgichni tekshirding, rahmat")
    entry = PointsEntry.objects.get(key=f"kudos:{kudos.pk}")
    assert (entry.membership, entry.points, entry.reason, entry.by) == (ali, 5, "kudos", madina)
    notice = Notification.objects.get(recipient=ali, kind="recognition.kudos")
    assert notice.title == "Madina thanked you: careful work."
    assert notice.app_screen == "kudos" and notice.in_app
    assert len(sent_messages) == 1  # the bot's own message, no second copy from the inbox
    message = sent_messages[0]
    assert message["chat_id"] == ali.user.telegram_id
    assert message["text"].startswith("<b>Madina thanked you: careful work.</b>")
    assert "«Sovutgichni tekshirding, rahmat»" in message["text"] and "+5 points" in message["text"]
    button = message["reply_markup"]["inline_keyboard"][0][0]
    assert button["text"] == "Say thanks back"
    assert button["web_app"]["url"].endswith(f"screen=thank%3A{madina.pk}")


def test_plain_thanks_reads_plainly(
    shop, madina, ali, sent_messages, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        thank(madina, ali)
    assert sent_messages[0]["text"].startswith("<b>Madina thanked you.</b>")
    assert sent_messages[0]["reply_markup"] is None  # no https mini app here: no button


def test_never_oneself_and_only_approved_colleagues_of_the_company(
    shop, madina, ali, member, other_company
):
    with pytest.raises(DomainError, match="yourself"):
        thank(madina, madina)
    stranger = member(other_company, "Employee")
    with pytest.raises(DomainError, match="this company"):
        thank(madina, stranger)
    left = member(shop, "Employee", status="left")
    with pytest.raises(DomainError, match="isn't working here"):
        thank(madina, left)
    with pytest.raises(PermissionDenied):
        thank(left, madina)
    with pytest.raises(DomainError):
        thank(madina, ali, badge="gold")
    with pytest.raises(DomainError):
        thank(madina, ali, message="x" * 201)
    assert not Kudos.objects.exists()


def test_a_day_s_limit(shop, madina, ali, nigora, head, freeze):
    thank(madina, ali)
    thank(madina, nigora)
    thank(madina, head)
    assert services.kudos_left(madina) == 0
    with pytest.raises(DomainError, match="3 colleagues a day"):
        thank(madina, ali, badge="star")
    freeze(at(DAY + timedelta(days=1), 9))
    assert services.kudos_left(madina) == 3
    thank(madina, ali, badge="star")


def test_switches(shop, madina, ali):
    settings = conf.get_settings(shop)
    settings.kudos_enabled = False
    settings.save()
    with pytest.raises(DomainError, match="aren't switched on"):
        thank(madina, ali)
    shop.features = ["learning"]
    shop.save(update_fields=["features"])
    with pytest.raises(DomainError, match="Recognition isn't switched on"):
        thank(madina, ali)


def test_hiding_takes_it_and_its_points_away_everywhere(shop, owner, head, madina, ali):
    kudos = thank(madina, ali, badge="teamwork", message="Rude words")
    with pytest.raises(PermissionDenied):
        services.hide_kudos(kudos, by=head)
    services.hide_kudos(kudos, by=owner)
    kudos.refresh_from_db()
    assert kudos.hidden_at is not None and kudos.hidden_by == owner.user
    assert not PointsEntry.objects.filter(key=f"kudos:{kudos.pk}").exists()
    assert queries.kudos_box(ali, "received") == []
    assert queries.kudos_box(madina, "given") == []
    assert queries.kudos_feed(shop, branch_ids=None) == []
    assert queries.kudos_today(ali) == []
    log = AuditLog.objects.get(action="recognition.kudos_hidden")
    assert log.details["message"] == "Rude words" and log.details["points_removed"] is True


def test_group_post_only_when_the_company_wants_it(
    shop, madina, ali, monkeypatch, django_capture_on_commit_callbacks
):
    posts = []
    monkeypatch.setattr(
        "apps.groups.services.broadcast",
        lambda company_id, event, text, **kwargs: posts.append((event, text, kwargs)) or 1,
    )
    with django_capture_on_commit_callbacks(execute=True):
        thank(madina, ali, badge="careful")
    assert posts == []
    settings = conf.get_settings(shop)
    settings.post_kudos_to_groups = True
    settings.save()
    with django_capture_on_commit_callbacks(execute=True):
        thank(madina, ali, badge="careful", message="Rahmat")
    event, text, kwargs = posts[0]
    assert event == "kudos" and kwargs == {"branch_id": ali.home_branch_id}
    assert "To: Alisher Valiyev" in text and "From: Madina Saidova" in text
    assert "Careful work" in text and "«Rahmat»" in text


def test_feeds_newest_first_and_in_scope(shop, madina, ali, nigora, yunusobod, chilonzor):
    first = thank(madina, ali)
    second = thank(nigora, madina, badge="fast")
    assert [k.pk for k in queries.kudos_box(madina, "received")] == [second.pk]
    assert [k.pk for k in queries.kudos_box(madina, "given")] == [first.pk]
    assert [k.pk for k in queries.kudos_feed(shop, branch_ids=None)] == [second.pk, first.pk]
    assert [k.pk for k in queries.kudos_feed(shop, branch_ids=[yunusobod.pk])] == [second.pk]
    assert {k.pk for k in queries.kudos_feed(shop, branch_ids=[chilonzor.pk])} == {
        first.pk,
        second.pk,
    }
