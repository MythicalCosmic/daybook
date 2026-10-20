"""Inbox endpoints: the owner drawer, preferences, and the mini app's inbox."""

from datetime import date

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.console import registry
from apps.console.ranges import Range
from apps.inbox.models import Notification, NotificationPreference
from apps.inbox.services import NotificationAction, notify

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("handlers")]

APPROVE = NotificationAction("approve", _("Approve"), "primary")
REJECT = NotificationAction("reject", _("Reject"), "danger", needs_reason=True)


def inbox_url(company, path="") -> str:
    return f"/api/v1/owner/companies/{company.pk}/inbox/{path}"


@pytest.fixture
def owner(company, member):
    return member(company, "Owner")


@pytest.fixture
def claims(owner, member, company):
    target = member(company)
    first, second = (
        notify(
            [owner], "inbox.claim", title=f"Claim {n}", target=target, actions=[APPROVE, REJECT]
        )[0]
        for n in (1, 2)
    )
    return first, second


def test_the_drawer_lists_my_in_app_notifications_newest_first(
    company, member, owner, claims, owner_api
):
    notify([owner], "inbox.request", title="Needs you only")  # Telegram-only kind
    notify([member(company, "Owner")], "inbox.claim", title="Someone else's")

    response = owner_api(owner).get(inbox_url(company))

    assert response.status_code == 200
    assert [row["title"] for row in response.data["results"]] == ["Claim 2", "Claim 1"]
    row = response.data["results"][0]
    assert row["actions"] == [
        {"key": "approve", "label": "Approve", "style": "primary", "needs_reason": False},
        {"key": "reject", "label": "Reject", "style": "danger", "needs_reason": True},
    ]
    assert row["read_at"] is None and row["acted_by"] is None


def test_the_unread_tab_and_count(company, owner, claims, owner_api):
    first, _second = claims
    Notification.objects.filter(pk=first.pk).update(read_at=timezone.now())
    client = owner_api(owner)

    unread = client.get(inbox_url(company), {"tab": "unread"}).data["results"]
    assert [row["id"] for row in unread] == [claims[1].pk]
    assert client.get(inbox_url(company, "unread-count/")).data == {"count": 1, "critical": 0}
    assert client.get(inbox_url(company), {"tab": "later"}).status_code == 400


def test_the_unread_count_says_how_many_are_critical(company, owner, claims, owner_api):
    notify([owner], "inbox.claim", title="Cash short", severity="critical")
    read = notify([owner], "inbox.claim", title="Seen already", severity="critical")[0]
    Notification.objects.filter(pk=read.pk).update(read_at=timezone.now())

    data = owner_api(owner).get(inbox_url(company, "unread-count/")).data

    assert data == {"count": 3, "critical": 1}


def test_the_drawer_takes_a_fixed_number_of_queries(
    company, member, owner, owner_api, django_assert_max_num_queries
):
    client = owner_api(owner)
    nameless = member(company, "Manager")
    nameless.first_name = nameless.last_name = ""
    nameless.save()
    notify([owner], "inbox.claim", title="First", actor=nameless)
    client.get(inbox_url(company))
    for n in range(4):
        notify([owner], "inbox.claim", title=f"Claim {n}", actor=member(company))

    with django_assert_max_num_queries(6):
        response = client.get(inbox_url(company))

    assert len(response.data["results"]) == 5
    assert response.data["results"][-1]["actor"]["name"] == str(nameless.user)


def test_mark_some_or_all_read(company, owner, claims, owner_api):
    client = owner_api(owner)

    assert client.post(
        inbox_url(company, "read/"), {"ids": [claims[0].pk]}, format="json"
    ).data == {"updated": 1}
    assert client.post(inbox_url(company, "read/"), {"all": True}, format="json").data == {
        "updated": 1
    }
    assert client.post(inbox_url(company, "read/"), {}, format="json").status_code == 400


def test_marking_someone_elses_notification_does_nothing(company, member, claims, owner_api):
    stranger = member(company, "Owner")

    response = owner_api(stranger).post(
        inbox_url(company, "read/"), {"ids": [claims[0].pk]}, format="json"
    )

    assert response.data == {"updated": 0}


def test_archive_hides_it(company, owner, claims, owner_api):
    client = owner_api(owner)

    response = client.post(inbox_url(company, f"{claims[0].pk}/archive/"))

    assert response.status_code == 200
    assert [row["id"] for row in client.get(inbox_url(company)).data["results"]] == [claims[1].pk]


def test_archive_of_another_persons_notification_is_404(company, member, claims, owner_api):
    stranger = member(company, "Owner")

    assert (
        owner_api(stranger).post(inbox_url(company, f"{claims[0].pk}/archive/")).status_code == 404
    )


