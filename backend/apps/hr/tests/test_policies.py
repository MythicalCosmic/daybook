"""Policies people read and sign: who owes a signature (positions, branches, newcomers, people
who move), a new version asks again and a small edit doesn't, signing (twice is fine), drafts and
files, the notices, reminders before the deadline and late notes to the manager (once each,
outside quiet hours), "Remind now", and what the pulse, the search and the export show."""

from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.hr.models import Policy, PolicyAcknowledgement, PolicyVersion
from apps.hr.policies import exporters, follow_up, notify, queries, services
from apps.hr.tests.conftest import DAY, local, pdf_upload
from apps.inbox.models import Notification
from apps.members import services as members
from apps.members.models import Membership

pytestmark = pytest.mark.django_db

BODY = "<h2>1. Umumiy qoidalar</h2><p>Retseptli dorilar faqat retsept bilan beriladi.</p>"


def make_policy(shop, by, **fields) -> Policy:
    fields.setdefault("title", "Dori berish qoidalari")
    fields.setdefault("category", "dispensing")
    fields.setdefault("body", BODY)
    return services.create_policy(shop, by=by, **fields)


@pytest.fixture
def rules(shop, staff):
    """Dispensing rules for every pharmacist (Ali and Vali at Chilonzor, Sara at Yunusobod)."""
    return make_policy(shop, staff.accountant, position_ids=[staff.pharmacist.pk])


def publish(policy, by, capture, **kwargs) -> PolicyVersion:
    with capture(execute=True):
        return services.publish(policy, by=by, **kwargs)


def owed(policy) -> dict[str, PolicyAcknowledgement]:
    policy.refresh_from_db()
    return {str(row.membership.first_name): row for row in queries.requests(policy)}


def notices(person, kind=notify.POLICY):
    return list(Notification.objects.filter(recipient=person, kind=kind).order_by("pk"))


# Who owes a signature ----------------------------------------------------------------------


def test_a_policy_applies_to_its_positions_and_branches_and_never_to_owners(
    shop, staff, chilonzor, yunusobod
):
    everyone = make_policy(shop, staff.accountant, title="Kassa intizomi")
    names = {str(m.first_name) for m in queries.audience(everyone)}
    # Owners set the rules; everyone else (any position, any branch) is asked.
    assert names == {"Bekzod", "Aziza", "Lola", "Ali", "Vali", "Sara"}

    pharmacists = make_policy(shop, staff.accountant, position_ids=[staff.pharmacist.pk])
    assert {m.first_name for m in queries.audience(pharmacists)} == {"Ali", "Vali", "Sara"}

    at_chilonzor = make_policy(
        shop,
        staff.accountant,
        title="Chilonzor kassasi",
        position_ids=[staff.pharmacist.pk],
        branch_ids=[chilonzor.pk],
    )
    assert {m.first_name for m in queries.audience(at_chilonzor)} == {"Ali", "Vali"}

    staff.vali.status = Membership.Status.LEFT
    staff.vali.save(update_fields=["status"])
    assert {m.first_name for m in queries.audience(at_chilonzor)} == {"Ali"}


def test_publishing_asks_everyone_it_applies_to_within_the_days(
    shop, staff, rules, django_capture_on_commit_callbacks, settings, sent_messages
):
    settings.EMPLOYEE_MINIAPP_URL = "https://app.example.uz/app/"
    assert queries.requests(rules).count() == 0  # a draft asks nobody

    version = publish(rules, staff.accountant, django_capture_on_commit_callbacks)

    rows = owed(rules)
    assert set(rows) == {"Ali", "Vali", "Sara"}
    assert {row.due_on for row in rows.values()} == {DAY + timedelta(days=7)}
    assert all(row.notified_at is not None for row in rows.values())
    assert rules.current_version == version == rules.ack_version
    # One message each, opening the policy in the mini app.
    (notice,) = notices(staff.ali)
    assert notice.app_screen == f"hr.policy:{rules.pk}"
    assert "Dori berish qoidalari" in notice.title
    assert "28.10.2026" in notice.body
    assert notices(staff.lead) == [] and notices(staff.owner) == []
    texts = [
        message for message in sent_messages if message["chat_id"] == staff.ali.user.telegram_id
    ]
    assert texts and texts[0]["reply_markup"]
    audit = AuditLog.objects.get(action="hr.policy_published")
    assert audit.details["asked"] == 3 and audit.target_id == rules.pk


