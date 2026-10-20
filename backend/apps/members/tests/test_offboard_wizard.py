"""The single offboarding wizard: steps other modules register, their blockers and questions,
and the answers that reach `member_left` receivers."""

import pytest
from django.utils import timezone

from apps.console import registry
from apps.console.registry import FieldSpec, OffboardStep
from apps.core.exceptions import DomainError
from apps.members import services
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.signals import member_left
from apps.timeoff.models import TimeOff

pytestmark = pytest.mark.django_db

URL = "/api/v1/owner/companies/{cid}/people/{pk}/"


@pytest.fixture
def fake_step(isolated_registries):
    """A finance-like step with a blocker switch and a required question."""
    state = {"blocked": False}

    def preview(membership):
        return OffboardStep(
            lines=["Holds 1 200 000 so‘m of company cash."],
            blockers=["Open till CHL-1042 must be closed first."] if state["blocked"] else [],
            fields=[
                FieldSpec("handover_to", "Hand the cash to", kind="member", required=True),
                FieldSpec("note", "Note", kind="text"),
            ],
            defaults={"note": ""},
        )

    registry.OFFBOARD_STEPS.add(
        registry.OffboardStepProvider(
            "sales", "sales", Perm.MEMBERS_MANAGE, None, 30, "Cash", preview
        )
    )
    return state


@pytest.fixture
def received():
    seen = []

    def receiver(sender, membership, reason, details, terminated_on, **kwargs):
        seen.append({"reason": reason, "details": details, "terminated_on": terminated_on})

    member_left.connect(receiver, weak=False)
    yield seen
    member_left.disconnect(receiver)


def test_the_preview_shows_every_step_in_order(owner_api, company, member, fake_step):
    owner = member.registered(company, "Owner")
    worker = member.registered(company)
    today = timezone.localdate()
    TimeOff.objects.create(
        company=company,
        membership=worker,
        first_day=today,
        last_day=today,
        status=TimeOff.Status.APPROVED,
    )

    response = owner_api(owner).get(URL.format(cid=company.pk, pk=worker.pk) + "offboard-preview/")

    assert response.status_code == 200
    keys = [step["key"] for step in response.data["steps"]]
    assert keys == ["members", "sales", "timeoff"]
    sales = response.data["steps"][1]
    assert sales["lines"] == ["Holds 1 200 000 so‘m of company cash."]
    assert sales["fields"][0]["name"] == "handover_to" and sales["fields"][0]["required"]
    assert response.data["can_override"] is True
    assert "resignation" in response.data["reasons"]


def test_answers_reach_member_left_in_details(
    owner_api, company, member, fake_step, received, django_capture_on_commit_callbacks
):
    owner = member.registered(company, "Owner")
    worker = member.registered(company)
    keeper = member.registered(company)

    with django_capture_on_commit_callbacks(execute=True):
        response = owner_api(owner).post(
            URL.format(cid=company.pk, pk=worker.pk) + "offboard/",
            {
                "reason": "resignation",
                "note": "Moving to Samarkand",
                "steps": {"sales": {"handover_to": keeper.pk}},
            },
            format="json",
        )

    assert response.status_code == 200, response.data
    assert response.data["status"] == "left"
    [event] = received
    assert event["reason"] == "left"
    assert event["details"]["sales"] == {"note": "", "handover_to": keeper.pk}
    assert event["details"]["members"]["reason"] == "resignation"
    assert event["details"]["members"]["note"] == "Moving to Samarkand"
    assert event["terminated_on"] == timezone.localdate()


def test_a_required_answer_is_required(company, member, fake_step):
    owner = member.registered(company, "Owner")
    worker = member.registered(company)

    with pytest.raises(DomainError, match="Hand the cash to"):
        services.complete_offboarding(worker, by=owner, terminated_on=None, reason="dismissal")


def test_a_blocker_stops_it_unless_an_owner_overrides(owner_api, company, member, fake_step):
    fake_step["blocked"] = True
    manager_role = member.registered(company, "Manager").role
    manager_role.permissions = [*manager_role.permissions, Perm.MEMBERS_MANAGE]
    manager_role.save()
    manager = member.registered(company, "Manager")
    owner = member.registered(company, "Owner")
    worker = member.registered(company)
    body = {"reason": "dismissal", "steps": {"sales": {"handover_to": owner.pk}}}
    url = URL.format(cid=company.pk, pk=worker.pk) + "offboard/"

    blocked = owner_api(owner).post(url, body, format="json")
    assert blocked.status_code == 400
    assert "CHL-1042" in str(blocked.data)
    not_owner = owner_api(manager).post(url, body | {"override_blockers": True}, format="json")
    assert not_owner.status_code == 403
    overridden = owner_api(owner).post(url, body | {"override_blockers": True}, format="json")
    assert overridden.status_code == 200
    worker.refresh_from_db()
    assert worker.status == Membership.Status.LEFT


def test_the_system_completes_a_scheduled_termination(
    company, member, received, django_capture_on_commit_callbacks
):
    member.registered(company, "Owner")
    worker = member.registered(company)

    with django_capture_on_commit_callbacks(execute=True):
        services.complete_offboarding(
            worker,
            by=None,
            terminated_on=None,
            reason="contract_end",
            steps={"lifecycle": {"rehire": "yes"}},
        )

    worker.refresh_from_db()
    assert worker.status == Membership.Status.LEFT
    assert received[0]["details"]["members"]["reason"] == "contract_end"


def test_future_time_off_is_cancelled(company, member):
    owner = member.registered(company, "Owner")
    worker = member.registered(company)
    today = timezone.localdate()
    future = TimeOff.objects.create(
        company=company,
        membership=worker,
        first_day=today,
        last_day=today,
        status=TimeOff.Status.APPROVED,
    )

    services.complete_offboarding(worker, by=owner, terminated_on=today, reason="redundancy")

    future.refresh_from_db()
    assert future.status == TimeOff.Status.CANCELLED


def test_an_unknown_reason_is_refused(company, member):
    owner = member.registered(company, "Owner")
    worker = member.registered(company)

    with pytest.raises(DomainError):
        services.complete_offboarding(worker, by=owner, terminated_on=None, reason="vibes")
