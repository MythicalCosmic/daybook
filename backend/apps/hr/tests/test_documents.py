"""Documents: private uploads, the ID kinds only `hr.sensitive` reads, audited downloads,
verification, the expiry filters, the required documents and the compliance matrix, and the
person's own documents in the mini app."""

from datetime import timedelta
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.audit.models import AuditLog
from apps.hr import queries, services
from apps.hr.models import EmployeeDocument, RequiredDocument
from apps.hr.tests.conftest import DAY, pdf_upload
from apps.hr.tests.factories import EmployeeDocumentFactory
from apps.members import services as members
from apps.members.models import Membership

pytestmark = pytest.mark.django_db


def base(company) -> str:
    return f"/api/v1/owner/companies/{company.pk}/hr/"


def jpeg() -> SimpleUploadedFile:
    out = BytesIO()
    Image.new("RGB", (30, 20), (10, 120, 200)).save(out, "PNG")
    return SimpleUploadedFile("photo.png", out.getvalue(), content_type="image/png")


def doc(member, **fields) -> EmployeeDocument:
    return EmployeeDocumentFactory(membership=member, **fields)


def upload(client, company, member, **fields):
    return client.post(
        f"{base(company)}documents/",
        {"member_id": member.pk, "file": pdf_upload(), **fields},
        format="multipart",
    )


# Uploads and what each one sees ------------------------------------------------------------


def test_hr_uploads_a_medical_book_into_private_storage(shop, staff, owner_api, private_media):
    response = upload(
        owner_api(staff.accountant),
        shop,
        staff.ali,
        kind="medical_book",
        number="TB 123/45",
        issued_on="2026-01-10",
        expires_on="2026-11-10",
    )

    assert response.status_code == 201, response.content
    body = response.json()
    assert body["number"] == "TB123/45"
    assert body["state"] == "expiring" and body["days_left"] == 20
    assert body["verified"] is False and body["file"].startswith("/api/v1/files/")
    document = EmployeeDocument.objects.get(pk=body["id"])
    assert document.file.name.startswith(f"hr/documents/{shop.pk}/")
    assert (private_media / document.file.name).exists()
    assert AuditLog.objects.filter(action="hr.document_added", target_id=staff.ali.pk).exists()


def test_a_file_that_isnt_a_pdf_or_a_picture_is_refused(shop, staff, owner_api):
    bad = SimpleUploadedFile(
        "x.pdf", b"<html><script>alert(1)</script>", content_type="application/pdf"
    )
    response = owner_api(staff.owner).post(
        f"{base(shop)}documents/",
        {"member_id": staff.ali.pk, "kind": "diploma", "file": bad},
        format="multipart",
    )

    assert response.status_code == 400
    assert not EmployeeDocument.objects.exists()


def test_pictures_are_re_encoded(shop, staff, owner_api):
    response = owner_api(staff.owner).post(
        f"{base(shop)}documents/",
        {"member_id": staff.ali.pk, "kind": "photo", "file": jpeg()},
        format="multipart",
    )

    assert response.status_code == 201
    assert EmployeeDocument.objects.get().file.name.endswith(".jpg")


def test_an_ids_number_and_scan_need_hr_sensitive(shop, staff, owner_api, client):
    created = upload(
        owner_api(staff.accountant), shop, staff.ali, kind="passport", number="AA1234567"
    )
    assert created.status_code == 201
    # The accountant (hr.manage) entered it, but can't read it back.
    assert created.json()["number"] == "AA•••••67"
    assert created.json()["file"] is None and created.json()["file_hidden"] is True
    document_id = created.json()["id"]

    as_manager = owner_api(staff.manager).get(f"{base(shop)}documents/{document_id}/").json()
    assert as_manager["number"] == "AA•••••67" and as_manager["file"] is None
    as_owner = owner_api(staff.owner).get(f"{base(shop)}documents/{document_id}/").json()
    assert as_owner["number"] == "AA1234567"

    # The owner's link opens; every opening is audited as a sensitive view.
    opened = owner_api(staff.owner).get(as_owner["file"])
    assert opened.status_code == 200
    assert opened["Content-Type"] == "application/pdf"
    row = AuditLog.objects.get(action="hr.document_opened")
    assert row.required_perm == "hr.sensitive" and row.details["document"] == document_id
    # Verifying an ID means looking at it.
    verify = f"{base(shop)}documents/{document_id}/verify/"
    assert owner_api(staff.accountant).post(verify).status_code == 403
    assert owner_api(staff.owner).post(verify).json()["verified"] is True


def test_a_link_stops_working_when_access_goes(shop, staff, owner_api):
    created = upload(owner_api(staff.owner), shop, staff.ali, kind="diploma")
    link = (
        owner_api(staff.manager)
        .get(f"{base(shop)}documents/{created.json()['id']}/")
        .json()["file"]
    )
    client = owner_api(staff.manager)
    assert client.get(link).status_code == 200
    staff.manager.role.permissions.remove("hr.view")
    staff.manager.role.save()

    assert client.get(link).status_code == 404
    assert AuditLog.objects.filter(action="hr.document_opened").count() == 1


