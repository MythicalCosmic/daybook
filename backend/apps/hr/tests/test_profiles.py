"""Employee profiles: made when someone is approved, IDs encrypted and masked, the audited
reveal, who may read and change what, emergency contacts, and the employment dates payroll
prorates with."""

from datetime import date, timedelta

import pytest
from django.db import connection

from apps.audit.models import AuditLog
from apps.hr import queries, services
from apps.hr.models import EmergencyContact, EmployeeProfile
from apps.hr.tests.conftest import DAY
from apps.members import services as members
from apps.members.models import Membership
from apps.members.tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db

PINFL = "30101900123456"
PASSPORT = "AA1234567"
CARD = "8600123456789012"


def url(company, member, tail="profile"):
    return f"/api/v1/owner/companies/{company.pk}/hr/people/{member.pk}/{tail}/"


def raw(column: str, profile: EmployeeProfile) -> str:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {column} FROM hr_employeeprofile WHERE id = %s", [profile.pk])
        return cursor.fetchone()[0]


# Made on approval ----------------------------------------------------------------------


def test_approving_someone_makes_their_profile_hired_today(
    shop, staff, django_capture_on_commit_callbacks
):
    joiner = MembershipFactory(company=shop, first_name="Jasur")
    with django_capture_on_commit_callbacks(execute=True):
        members.approve(joiner, by=staff.owner.user)

    profile = EmployeeProfile.objects.get(membership=joiner)
    assert profile.hire_date == DAY
    assert profile.company_id == shop.pk


def test_coming_back_starts_a_new_stint(shop, staff, django_capture_on_commit_callbacks):
    person = staff.ali
    profile = services.ensure_profile(person)
    profile.hire_date = date(2024, 3, 1)
    profile.save()
    with django_capture_on_commit_callbacks(execute=True):
        members.offboard(person, by=staff.owner.user, terminated_on=DAY - timedelta(days=40))
    profile.refresh_from_db()
    assert profile.terminated_on == DAY - timedelta(days=40)
    assert profile.termination_reason == "other"

    Membership.objects.filter(pk=person.pk).update(status=Membership.Status.PENDING)
    with django_capture_on_commit_callbacks(execute=True):
        members.approve(Membership.objects.get(pk=person.pk), by=staff.owner.user)

    profile.refresh_from_db()
    assert (profile.hire_date, profile.terminated_on, profile.termination_reason) == (DAY, None, "")


def test_the_wizards_reason_and_note_reach_the_profile(
    shop, staff, django_capture_on_commit_callbacks
):
    services.ensure_profile(staff.vali)
    with django_capture_on_commit_callbacks(execute=True):
        members.complete_offboarding(
            staff.vali,
            by=staff.owner,
            terminated_on=DAY,
            reason="resignation",
            note="Moved to Samarkand",
            override_blockers=True,
        )

    profile = EmployeeProfile.objects.get(membership=staff.vali)
    assert profile.termination_reason == "resigned"
    assert profile.termination_note == "Moved to Samarkand"
    assert profile.terminated_on == DAY


def test_employment_dates_come_from_the_profile(shop, staff, django_capture_on_commit_callbacks):
    profile = services.ensure_profile(staff.ali)
    profile.hire_date = date(2023, 5, 2)
    profile.save()
    with django_capture_on_commit_callbacks(execute=True):
        members.offboard(staff.ali, by=staff.owner.user, terminated_on=DAY - timedelta(days=2))

    dates = queries.employment_dates(shop, [staff.ali.pk, staff.vali.pk])

    assert dates[staff.ali.pk] == (date(2023, 5, 2), DAY - timedelta(days=2))
    # No profile yet: the membership's own dates, still employed.
    assert dates[staff.vali.pk][1] is None


# Encryption, masking, the reveal ----------------------------------------------------------


def test_ids_are_encrypted_at_rest_and_masked_in_the_api(shop, staff, owner_api):
    response = owner_api(staff.owner).patch(
        url(shop, staff.ali),
        {
            "pinfl": "3010 1900 1234 56",
            "passport": "aa 1234567",
            "payout_card": CARD,
            "payout_method": "card",
            "tin": "123456789",
        },
        format="json",
    )

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["pinfl"] == "••••••••••3456"
    assert body["passport"] == "AA•••••67"
    assert body["payout_card"] == "••••••••••••9012"
    profile = EmployeeProfile.objects.get(membership=staff.ali)
    assert profile.pinfl == PINFL and profile.passport == PASSPORT
    for column, plain in (("pinfl", PINFL), ("passport", PASSPORT), ("payout_card", CARD)):
        stored = raw(column, profile)
        assert stored and plain not in stored and stored.startswith("gAAAA")
    assert raw("pinfl_digest", profile) and PINFL not in raw("pinfl_digest", profile)
    # The audit row names the secret fields, never their values.
    row = AuditLog.objects.get(action="hr.profile_changed", target_id=staff.ali.pk)
    assert sorted(row.details["fields"]) == ["passport", "payout_card", "pinfl"]
    assert PINFL not in str(row.details) and PASSPORT not in str(row.details)
    assert row.target_type == "membership"