def test_a_new_version_asks_again_and_a_small_edit_does_not(
    shop, staff, rules, django_capture_on_commit_callbacks, freeze
):
    first = publish(rules, staff.accountant, django_capture_on_commit_callbacks)
    services.acknowledge(first, by=staff.ali)

    # A typo fixed: nobody is asked again, Ali's signature stays.
    services.save_draft(rules, by=staff.accountant, body=BODY.replace("faqat", "faqatgina"))
    small = publish(rules, staff.accountant, django_capture_on_commit_callbacks, asks_again=False)
    rows = owed(rules)
    assert rules.current_version == small and rules.ack_version == first
    assert rows["Ali"].acknowledged_at is not None
    assert len(notices(staff.ali)) == 1 and len(notices(staff.vali)) == 1
    # Signing now signs the text in force.
    services.acknowledge(small, by=staff.vali)
    assert owed(rules)["Vali"].signed_version == small

    # A real change: everyone owes the new version, Ali too; the signatures of v1 stay on v1.
    freeze(local(DAY + timedelta(days=2), 11))
    services.save_draft(rules, by=staff.accountant, body=BODY + "<p>Yangi band.</p>")
    third = publish(rules, staff.accountant, django_capture_on_commit_callbacks)
    rows = owed(rules)
    assert rules.ack_version == third and set(rows) == {"Ali", "Vali", "Sara"}
    assert all(row.acknowledged_at is None for row in rows.values())
    assert {row.due_on for row in rows.values()} == {DAY + timedelta(days=9)}
    assert (
        PolicyAcknowledgement.objects.filter(version=first, acknowledged_at__isnull=False).count()
        == 2
    )
    # Sara never signed v1: what she owed for it is released, she owes v3 instead.
    assert not PolicyAcknowledgement.objects.filter(version=first, membership=staff.sara).exists()
    latest = notices(staff.ali)[-1]
    assert latest.title.startswith("New version to read and sign")


def test_signing_twice_changes_nothing(shop, staff, rules, django_capture_on_commit_callbacks):
    version = publish(rules, staff.accountant, django_capture_on_commit_callbacks)
    with django_capture_on_commit_callbacks(execute=True):
        first = services.acknowledge(version, by=staff.ali)
    again = services.acknowledge(version, by=staff.ali)

    assert again.pk == first.pk and again.acknowledged_at == first.acknowledged_at
    assert AuditLog.objects.filter(action="hr.policy_signed").count() == 1
    signed = AuditLog.objects.get(action="hr.policy_signed")
    assert signed.target_type == "membership" and signed.target_id == staff.ali.pk
    # The messages that asked are read now.
    assert all(notice.read_at for notice in notices(staff.ali))


def test_only_the_people_it_applies_to_sign_the_version_in_force(
    shop, staff, rules, django_capture_on_commit_callbacks, outsider
):
    version = publish(rules, staff.accountant, django_capture_on_commit_callbacks)
    with pytest.raises(PermissionDenied):
        services.acknowledge(version, by=staff.lead)  # not a pharmacist
    with pytest.raises(PermissionDenied):
        services.acknowledge(version, by=outsider)

    services.save_draft(rules, by=staff.accountant, body=BODY + "<p>2.</p>")
    publish(rules, staff.accountant, django_capture_on_commit_callbacks)
    with pytest.raises(DomainError):
        services.acknowledge(version, by=staff.ali)  # an older text

    members.suspend(staff.sara, by=staff.owner, until=None, reason="Tekshiruv")
    staff.sara.refresh_from_db()
    rules.refresh_from_db()
    with pytest.raises(PermissionDenied):
        services.acknowledge(rules.current_version, by=staff.sara)


