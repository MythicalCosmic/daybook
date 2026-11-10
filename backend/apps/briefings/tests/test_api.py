"""The owner endpoints of briefings (rule 21): company scope (another company's id is a 404),
permissions (403), the reader's own scope (a manager never reads the owner's finance review),
settings audited, the 3-a-day rewrite, "Ask the advisor" conversations."""

from datetime import timedelta

import pytest

from apps.audit.models import AuditLog
from apps.briefings import reviews, scope
from apps.briefings.audit_actions import BriefingAction
from apps.briefings.models import Briefing, BriefingDelivery, BriefingSettings
from apps.companies.tests.factories import CompanyFactory

from .conftest import NOW

pytestmark = pytest.mark.django_db


def url(company, path=""):
    return f"/api/v1/owner/companies/{company.pk}/briefings/{path}"


@pytest.fixture
def sent(ledger, till_days, people, pharmacy):
    """This Monday's reviews, to the owner and (recipients: reports) the manager."""
    row = BriefingSettings.objects.get_or_create(company=pharmacy)[0]
    row.recipients = BriefingSettings.Recipients.REPORTS
    row.save()
    reviews.tick()
    return {
        "owner": Briefing.objects.get(scope_key=scope.of(people.owner).key),
        "manager": Briefing.objects.get(scope_key=scope.of(people.manager).key),
    }


def test_the_owner_reads_the_latest_review(sent, people, pharmacy, owner_api):
    client = owner_api(people.owner)

    body = client.get(url(pharmacy, "latest/")).json()

    review = body["review"]
    assert review["id"] == sent["owner"].pk
    assert review["kind"] == "weekly" and review["period"]["start"] == "2026-11-09"
    assert review["headline"] == sent["owner"].content["headline"]
    assert [section["key"] for section in review["sections"]] == ["went_well", "went_wrong"]
    assert review["actions"] and review["facts"]["finance"]["revenue"]["value"] == "20000000.00"
    assert body["writer"] == "template" and body["advisor_on"] is False and body["chat"] is False
    assert body["can_regenerate"] is True and body["regenerations_left"] == 3
    assert body["next"]["weekly"].startswith("2026-11-23T08:00")
    delivery = BriefingDelivery.objects.get(briefing=sent["owner"])
    assert delivery.opened_at is not None


def test_the_history_and_one_review(sent, people, pharmacy, owner_api):
    client = owner_api(people.owner)

    listed = client.get(url(pharmacy)).json()["results"]
    one = client.get(url(pharmacy, f"{sent['owner'].pk}/"))

    assert [row["id"] for row in listed] == [sent["owner"].pk]
    assert one.status_code == 200 and one.json()["facts"]["kind"] == "weekly"


def test_a_manager_never_reads_the_owners_review(sent, people, pharmacy, owner_api):
    client = owner_api(people.manager)

    latest = client.get(url(pharmacy, "latest/")).json()["review"]
    listed = client.get(url(pharmacy)).json()["results"]

    assert latest["id"] == sent["manager"].pk
    assert "finance" not in latest["facts"]
    assert [row["id"] for row in listed] == [sent["manager"].pk]
    assert client.get(url(pharmacy, f"{sent['owner'].pk}/")).status_code == 404


def test_without_reports_there_is_no_review(sent, people, pharmacy, owner_api):
    client = owner_api(people.clerk)

    assert client.get(url(pharmacy, "latest/")).status_code == 403
    assert client.get(url(pharmacy)).status_code == 403
    assert client.get(url(pharmacy, f"{sent['owner'].pk}/")).status_code == 403


def test_another_companys_review_is_a_404(sent, people, member, owner_api):
    other = CompanyFactory()
    stranger = member(other, "Owner")
    client = owner_api(stranger)

    assert client.get(url(other, f"{sent['owner'].pk}/")).status_code == 404
    assert client.get(url(sent["owner"].company, "latest/")).status_code == 404