def test_the_sensitive_read_needs_hr_sensitive_and_is_audited_every_time(shop, staff, owner_api):
    services.update_profile(staff.ali, by=staff.owner, pinfl=PINFL, passport=PASSPORT)

    for viewer in (staff.manager, staff.accountant, staff.lead):
        assert owner_api(viewer).get(url(shop, staff.ali, "sensitive")).status_code == 403
    client = owner_api(staff.owner)
    first = client.get(url(shop, staff.ali, "sensitive"))
    second = client.get(url(shop, staff.ali, "sensitive"))

    assert first.status_code == second.status_code == 200
    assert first.json()["pinfl"] == PINFL and first.json()["passport"] == PASSPORT
    assert first["Cache-Control"] == "private, no-store"
    reads = AuditLog.objects.filter(action="hr.sensitive_viewed", target_id=staff.ali.pk)
    assert reads.count() == 2
    assert {row.required_perm for row in reads} == {"hr.sensitive"}


def test_hr_view_reads_hr_manage_writes(shop, staff, owner_api):
    reader = owner_api(staff.manager)
    assert reader.get(url(shop, staff.ali)).status_code == 200
    assert (
        reader.patch(url(shop, staff.ali), {"city": "Toshkent"}, format="json").status_code == 403
    )

    writer = owner_api(staff.accountant)
    response = writer.patch(
        url(shop, staff.ali), {"city": "Toshkent", "notes": "Good"}, format="json"
    )
    assert response.status_code == 200
    assert response.json()["city"] == "Toshkent"
    assert response.json()["notes"] == "Good"
    # Notes are for hr.manage only.
    assert reader.get(url(shop, staff.ali)).json()["notes"] is None
    # An employee has no dashboard at all.
    assert owner_api(staff.vali).get(url(shop, staff.ali)).status_code == 403


def test_other_companies_and_other_branches_answer_404(shop, staff, owner_api, outsider):
    assert owner_api(staff.owner).get(url(shop, outsider)).status_code == 404
    assert owner_api(outsider).get(url(shop, staff.ali)).status_code == 404
    lead = owner_api(staff.lead)
    assert lead.get(url(shop, staff.ali)).status_code == 200  # Chilonzor
    assert lead.get(url(shop, staff.sara)).status_code == 404  # Yunusobod
    assert lead.patch(url(shop, staff.sara), {"city": "X"}, format="json").status_code == 404
    pending = MembershipFactory(company=shop)
    assert owner_api(staff.owner).get(url(shop, pending)).status_code == 404


def test_the_same_pinfl_cant_be_hired_twice(shop, staff, owner_api):
    services.update_profile(staff.ali, by=staff.owner, pinfl=PINFL)

    response = owner_api(staff.owner).patch(url(shop, staff.vali), {"pinfl": PINFL}, format="json")

    assert response.status_code == 400
    assert "PINFL" in str(response.json())
    # Another company may have the same person.
    other = services.ensure_profile(staff.sara)
    assert other.pinfl == ""


def test_a_shared_passport_is_only_a_warning(shop, staff, owner_api):
    services.update_profile(staff.ali, by=staff.owner, passport=PASSPORT)
    services.update_profile(staff.vali, by=staff.owner, passport=PASSPORT)

    body = owner_api(staff.manager).get(url(shop, staff.vali)).json()

    assert body["passport_shared"] is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pinfl", "1234"),
        ("passport", "A1234567"),
        ("payout_card", "8600"),
        ("tin", "12"),
        ("personal_phone", "call me"),
        ("birth_date", "2030-01-01"),
        ("hire_date", "2027-01-01"),
    ],
)
def test_wrong_values_are_refused_with_a_reason(shop, staff, owner_api, field, value):
    response = owner_api(staff.owner).patch(url(shop, staff.ali), {field: value}, format="json")

    assert response.status_code == 400


