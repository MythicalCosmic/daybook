"""The policy endpoints: the dashboard's (list, editor, publish, versions, the people grid,
"Remind now", the audience preview, a person's signatures) and the mini app's (my rules, one to
read, its file, "O‘qidim va roziman"), with the rule 21 checks: another company's id answers 404,
a missing permission 403, branch scope, no hidden fields, and the module switch."""

from datetime import timedelta

import pytest

from apps.hr.models import Policy
from apps.hr.policies import services
from apps.hr.tests.conftest import DAY, local, pdf_upload
from apps.members import services as members

pytestmark = pytest.mark.django_db

BODY = "<h2>Saqlash</h2><p>Sovuq zanjir: +2 dan +8 gacha.</p><p>Namlik 60% dan oshmasin.</p>"


def base(company) -> str:
    return f"/api/v1/owner/companies/{company.pk}/hr/"


def mine(company) -> str:
    return f"/api/v1/companies/{company.pk}/hr/"


@pytest.fixture
def storage(shop, staff, django_capture_on_commit_callbacks):
    """Storage rules for the pharmacists, published (version 1)."""
    policy = services.create_policy(
        shop,
        by=staff.accountant,
        title="Saqlash va harorat rejimi",
        category="storage",
        position_ids=[staff.pharmacist.pk],
        body=BODY,
    )
    with django_capture_on_commit_callbacks(execute=True):
        services.publish(policy, by=staff.accountant)
    policy.refresh_from_db()
    return policy


def test_hr_writes_and_publishes_a_policy_from_the_dashboard(
    shop, staff, chilonzor, owner_api, django_capture_on_commit_callbacks
):
    client = owner_api(staff.accountant)
    preview = client.get(
        f"{base(shop)}policies/audience/", {"position": staff.pharmacist.pk, "branch": chilonzor.pk}
    )
    assert preview.status_code == 200
    assert preview.json()["count"] == 2
    assert {person["name"] for person in preview.json()["people"]} == {"Ali Valiyev", "Vali Aliyev"}

    created = client.post(
        f"{base(shop)}policies/",
        {
            "title": "Dori berish qoidalari",
            "category": "dispensing",
            "position_ids": [staff.pharmacist.pk],
            "branch_ids": [],
            "requires_ack": True,
            "ack_within_days": 5,
            "body": "<p>Retseptli dorilar faqat retsept bilan.</p>",
        },
        format="json",
    )
    assert created.status_code == 201, created.content
    policy = created.json()
    assert policy["version"] is None and policy["draft"]["number"] == 1
    assert policy["audience_count"] == 3 and policy["can_change"] is True
    pk = policy["id"]

    saved = client.put(
        f"{base(shop)}policies/{pk}/draft/",
        {"file": pdf_upload("buyruq.pdf"), "change_note": "Birinchi tahrir"},
        format="multipart",
    )
    assert saved.status_code == 200, saved.content
    assert saved.json()["has_file"] is True and saved.json()["file_type"] == "pdf"
    assert saved.json()["file_url"].startswith("/api/v1/files/")

    with django_capture_on_commit_callbacks(execute=True):
        published = client.post(f"{base(shop)}policies/{pk}/publish/", {}, format="json")
    assert published.status_code == 200, published.content
    body = published.json()
    assert body["version"]["number"] == 1 and body["draft"] is None
    assert body["tally"] == {"total": 3, "signed": 0, "waiting": 3, "late": 0}
    assert body["due_on"] == (DAY + timedelta(days=5)).isoformat()
    assert [version["number"] for version in body["versions"]] == [1]
    assert body["versions"][0]["published_by"] == "Aziza Rasulova"

    listed = client.get(f"{base(shop)}policies/")
    assert [row["id"] for row in listed.json()] == [pk]
    assert client.get(f"{base(shop)}policies/", {"view": "drafts"}).json() == []

    text = client.get(f"{base(shop)}policies/{pk}/versions/1/")
    assert text.status_code == 200
    assert text.json()["body_text"] == "Retseptli dorilar faqat retsept bilan."

    changed = client.patch(f"{base(shop)}policies/{pk}/", {"title": "Dori berish"}, format="json")
    assert changed.status_code == 200 and changed.json()["title"] == "Dori berish"