def test_a_policy_that_asks_no_signature_is_only_announced(
    shop, staff, django_capture_on_commit_callbacks
):
    info = make_policy(shop, staff.accountant, title="Sanitariya kuni", requires_ack=False)
    publish(info, staff.accountant, django_capture_on_commit_callbacks)

    assert queries.requests(info).count() == 0
    (notice,) = notices(staff.vali)
    assert notice.title == "New rules to read: Sanitariya kuni"
    version = info.versions.get()
    with pytest.raises(DomainError):
        services.acknowledge(version, by=staff.vali)
    standing = queries.mine(staff.vali, DAY)
    assert [(item.policy.pk, item.state) for item in standing] == [(info.pk, queries.TO_READ)]


# Newcomers and people who move -------------------------------------------------------------


def test_someone_who_joins_a_position_owes_its_policies(
    shop, staff, rules, chilonzor, member, django_capture_on_commit_callbacks
):
    publish(rules, staff.accountant, django_capture_on_commit_callbacks)
    second = make_policy(shop, staff.accountant, title="Saqlash va harorat rejimi")
    publish(second, staff.accountant, django_capture_on_commit_callbacks)

    newcomer = member(shop, "Employee", status=Membership.Status.PENDING, first_name="Kamola")
    with django_capture_on_commit_callbacks(execute=True):
        members.approve(
            newcomer,
            by=staff.owner.user,
            position=staff.pharmacist,
            branches=[chilonzor],
            home_branch=chilonzor,
        )

    assert "Kamola" in owed(rules) and "Kamola" in owed(second)
    # Both at once in one message, opening the list.
    (notice,) = notices(newcomer)
    assert notice.app_screen == "hr.policies"
    assert notice.title == "Rules to read and sign: 2"
    assert "Dori berish qoidalari" in notice.body and "Saqlash va harorat rejimi" in notice.body


def test_the_beat_follows_people_who_move(
    shop, staff, rules, django_capture_on_commit_callbacks, freeze
):
    publish(rules, staff.accountant, django_capture_on_commit_callbacks)
    staff.ali.position = staff.office
    staff.ali.save(update_fields=["position"])
    staff.lead.position = staff.pharmacist
    staff.lead.save(update_fields=["position"])

    freeze(local(DAY, 10, 30))
    with django_capture_on_commit_callbacks(execute=True):
        follow_up.follow_up()

    rows = owed(rules)
    assert "Ali" not in rows and "Lola" in rows
    assert not PolicyAcknowledgement.objects.filter(membership=staff.ali).exists()
    assert len(notices(staff.lead)) == 1


# Reminders and late notes ------------------------------------------------------------------


def test_one_reminder_the_day_before_the_deadline_outside_quiet_hours(
    shop, staff, rules, django_capture_on_commit_callbacks, freeze
):
    version = publish(rules, staff.accountant, django_capture_on_commit_callbacks)
    services.acknowledge(version, by=staff.ali)

    freeze(local(DAY + timedelta(days=5), 10))  # two days before: nothing yet
    assert follow_up.follow_up() == 0

    freeze(local(DAY + timedelta(days=5), 23, 10))  # the night before: quiet hours
    assert follow_up.follow_up() == 0

    freeze(local(DAY + timedelta(days=6), 8, 5))  # the day before the deadline, morning
    assert follow_up.follow_up() == 2  # Vali and Sara (Ali signed)
    latest = notices(staff.vali)[-1]
    assert latest.title == "Sign by tomorrow: Dori berish qoidalari"

    freeze(local(DAY + timedelta(days=6), 15))
    assert follow_up.follow_up() == 0
    freeze(local(DAY + timedelta(days=7), 9))  # the last day: reminded already
    assert follow_up.follow_up() == 0
    assert len(notices(staff.vali)) == 2