def test_branch_scope_and_other_companies(shop, staff, owner_api, outsider):
    mine = doc(staff.ali, kind="diploma")
    yunusobod = doc(staff.sara, kind="diploma")
    theirs = doc(outsider, kind="diploma")

    lead = owner_api(staff.lead)
    listed = [row["id"] for row in lead.get(f"{base(shop)}documents/").json()["results"]]
    assert listed == [mine.pk]
    assert lead.get(f"{base(shop)}documents/{yunusobod.pk}/").status_code == 404
    owner = owner_api(staff.owner)
    assert owner.get(f"{base(shop)}documents/{theirs.pk}/").status_code == 404
    assert owner.get(f"{base(shop)}documents/?member={outsider.pk}").json()["results"] == []
    created = upload(owner, shop, outsider, kind="diploma")
    assert created.status_code == 404
    assert upload(lead, shop, staff.sara, kind="diploma").status_code == 404


def test_hr_view_reads_hr_manage_writes(shop, staff, owner_api):
    document = doc(staff.ali, kind="diploma")
    reader = owner_api(staff.manager)

    assert reader.get(f"{base(shop)}documents/").status_code == 200
    assert upload(reader, shop, staff.ali, kind="diploma").status_code == 403
    assert reader.patch(f"{base(shop)}documents/{document.pk}/", {"title": "X"}).status_code == 403
    assert reader.delete(f"{base(shop)}documents/{document.pk}/").status_code == 403
    assert reader.post(f"{base(shop)}documents/{document.pk}/verify/").status_code == 403
    writer = owner_api(staff.accountant)
    assert (
        writer.patch(
            f"{base(shop)}documents/{document.pk}/", {"title": "Diplom"}, format="multipart"
        ).json()["title"]
        == "Diplom"
    )
    assert writer.delete(f"{base(shop)}documents/{document.pk}/").status_code == 204
    assert not EmployeeDocument.objects.filter(pk=document.pk).exists()


def test_changing_whats_on_it_needs_a_new_check(shop, staff, owner_api):
    document = doc(staff.ali, kind="medical_book", expires_on=DAY + timedelta(days=5))
    services.verify_document(document, by=staff.owner)
    document.refresh_from_db()
    document.expiry_notified = [30, 7]
    document.save()

    response = owner_api(staff.owner).patch(
        f"{base(shop)}documents/{document.pk}/", {"expires_on": "2027-10-20"}, format="multipart"
    )

    assert response.json()["verified"] is False
    document.refresh_from_db()
    assert document.expiry_notified == []


def test_filters_by_state_and_expiry(shop, staff, owner_api):
    expired = doc(staff.ali, kind="medical_book", expires_on=DAY - timedelta(days=3))
    soon = doc(staff.vali, kind="medical_book", expires_on=DAY + timedelta(days=12))
    later = doc(staff.sara, kind="medical_book", expires_on=DAY + timedelta(days=200))
    forever = doc(staff.sara, kind="diploma")
    client = owner_api(staff.owner)

    def ids(query):
        return {
            row["id"] for row in client.get(f"{base(shop)}documents/?{query}").json()["results"]
        }

    assert ids("state=expired") == {expired.pk}
    assert ids("state=expiring") == {soon.pk}
    assert ids("state=valid") == {later.pk}
    assert ids("state=no_expiry") == {forever.pk}
    assert ids("expiring_within=30") == {expired.pk, soon.pk}
    assert ids("kind=diploma") == {forever.pk}
    assert ids(f"member={staff.sara.pk}") == {later.pk, forever.pk}
    assert ids("q=Vali") == {soon.pk, expired.pk}  # Vali Aliyev and Ali Valiyev


def test_a_renewed_document_replaces_the_old_one_in_warnings(shop, staff):
    old = doc(staff.ali, kind="medical_book", expires_on=DAY + timedelta(days=4))
    rows = queries.expiring_documents(shop, branch_ids=None, day=DAY, within=30)
    assert list(rows) == [old]

    doc(staff.ali, kind="medical_book", expires_on=DAY + timedelta(days=365))

    assert list(queries.expiring_documents(shop, branch_ids=None, day=DAY, within=30)) == []


# Required documents and compliance ---------------------------------------------------------


def test_required_documents_crud(shop, staff, owner_api):
    client = owner_api(staff.accountant)
    path = f"{base(shop)}required-documents/"

    everyone = client.post(path, {"kind": "medical_book"}, format="json")
    pharmacists = client.post(
        path,
        {
            "kind": "pharmacy_diploma",
            "position_id": staff.pharmacist.pk,
            "alternatives": ["medical_diploma"],
        },
        format="json",
    )
    twice = client.post(path, {"kind": "medical_book"}, format="json")

    assert everyone.status_code == pharmacists.status_code == 201
    assert pharmacists.json()["position"] == {"id": staff.pharmacist.pk, "name": "Pharmacist"}
    assert twice.status_code == 400
    assert owner_api(staff.manager).post(path, {"kind": "nda"}, format="json").status_code == 403
    assert len(owner_api(staff.manager).get(path).json()) == 2
    row = pharmacists.json()["id"]
    changed = client.patch(f"{path}{row}/", {"level": "higher"}, format="json")
    assert changed.json()["level"] == "higher"
    assert changed.json()["alternatives"] == ["medical_diploma"]
    assert client.delete(f"{path}{row}/").status_code == 204
    assert RequiredDocument.objects.count() == 1