def test_the_people_grid_and_remind_now(shop, staff, storage, owner_api, freeze):
    services.acknowledge(storage.current_version, by=staff.ali)
    freeze(local(DAY + timedelta(days=8), 10))
    client = owner_api(staff.accountant)

    grid = client.get(f"{base(shop)}policies/{storage.pk}/acknowledgements/")
    assert grid.status_code == 200
    rows = {row["member"]["name"]: row for row in grid.json()["results"]}
    assert {name: row["state"] for name, row in rows.items()} == {
        "Ali Valiyev": "signed",
        "Vali Aliyev": "late",
        "Sara Tosheva": "late",
    }
    assert rows["Ali Valiyev"]["signed_number"] == 1
    # Nothing about a person beyond who they are and where they work.
    assert set(rows["Vali Aliyev"]["member"]) == {"id", "name", "photo_url"}
    assert "telegram_id" not in grid.content.decode() and "phone" not in grid.content.decode()

    late = client.get(f"{base(shop)}policies/{storage.pk}/acknowledgements/", {"state": "late"})
    assert late.json()["count"] == 2
    reminded = client.post(
        f"{base(shop)}policies/{storage.pk}/remind/", {"member_ids": [staff.vali.pk]}, format="json"
    )
    assert reminded.status_code == 200 and reminded.json() == {"reminded": 1}
    again = client.post(f"{base(shop)}policies/{storage.pk}/remind/", {}, format="json")
    assert again.json() == {"reminded": 1}  # Sara; Vali was reminded a moment ago
    third = client.post(f"{base(shop)}policies/{storage.pk}/remind/", {}, format="json")
    assert third.status_code == 400


def test_another_companys_policy_answers_404(shop, staff, storage, owner_api, outsider):
    client = owner_api(outsider)
    other = f"/api/v1/owner/companies/{outsider.company_id}/hr/policies/{storage.pk}/"
    assert client.get(other).status_code == 404
    assert client.post(f"{other}publish/", {}, format="json").status_code == 404
    assert client.get(f"{other}acknowledgements/").status_code == 404
    assert owner_api(staff.accountant).get(f"{base(shop)}policies/999999/").status_code == 404


def test_reading_needs_hr_view_and_writing_hr_manage(shop, staff, storage, owner_api):
    viewer = owner_api(staff.manager)  # hr.view, no hr.manage
    assert viewer.get(f"{base(shop)}policies/").status_code == 200
    assert viewer.get(f"{base(shop)}policies/{storage.pk}/acknowledgements/").status_code == 200
    assert viewer.post(f"{base(shop)}policies/", {"title": "X"}, format="json").status_code == 403
    assert viewer.post(f"{base(shop)}policies/{storage.pk}/publish/", {}).status_code == 403
    assert viewer.post(f"{base(shop)}policies/{storage.pk}/remind/", {}).status_code == 403
    assert viewer.patch(f"{base(shop)}policies/{storage.pk}/", {"title": "Y"}).status_code == 403
    assert viewer.delete(f"{base(shop)}policies/{storage.pk}/").status_code == 403

    nobody = owner_api(staff.ali)  # no dashboard
    assert nobody.get(f"{base(shop)}policies/").status_code == 403


def test_branch_scope_on_policies_and_their_people(
    shop, staff, storage, chilonzor, yunusobod, owner_api
):
    only_yunusobod = services.create_policy(
        shop, by=staff.accountant, title="Yunusobod tungi smena", branch_ids=[yunusobod.pk]
    )
    client = owner_api(staff.lead)  # Chilonzor only

    titles = {row["title"] for row in client.get(f"{base(shop)}policies/", {"view": "all"}).json()}
    assert titles == {"Saqlash va harorat rejimi"}
    assert client.get(f"{base(shop)}policies/{only_yunusobod.pk}/").status_code == 404

    detail = client.get(f"{base(shop)}policies/{storage.pk}/").json()
    assert detail["tally"]["total"] == 2 and detail["can_change"] is False
    grid = client.get(f"{base(shop)}policies/{storage.pk}/acknowledgements/").json()
    assert {row["member"]["name"] for row in grid["results"]} == {"Ali Valiyev", "Vali Aliyev"}
    # A company-wide policy reaches Yunusobod too: not theirs to change.
    assert client.patch(f"{base(shop)}policies/{storage.pk}/", {"title": "Z"}).status_code == 403
    refused = client.post(
        f"{base(shop)}policies/",
        {"title": "Yunusobod", "branch_ids": [yunusobod.pk]},
        format="json",
    )
    assert refused.status_code == 400
    own = client.post(
        f"{base(shop)}policies/",
        {"title": "Chilonzor kassasi", "branch_ids": [chilonzor.pk]},
        format="json",
    )
    assert own.status_code == 201 and own.json()["can_change"] is True
    assert client.get(f"{base(shop)}people/{staff.sara.pk}/policies/").status_code == 404


def test_a_persons_policies_and_signatures(
    shop, staff, storage, owner_api, django_capture_on_commit_callbacks
):
    first = storage.current_version
    services.acknowledge(first, by=staff.ali)
    services.save_draft(storage, by=staff.accountant, body=BODY + "<p>Yangi band.</p>")
    with django_capture_on_commit_callbacks(execute=True):
        services.publish(storage, by=staff.accountant)

    found = owner_api(staff.accountant).get(f"{base(shop)}people/{staff.ali.pk}/policies/")
    assert found.status_code == 200
    data = found.json()
    assert [(row["policy"]["title"], row["number"], row["state"]) for row in data["current"]] == [
        ("Saqlash va harorat rejimi", 2, "waiting")
    ]
    assert [(row["number"], row["signed_number"]) for row in data["history"]] == [(1, 1)]