def test_settings_change_audited_and_only_with_company_settings(
    pharmacy, people, owner_api, ledger
):
    client = owner_api(people.owner)

    changed = client.patch(
        url(pharmacy, "settings/"), {"weekday": 4, "send_at": "18:30"}, format="json"
    )

    assert changed.status_code == 200
    assert changed.json() | {} == {
        "weekly_enabled": True,
        "monthly_enabled": True,
        "weekday": 4,
        "send_at": "18:30",
        "recipients": "owners",
    }
    log = AuditLog.objects.get(action=BriefingAction.SETTINGS_CHANGED)
    assert log.details["changes"]["weekday"] == [0, 4]
    assert (
        owner_api(people.manager)
        .patch(url(pharmacy, "settings/"), {"weekday": 1}, format="json")
        .status_code
        == 403
    )
    assert (
        client.patch(url(pharmacy, "settings/"), {"weekday": 9}, format="json").status_code == 400
    )


def test_the_review_written_again_three_times_a_day(ledger, people, pharmacy, owner_api):
    client = owner_api(people.owner)

    for _attempt in range(3):
        answer = client.post(url(pharmacy, "regenerate/"), {"kind": "weekly"}, format="json")
        assert answer.status_code == 200
        assert answer.json()["period"]["start"] == "2026-11-09"
    fourth = client.post(url(pharmacy, "regenerate/"), {}, format="json")

    assert fourth.status_code == 400
    assert Briefing.objects.count() == 1
    assert AuditLog.objects.filter(action=BriefingAction.REGENERATED).count() == 3
    assert owner_api(people.manager).post(url(pharmacy, "regenerate/"), {}).status_code == 403


def test_with_claude_the_rewrite_goes_to_the_ai_queue(
    ledger, people, pharmacy, owner_api, ai_on, fake_claude, django_capture_on_commit_callbacks
):
    ai_on()
    client = owner_api(people.owner)

    with django_capture_on_commit_callbacks() as callbacks:
        answer = client.post(url(pharmacy, "regenerate/"), {}, format="json")

    assert answer.status_code == 202 and answer.json() == {"queued": True}
    assert len(callbacks) == 1


def test_nothing_to_rewrite_in_a_new_company(pharmacy, people, owner_api):
    answer = owner_api(people.owner).post(url(pharmacy, "regenerate/"), {}, format="json")

    assert answer.status_code == 400
    assert not AuditLog.objects.filter(action=BriefingAction.REGENERATED).exists()


def test_ask_the_advisor_conversations(ledger, people, pharmacy, owner_api, ai_on, settings):
    settings.AI_FAKE = True
    client = owner_api(people.owner)
    assert client.post(url(pharmacy, "advisor/conversations/")).status_code == 403  # AI off

    ai_on()
    made = client.post(url(pharmacy, "advisor/conversations/"))
    listed = client.get(url(pharmacy, "advisor/conversations/")).json()
    ask_ai = (
        owner_api(people.owner)
        .get(f"/api/v1/owner/companies/{pharmacy.pk}/ai/conversations/")
        .json()
    )

    assert made.status_code == 201
    assert [row["id"] for row in listed] == [made.json()["id"]]
    assert ask_ai == []  # Ask AI keeps its own list
    assert owner_api(people.clerk).get(url(pharmacy, "advisor/conversations/")).status_code == 403
    latest = client.get(url(pharmacy, "latest/")).json()
    assert latest["chat"] is True and latest["advisor_on"] is True


def test_maslahatchi_off_closes_its_chat(ledger, people, pharmacy, owner_api, ai_on, settings):
    settings.AI_FAKE = True
    ai_on(advisor=False)

    answer = owner_api(people.owner).post(url(pharmacy, "advisor/conversations/"))

    assert answer.status_code == 403


def test_the_list_answers_in_few_queries(sent, people, pharmacy, owner_api, freeze):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    client = owner_api(people.owner)
    client.get(url(pharmacy))
    for weeks in range(1, 4):
        Briefing.objects.create(
            company=pharmacy,
            day=sent["owner"].day - timedelta(days=7 * weeks),
            kind="weekly",
            language="en",
            scope_key=sent["owner"].scope_key,
            facts={"period": {"kind": "weekly", "start": "2026-10-01", "end": "2026-10-07"}},
            content={"headline": "Old"},
            written_at=NOW,
        )
    with CaptureQueriesContext(connection) as queries:
        rows = client.get(url(pharmacy)).json()["results"]

    assert len(rows) == 4
    assert len(queries) <= 12