def test_the_compliance_matrix_says_who_lacks_what(shop, staff, owner_api):
    RequiredDocument.objects.create(company=shop, kind="medical_book")
    RequiredDocument.objects.create(
        company=shop,
        kind="pharmacy_diploma",
        position=staff.pharmacist,
        alternatives=["medical_diploma"],
    )
    RequiredDocument.objects.create(
        company=shop, kind="pharmacist_certificate", position=staff.pharmacist
    )
    verified = doc(staff.ali, kind="medical_book", expires_on=DAY + timedelta(days=200))
    services.verify_document(verified, by=staff.owner)
    doc(staff.ali, kind="medical_diploma", level="higher")
    doc(staff.ali, kind="pharmacist_certificate", expires_on=DAY - timedelta(days=1))
    doc(staff.vali, kind="medical_book", expires_on=DAY + timedelta(days=10))

    body = owner_api(staff.manager).get(f"{base(shop)}documents/compliance/").json()

    assert body["kinds"] == ["pharmacy_diploma", "pharmacist_certificate", "medical_book"]
    rows = {row["member"]["name"]: row for row in body["rows"]}
    ali = {item["kind"]: item["status"] for item in rows["Ali Valiyev"]["items"]}
    assert ali == {
        "medical_book": "ok",
        "pharmacy_diploma": "unverified",  # the medical diploma is an alternative
        "pharmacist_certificate": "expired",
    }
    vali = {item["kind"]: item["status"] for item in rows["Vali Aliyev"]["items"]}
    assert vali["medical_book"] == "expiring" and vali["pharmacy_diploma"] == "missing"
    assert rows["Dilnoza Karimova"]["items"] == [
        {
            "kind": "medical_book",
            "status": "missing",
            "document_id": None,
            "expires_on": None,
            "level": "",
        }
    ]
    assert rows["Ali Valiyev"]["complete"] is False and rows["Ali Valiyev"]["missing"] == 1
    assert body["totals"]["people"] == 7
    # A position filter, and the branch scope.
    only = (
        owner_api(staff.owner)
        .get(f"{base(shop)}documents/compliance/?position={staff.pharmacist.pk}")
        .json()
    )
    assert {row["member"]["name"] for row in only["rows"]} == {
        "Ali Valiyev",
        "Vali Aliyev",
        "Sara Tosheva",
    }
    lead = owner_api(staff.lead).get(f"{base(shop)}documents/compliance/").json()
    assert "Sara Tosheva" not in {row["member"]["name"] for row in lead["rows"]}


def test_a_level_asked_for_is_met_by_a_higher_one(shop, staff):
    required = RequiredDocument.objects.create(
        company=shop, kind="pharmacy_diploma", level="college"
    )
    higher = doc(staff.ali, kind="pharmacy_diploma", level="higher")
    college = doc(staff.vali, kind="pharmacy_diploma", level="college")

    assert queries.satisfies(higher, required) and queries.satisfies(college, required)
    required.level = "higher"
    assert queries.satisfies(higher, required) and not queries.satisfies(college, required)


# The person's own documents ---------------------------------------------------------------


def test_people_upload_and_read_their_own_documents(shop, staff, api_as):
    hidden = doc(staff.ali, kind="other", visible_to_employee=False)
    theirs = doc(staff.vali, kind="diploma")
    client = api_as(staff.ali)
    path = f"/api/v1/companies/{shop.pk}/hr/documents/"

    created = client.post(
        path,
        {"kind": "medical_book", "expires_on": "2027-10-01", "file": pdf_upload()},
        format="multipart",
    )

    assert created.status_code == 201, created.content
    assert created.json()["verified"] is False
    listed = [row["id"] for row in client.get(path).json()]
    assert listed == [created.json()["id"]]
    assert hidden.pk not in listed and theirs.pk not in listed
    assert client.get(created.json()["file"]).status_code == 200
    document = EmployeeDocument.objects.get(pk=created.json()["id"])
    assert document.uploaded_by == staff.ali.user and document.visible_to_employee


def test_a_suspended_person_still_opens_their_own_documents(shop, staff, api_as):
    services.add_document(staff.ali, by=staff.owner, kind="diploma", file=pdf_upload())
    link = api_as(staff.ali).get(f"/api/v1/companies/{shop.pk}/hr/documents/").json()[0]["file"]
    members.suspend(staff.ali, by=staff.owner, until=None, reason="Investigation")
    client = api_as(Membership.objects.get(pk=staff.ali.pk))

    assert client.get(link).status_code == 200
    response = client.post(
        f"/api/v1/companies/{shop.pk}/hr/documents/",
        {"kind": "diploma", "file": pdf_upload()},
        format="multipart",
    )
    assert response.status_code == 403