def test_the_module_switch(shop, staff, storage, owner_api, api_as):
    shop.features = ["payroll"]
    shop.save(update_fields=["features"])
    assert owner_api(staff.accountant).get(f"{base(shop)}policies/").status_code == 403
    assert api_as(staff.ali).get(f"{mine(shop)}policies/").status_code == 403


def test_deleting_only_what_was_never_published(shop, staff, storage, owner_api):
    client = owner_api(staff.accountant)
    assert client.delete(f"{base(shop)}policies/{storage.pk}/").status_code == 400
    draft = services.create_policy(shop, by=staff.accountant, title="Qoralama")
    assert client.delete(f"{base(shop)}policies/{draft.pk}/").status_code == 204
    assert not Policy.objects.filter(pk=draft.pk).exists()


# The mini app ------------------------------------------------------------------------------


def test_my_rules_to_sign_first_and_signing_in_the_app(
    shop, staff, storage, api_as, django_capture_on_commit_callbacks
):
    info = services.create_policy(
        shop, by=staff.accountant, title="Ichki tartib", requires_ack=False
    )
    services.save_draft(info, by=staff.accountant, body="<p>Ish vaqti 08:00 dan.</p>")
    with django_capture_on_commit_callbacks(execute=True):
        services.publish(info, by=staff.accountant)
    client = api_as(staff.vali)

    listed = client.get(f"{mine(shop)}policies/")
    assert listed.status_code == 200
    assert [(row["title"], row["state"]) for row in listed.json()] == [
        ("Saqlash va harorat rejimi", "waiting"),
        ("Ichki tartib", "to_read"),
    ]
    detail = client.get(f"{mine(shop)}policies/{storage.pk}/").json()
    assert detail["body"] == BODY and detail["due_on"] == (DAY + timedelta(days=7)).isoformat()

    signed = client.post(f"{mine(shop)}policies/versions/{detail['version_id']}/acknowledge/")
    assert signed.status_code == 200, signed.content
    assert signed.json()["state"] == "signed" and signed.json()["signed_number"] == 1
    twice = client.post(f"{mine(shop)}policies/versions/{detail['version_id']}/acknowledge/")
    assert twice.status_code == 200 and twice.json()["signed_at"] == signed.json()["signed_at"]

    # Not Lola's (an office position), nor anyone else's company's.
    assert api_as(staff.lead).get(f"{mine(shop)}policies/{storage.pk}/").status_code == 404
    assert (
        api_as(staff.lead)
        .post(f"{mine(shop)}policies/versions/{detail['version_id']}/acknowledge/")
        .status_code
        == 404
    )


def test_the_file_opens_through_a_short_signed_link(
    shop, staff, api_as, owner_api, django_capture_on_commit_callbacks
):
    policy = services.create_policy(
        shop, by=staff.accountant, title="Buyruq", position_ids=[staff.pharmacist.pk]
    )
    services.save_draft(policy, by=staff.accountant, file=pdf_upload())
    with django_capture_on_commit_callbacks(execute=True):
        services.publish(policy, by=staff.accountant)

    link = api_as(staff.ali).get(f"{mine(shop)}policies/{policy.pk}/file/")
    assert link.status_code == 200
    opened = api_as(staff.ali).get(link.json()["url"])
    assert opened.status_code == 200 and b"".join(opened.streaming_content).startswith(b"%PDF")
    # Lola isn't a pharmacist: the app gives her no link.
    assert api_as(staff.lead).get(f"{mine(shop)}policies/{policy.pk}/file/").status_code == 404
    # The link is checked again when it is used: once Ali moves to the office it opens nothing.
    staff.ali.position = staff.office
    staff.ali.save(update_fields=["position"])
    assert api_as(staff.ali).get(link.json()["url"]).status_code in (403, 404)
    # HR opens any version's file from the dashboard.
    text = owner_api(staff.accountant).get(f"{base(shop)}policies/{policy.pk}/versions/1/")
    assert owner_api(staff.accountant).get(text.json()["file_url"]).status_code == 200


def test_a_suspended_person_reads_but_does_not_sign(shop, staff, storage, api_as):
    members.suspend(staff.sara, by=staff.owner, until=None, reason="Tekshiruv")
    client = api_as(staff.sara)
    detail = client.get(f"{mine(shop)}policies/{storage.pk}/")
    assert detail.status_code == 200
    refused = client.post(
        f"{mine(shop)}policies/versions/{detail.json()['version_id']}/acknowledge/"
    )
    assert refused.status_code == 403