def test_the_manager_hears_once_who_is_late(
    shop, staff, rules, chilonzor, yunusobod, django_capture_on_commit_callbacks, freeze
):
    chilonzor.manager = staff.lead
    chilonzor.save(update_fields=["manager"])
    publish(rules, staff.accountant, django_capture_on_commit_callbacks)

    freeze(local(DAY + timedelta(days=8), 9))  # the day after the deadline
    follow_up.follow_up()
    # Chilonzor's manager hears about Ali and Vali in one message; Sara's branch has no
    # manager, so HR in her branches hears about her.
    (late,) = notices(staff.lead, notify.POLICY_LATE)
    assert late.title == "Not signed in time: Dori berish qoidalari"
    assert "Ali Valiyev" in late.body and "Vali Aliyev" in late.body and "Sara" not in late.body
    assert late.url.endswith(f"/hr/policies/{rules.pk}?state=late")
    (about_sara,) = notices(staff.accountant, notify.POLICY_LATE)
    assert "Sara Tosheva" in about_sara.body and "Ali" not in about_sara.body

    freeze(local(DAY + timedelta(days=9), 9))
    follow_up.follow_up()
    assert len(notices(staff.lead, notify.POLICY_LATE)) == 1
    assert queries.state(owed(rules)["Ali"], DAY + timedelta(days=9)) == queries.LATE


def test_remind_now_reaches_who_is_still_to_sign_in_scope_once_in_a_while(
    shop, staff, rules, django_capture_on_commit_callbacks, freeze
):
    version = publish(rules, staff.accountant, django_capture_on_commit_callbacks)
    services.acknowledge(version, by=staff.ali)

    # Lola manages Chilonzor only: Vali is hers, Sara isn't.
    assert services.remind(rules, by=staff.lead) == 1
    assert len(notices(staff.vali)) == 2 and len(notices(staff.sara)) == 1
    with pytest.raises(DomainError):
        services.remind(rules, by=staff.lead)

    freeze(local(DAY, 17))
    assert services.remind(rules, by=staff.accountant, member_ids=[staff.sara.pk]) == 1
    with pytest.raises(PermissionDenied):
        services.remind(rules, by=staff.manager)  # hr.view only
    assert AuditLog.objects.filter(action="hr.policy_reminded").count() == 2


# Settings, drafts, files -------------------------------------------------------------------


def test_settings_apply_at_once(
    shop, staff, rules, chilonzor, django_capture_on_commit_callbacks, freeze
):
    publish(rules, staff.accountant, django_capture_on_commit_callbacks)
    freeze(local(DAY + timedelta(days=1), 10))

    with django_capture_on_commit_callbacks(execute=True):
        services.update_policy(rules, by=staff.accountant, ack_within_days=14)
    assert {row.due_on for row in owed(rules).values()} == {DAY + timedelta(days=14)}

    with django_capture_on_commit_callbacks(execute=True):
        services.update_policy(rules, by=staff.accountant, branch_ids=[chilonzor.pk])
    assert set(owed(rules)) == {"Ali", "Vali"}

    services.update_policy(rules, by=staff.accountant, is_active=False)
    assert PolicyAcknowledgement.objects.filter(version__policy=rules).count() == 0
    assert AuditLog.objects.filter(action="hr.policy_archived").exists()
    with pytest.raises(DomainError):
        services.publish(rules, by=staff.accountant)


def test_a_branch_manager_writes_only_the_policies_of_their_branches(
    shop, staff, rules, chilonzor, yunusobod
):
    with pytest.raises(PermissionDenied):
        services.update_policy(rules, by=staff.lead, title="Boshqa")  # company-wide
    with pytest.raises(DomainError):
        make_policy(shop, staff.lead, title="Yunusobod", branch_ids=[yunusobod.pk])
    with pytest.raises(DomainError):
        make_policy(shop, staff.lead, title="Hammaga")
    own = make_policy(shop, staff.lead, title="Chilonzor kassasi", branch_ids=[chilonzor.pk])
    services.update_policy(own, by=staff.lead, ack_within_days=3)
    with pytest.raises(PermissionDenied):
        make_policy(shop, staff.manager, title="Ko‘rish huquqi bilan")