def test_pressing_a_button_runs_the_modules_handler(company, owner, claims, handlers, owner_api):
    response = owner_api(owner).post(inbox_url(company, f"{claims[0].pk}/actions/approve/"))

    assert response.status_code == 200
    assert response.data["message"] == "Claim approved"
    assert response.data["notification"]["actions"] == []
    assert response.data["notification"]["acted_by"] == str(owner.user)
    assert handlers.calls == [("approve", claims[0].pk, owner.pk, "")]


def test_a_reason_reaches_the_handler(company, owner, claims, handlers, owner_api):
    client = owner_api(owner)
    url = inbox_url(company, f"{claims[0].pk}/actions/reject/")

    assert client.post(url, {}, format="json").status_code == 400
    response = client.post(url, {"reason": "No receipt"}, format="json")

    assert response.status_code == 200
    assert response.data["message"] == "Done."
    assert handlers.calls == [("reject", claims[0].pk, owner.pk, "No receipt")]


def test_a_handled_notification_answers_400(company, owner, claims, owner_api):
    client = owner_api(owner)
    client.post(inbox_url(company, f"{claims[0].pk}/actions/approve/"))

    response = client.post(inbox_url(company, f"{claims[0].pk}/actions/approve/"))

    assert response.status_code == 400


def test_a_handler_refusing_on_permission_answers_403(
    company, owner, claims, owner_api, monkeypatch
):
    def no(notification, by, reason):
        raise PermissionDenied("Only accountants pay claims.")

    monkeypatch.setattr("apps.inbox.registry.get_handler", lambda kind, key: no)

    response = owner_api(owner).post(inbox_url(company, f"{claims[0].pk}/actions/approve/"))

    assert response.status_code == 403
    assert response.data["detail"] == "Only accountants pay claims."


def test_someone_elses_notification_is_404(company, member, claims, owner_api):
    stranger = member(company, "Owner")

    response = owner_api(stranger).post(inbox_url(company, f"{claims[0].pk}/actions/approve/"))

    assert response.status_code == 404


@pytest.mark.parametrize("path", ["", "unread-count/"])
def test_the_inbox_is_company_scoped(company, other_company, member, owner_api, path):
    assert (
        owner_api(member(other_company, "Owner")).get(inbox_url(company, path)).status_code == 404
    )
    assert owner_api(member(company)).get(inbox_url(company, path)).status_code == 403


def test_preferences_list_every_kind_with_defaults(company, owner, owner_api):
    response = owner_api(owner).get(
        f"/api/v1/owner/companies/{company.pk}/notification-preferences/"
    )

    rows = {row["kind"]: row for row in response.data}
    assert rows["inbox.claim"] == {
        "kind": "inbox.claim",
        "label": "Expense claim",
        "audience": "owner",
        "severity": "info",
        "in_app_available": True,
        "in_app": True,
        "telegram": True,
    }
    assert rows["inbox.request"]["in_app_available"] is False
    assert rows["inbox.digest"]["telegram"] is False


def test_preferences_are_saved(company, owner, owner_api):
    url = f"/api/v1/owner/companies/{company.pk}/notification-preferences/"

    response = owner_api(owner).put(
        url, [{"kind": "inbox.claim", "in_app": True, "telegram": False}], format="json"
    )

    assert response.status_code == 200
    assert (
        NotificationPreference.objects.get(membership=owner, kind="inbox.claim").telegram is False
    )
    assert {row["kind"]: row for row in response.data}["inbox.claim"]["telegram"] is False
    bad = owner_api(owner).put(
        url, [{"kind": "inbox.nope", "in_app": True, "telegram": True}], format="json"
    )
    assert bad.status_code == 400


def test_the_mini_app_inbox_shows_my_notifications_in_this_company(
    company, other_company, member, api_as
):
    worker = member(company)
    notify([worker], "inbox.digest", title="Your week")
    elsewhere = member(other_company, user=worker.user)
    notify([elsewhere], "inbox.digest", title="Other job")

    response = api_as(worker).get(f"/api/v1/companies/{company.pk}/inbox/")

    assert response.status_code == 200
    assert [row["title"] for row in response.data["results"]] == ["Your week"]


def test_the_mini_app_marks_read(company, member, api_as):
    worker = member(company)
    [item] = notify([worker], "inbox.digest", title="Your week")

    response = api_as(worker).post(
        f"/api/v1/companies/{company.pk}/inbox/read/", {"all": True}, format="json"
    )

    assert response.data == {"updated": 1}
    item.refresh_from_db()
    assert item.read_at is not None


def test_the_mini_app_inbox_is_for_members_only(company, other_company, member, api_as):
    outsider = member(other_company)

    assert api_as(outsider).get(f"/api/v1/companies/{company.pk}/inbox/").status_code == 404


def test_the_unread_badge_and_the_waiting_fact(company, owner, claims):
    assert registry.pulse_counts(owner)["inbox.unread"] == 2
    span = Range(date(2026, 10, 1), date(2026, 10, 20))
    assert registry.collect_company_facts(owner, span)["inbox"] == {"waiting": 0}