def test_a_current_member_has_no_last_day(shop, staff, owner_api):
    response = owner_api(staff.owner).patch(
        url(shop, staff.ali), {"terminated_on": "2026-10-01"}, format="json"
    )

    assert response.status_code == 400


def test_paying_to_a_card_needs_the_card(shop, staff, owner_api):
    response = owner_api(staff.owner).patch(
        url(shop, staff.ali), {"payout_method": "card"}, format="json"
    )

    assert response.status_code == 400


def test_the_profile_reads_the_org_and_the_status(shop, staff, owner_api):
    body = owner_api(staff.manager).get(url(shop, staff.sara)).json()

    assert body["member"]["name"] == "Sara Tosheva"
    assert body["position"]["name"] == "Pharmacist"
    assert body["home_branch"]["code"] == "YNS"
    assert body["status"] == "approved"
    assert body["can_edit"] is False and body["can_reveal"] is False
    assert body["hire_date"]  # from the membership until a profile is saved


def test_the_module_must_be_on(shop, staff, owner_api):
    shop.features = []
    shop.save(update_fields=["features"])

    assert owner_api(staff.owner).get(url(shop, staff.ali)).status_code == 403


# Emergency contacts -----------------------------------------------------------------------


def test_three_emergency_contacts_at_most(shop, staff, owner_api):
    client = owner_api(staff.accountant)
    path = url(shop, staff.ali, "emergency-contacts")
    for index in range(3):
        response = client.post(
            path, {"name": f"Ona {index}", "relation": "Ona", "phone": "+998 90 111 22 33"}
        )
        assert response.status_code == 201, response.content

    fourth = client.post(path, {"name": "Aka", "phone": "+998901112233"})

    assert fourth.status_code == 400
    assert len(client.get(path).json()) == 3
    contact = EmergencyContact.objects.filter(profile__membership=staff.ali).first()
    changed = client.patch(f"{path}{contact.pk}/", {"phone": "+998 91 000 00 00"}, format="json")
    assert changed.status_code == 200 and changed.json()["phone"] == "+998 91 000 00 00"
    assert client.delete(f"{path}{contact.pk}/").status_code == 204
    assert (
        owner_api(staff.manager).post(path, {"name": "X", "phone": "+998901112233"}).status_code
        == 403
    )
    # Someone else's contact through this person's address: not found.
    other = services.add_contact(staff.vali, by=staff.owner, name="Ota", phone="+998901112233")
    assert client.delete(f"{path}{other.pk}/").status_code == 404


# The mini app -----------------------------------------------------------------------------


def test_people_read_and_change_a_few_fields_of_their_own_profile(shop, staff, api_as):
    services.update_profile(staff.ali, by=staff.owner, pinfl=PINFL, notes="Secret note")
    client = api_as(staff.ali)
    path = f"/api/v1/companies/{shop.pk}/hr/profile/"

    body = client.get(path).json()
    assert body["pinfl"] == "••••••••••3456"
    assert "notes" not in body

    response = client.patch(
        path,
        {"city": "Toshkent", "payout_card": CARD, "pinfl": "0" * 14, "hire_date": "2020-01-01"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["payout_card"] == "••••••••••••9012"
    profile = EmployeeProfile.objects.get(membership=staff.ali)
    assert profile.city == "Toshkent" and profile.payout_card == CARD
    assert profile.pinfl == PINFL and profile.hire_date != date(2020, 1, 1)  # not theirs to change


def test_people_keep_their_own_emergency_contacts(shop, staff, api_as):
    client = api_as(staff.ali)
    path = f"/api/v1/companies/{shop.pk}/hr/profile/emergency-contacts/"

    created = client.post(path, {"name": "Ona", "phone": "+998901112233"}, format="json")
    assert created.status_code == 201
    assert [row["name"] for row in client.get(path).json()] == ["Ona"]
    theirs = services.add_contact(staff.vali, by=staff.vali, name="Ota", phone="+998901112233")
    assert client.patch(f"{path}{theirs.pk}/", {"name": "X"}, format="json").status_code == 404
    assert client.delete(f"{path}{theirs.pk}/").status_code == 404


def test_a_suspended_person_reads_but_doesnt_change_their_profile(shop, staff, api_as):
    members.suspend(staff.ali, by=staff.owner, until=None, reason="Investigation")
    client = api_as(Membership.objects.get(pk=staff.ali.pk))
    path = f"/api/v1/companies/{shop.pk}/hr/profile/"

    assert client.get(path).status_code == 200
    response = client.patch(path, {"city": "X"}, format="json")
    assert response.status_code == 403
    assert response.json()["code"] == "suspended"