def test_drafts_start_from_the_version_in_force_and_files_stay_with_their_versions(
    shop, staff, rules, django_capture_on_commit_callbacks, private_media
):
    services.save_draft(rules, by=staff.accountant, file=pdf_upload())
    first = publish(rules, staff.accountant, django_capture_on_commit_callbacks)
    assert first.file and first.file.name.endswith(".pdf")

    draft = services.save_draft(rules, by=staff.accountant, change_note="Tuzatish")
    assert draft.number == 2 and draft.body == first.body and draft.file.name == first.file.name
    with django_capture_on_commit_callbacks(execute=True):
        services.save_draft(rules, by=staff.accountant, remove_file=True)
    first.refresh_from_db()
    assert first.file  # the published version keeps its file
    assert (private_media / first.file.name).exists()

    with django_capture_on_commit_callbacks(execute=True):
        services.discard_draft(rules, by=staff.accountant)
    assert queries.draft_of(rules) is None
    with pytest.raises(DomainError):
        services.publish(rules, by=staff.accountant)
    with pytest.raises(DomainError):
        services.delete_policy(rules, by=staff.accountant)


def test_the_text_is_cleaned_and_a_file_must_be_a_pdf_or_a_picture(shop, staff):
    policy = make_policy(
        shop,
        staff.accountant,
        body='<p onclick="x()">Qoida</p><script>alert(1)</script><img data-image-id="3">',
    )
    draft = policy.versions.get()
    assert draft.body == "<p>Qoida</p>" and draft.body_text == "Qoida"
    with pytest.raises(DomainError):
        services.save_draft(
            policy, by=staff.accountant, file=SimpleUploadedFile("x.html", b"<html></html>")
        )
    with pytest.raises(DomainError):
        services.publish(
            make_policy(shop, staff.accountant, title="Bo‘sh", body=""), by=staff.accountant
        )
    services.delete_policy(policy, by=staff.accountant)
    assert not Policy.objects.filter(pk=policy.pk).exists()


# Quiet hours, the pulse, the search, the export ----------------------------------------------


def test_publishing_at_night_tells_people_in_the_morning(
    shop, staff, rules, django_capture_on_commit_callbacks, freeze
):
    freeze(local(DAY, 23, 30))
    publish(rules, staff.accountant, django_capture_on_commit_callbacks)
    assert notices(staff.ali) == []
    assert all(row.notified_at is None for row in owed(rules).values())

    freeze(local(DAY + timedelta(days=1), 8, 2))
    follow_up.follow_up()
    assert len(notices(staff.ali)) == 1


def test_the_late_badge_search_and_export_follow_the_scope(
    shop, staff, rules, django_capture_on_commit_callbacks, freeze
):
    version = publish(rules, staff.accountant, django_capture_on_commit_callbacks)
    services.acknowledge(version, by=staff.ali)
    freeze(local(DAY + timedelta(days=8), 10))

    assert queries.late_count(staff.accountant) == 2  # Vali and Sara
    assert queries.late_count(staff.lead) == 1  # Vali (Chilonzor)

    (hit,) = queries.search(staff.lead, "retsept", 5)
    assert hit.id == rules.pk and hit.url == f"/c/{shop.pk}/hr/policies/{rules.pk}"

    rows = list(exporters.rows(staff.lead, {"policy": rules.pk}))
    assert [(row["person"], row["status"]) for row in rows] == [
        ("Ali Valiyev", "Signed"),
        ("Vali Aliyev", "Late"),
    ]
    late_only = list(exporters.rows(staff.accountant, {"state": "late"}))
    assert {row["person"] for row in late_only} == {"Vali Aliyev", "Sara Tosheva"}
