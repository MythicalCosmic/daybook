"""Contracts and their templates: one in force per person, fixed-term needs an end, the
lifecycle actions, probation, the PDF from a template (placeholders filled, the pay only for
payroll.view), the person's own contract and "I've read it", and the fixed services other
apps call (`hr.contracts`, `hr.queries.org`)."""

import inspect
from datetime import date, timedelta

import pytest

from apps.audit.models import AuditLog
from apps.hr import contracts, printing, queries, services
from apps.hr.models import Contract, ContractTemplate
from apps.hr.tests.conftest import DAY, pdf_upload
from apps.inbox.models import Notification
from apps.members import departments
from apps.members import services as members
from apps.members.models import Membership

pytestmark = pytest.mark.django_db

BODY = (
    "<h1>Mehnat shartnomasi</h1><p>{{company_name}} (STIR {{company_tin}}) va "
    "{{employee_full_name}}, lavozimi: {{position}}, filial: {{branch}}.</p>"
    "<p>Boshlanishi: {{starts_on}}. Tugashi: {{ends_on}}. Sinov: {{probation_until}}.</p>"
    "<p>Haftasiga {{weekly_hours}} soat. Ish haqi: {{salary_text}}. Sana: {{today}}.</p>"
)


def base(company) -> str:
    return f"/api/v1/owner/companies/{company.pk}/hr/"


def template(company, **fields) -> ContractTemplate:
    fields.setdefault("name", "Mehnat shartnomasi")
    return ContractTemplate.objects.create(company=company, body=BODY, **fields)


def draft(member, by, **fields) -> Contract:
    fields.setdefault("starts_on", DAY)
    return services.create_contract(member, by=by, **fields)


def signed(member, by, **fields) -> Contract:
    return services.activate_contract(draft(member, by, **fields), by=by)


@pytest.fixture
def no_salary(monkeypatch):
    monkeypatch.setattr("apps.hr.integrations.salary_text", lambda *args: "")


@pytest.fixture
def salary(monkeypatch):
    """Payroll knows the pay (package H isn't on this branch: its reading is patched)."""
    monkeypatch.setattr(
        "apps.hr.integrations.salary_text", lambda membership, day, language: "5 200 000 so‘m"
    )


# Drawing up and signing -------------------------------------------------------------------


def test_hr_draws_up_and_signs_a_contract(
    shop, staff, owner_api, django_capture_on_commit_callbacks
):
    client = owner_api(staff.accountant)

    created = client.post(
        f"{base(shop)}contracts/",
        {
            "member_id": staff.ali.pk,
            "kind": "fixed_term",
            "starts_on": "2026-10-21",
            "ends_on": "2027-10-20",
            "probation_until": "2027-01-20",
            "weekly_hours": "40",
        },
        format="json",
    )

    assert created.status_code == 201, created.content
    body = created.json()
    assert body["status"] == "draft" and body["number"] == "2026-001"
    assert body["position"] == {"id": staff.pharmacist.pk, "name": "Pharmacist"}
    assert body["actions"]["activate"] and not body["actions"]["terminate"]
    with django_capture_on_commit_callbacks(execute=True):
        signed_now = client.post(f"{base(shop)}contracts/{body['id']}/activate/")
    assert signed_now.status_code == 200
    assert signed_now.json()["status"] == "active"
    assert signed_now.json()["on_probation"] is True
    assert signed_now.json()["days_left"] == 364
    assert contracts.active_contract(staff.ali).pk == body["id"]
    # The person hears their contract is in force, with a way into the app.
    notice = Notification.objects.get(recipient=staff.ali, kind="hr.contract")
    assert notice.app_screen == "hr.contract" and "2026-001" in notice.body
    assert AuditLog.objects.filter(action="hr.contract_activated", target_id=staff.ali.pk).exists()


def test_a_fixed_term_contract_needs_an_end(shop, staff, owner_api):
    response = owner_api(staff.owner).post(
        f"{base(shop)}contracts/",
        {"member_id": staff.ali.pk, "kind": "fixed_term", "starts_on": "2026-10-21"},
        format="json",
    )

    assert response.status_code == 400
    assert not Contract.objects.exists()


@pytest.mark.parametrize(
    "fields",
    [
        {"ends_on": "2026-10-01"},  # before the start
        {"probation_until": "2026-10-01"},
        {"ends_on": "2026-12-31", "probation_until": "2027-01-31"},  # past the end
    ],
)
def test_contract_dates_must_hang_together(shop, staff, owner_api, fields):
    response = owner_api(staff.owner).post(
        f"{base(shop)}contracts/",
        {"member_id": staff.ali.pk, "starts_on": "2026-10-21", **fields},
        format="json",
    )

    assert response.status_code == 400


def test_one_contract_in_force_per_person(shop, staff):
    signed(staff.ali, staff.owner)
    second = draft(staff.ali, staff.owner, starts_on=DAY + timedelta(days=1))

    with pytest.raises(services.DomainError):
        services.activate_contract(second, by=staff.owner)
    assert Contract.objects.filter(membership=staff.ali, status="active").count() == 1


def test_hr_view_reads_hr_manage_acts(shop, staff, owner_api):
    contract = draft(staff.ali, staff.owner)
    reader = owner_api(staff.manager)

    assert reader.get(f"{base(shop)}contracts/").json()["count"] == 1
    assert (
        reader.get(f"{base(shop)}contracts/{contract.pk}/").json()["actions"]["activate"] is False
    )
    for verb in ("activate", "terminate", "end", "renew", "pass-probation", "generate-pdf"):
        assert reader.post(f"{base(shop)}contracts/{contract.pk}/{verb}/").status_code == 403
    assert (
        reader.post(
            f"{base(shop)}contracts/", {"member_id": staff.ali.pk, "starts_on": "2026-10-21"}
        ).status_code
        == 403
    )
    assert reader.delete(f"{base(shop)}contracts/{contract.pk}/").status_code == 403
    assert (
        owner_api(staff.accountant).delete(f"{base(shop)}contracts/{contract.pk}/").status_code
        == 204
    )


def test_scope_and_other_companies(shop, staff, owner_api, outsider):
    mine = draft(staff.ali, staff.owner)
    yunusobod = draft(staff.sara, staff.owner)
    theirs = draft(outsider, outsider)

    lead = owner_api(staff.lead)
    assert [row["id"] for row in lead.get(f"{base(shop)}contracts/").json()["results"]] == [mine.pk]
    assert lead.post(f"{base(shop)}contracts/{yunusobod.pk}/activate/").status_code == 404
    owner = owner_api(staff.owner)
    assert owner.get(f"{base(shop)}contracts/{theirs.pk}/").status_code == 404
    assert (
        owner.post(
            f"{base(shop)}contracts/",
            {"member_id": outsider.pk, "starts_on": "2026-10-21"},
            format="json",
        ).status_code
        == 404
    )


def test_a_signed_contracts_terms_change_only_by_an_amendment(shop, staff, owner_api):
    contract = signed(staff.ali, staff.owner, kind="fixed_term", ends_on=DAY + timedelta(200))
    client = owner_api(staff.owner)

    refused = client.patch(
        f"{base(shop)}contracts/{contract.pk}/", {"ends_on": "2027-12-31"}, format="json"
    )
    noted = client.patch(
        f"{base(shop)}contracts/{contract.pk}/", {"note": "Asl nusxa seyfda"}, format="json"
    )

    assert refused.status_code == 400
    assert noted.status_code == 200 and noted.json()["note"] == "Asl nusxa seyfda"
    assert client.delete(f"{base(shop)}contracts/{contract.pk}/").status_code == 400


# Ending, terminating, renewing --------------------------------------------------------------


def test_terminating_needs_a_reason_and_a_day_not_in_the_future(shop, staff, owner_api):
    contract = signed(staff.ali, staff.owner, starts_on=DAY - timedelta(days=100))
    path = f"{base(shop)}contracts/{contract.pk}/terminate/"
    client = owner_api(staff.owner)

    assert client.post(path, {"terminated_on": "2026-10-21"}, format="json").status_code == 400
    future = {"terminated_on": "2026-11-01", "reason": "Kelishuv"}
    assert client.post(path, future, format="json").status_code == 400
    done = client.post(path, {"terminated_on": "2026-10-20", "reason": "Kelishuv"}, format="json")

    assert done.status_code == 200
    assert done.json()["status"] == "terminated"
    assert done.json()["terminated_on"] == "2026-10-20"
    assert contracts.active_contract(staff.ali) is None


def test_renewing_a_fixed_term_contract_carries_on_the_next_day(shop, staff, owner_api):
    old = signed(
        staff.ali,
        staff.owner,
        kind="fixed_term",
        starts_on=date(2025, 10, 21),
        ends_on=date(2026, 10, 31),
        weekly_hours="40",
    )

    response = owner_api(staff.owner).post(
        f"{base(shop)}contracts/{old.pk}/renew/", {"ends_on": "2027-10-31"}, format="json"
    )

    assert response.status_code == 201, response.content
    renewed = response.json()
    assert renewed["status"] == "active" and renewed["starts_on"] == "2026-11-01"
    assert renewed["weekly_hours"] == "40.0" and renewed["number"] == "2026-001"
    old.refresh_from_db()
    assert old.status == "ended" and old.terminated_on == date(2026, 10, 31)
    assert contracts.active_contract(staff.ali).pk == renewed["id"]


def test_an_indefinite_contract_isnt_renewed(shop, staff):
    contract = signed(staff.ali, staff.owner)

    with pytest.raises(services.DomainError):
        services.renew_contract(contract, by=staff.owner, ends_on=date(2027, 1, 1))


def test_hr_contracts_end_and_amend_keep_their_signatures(shop, staff):
    assert (
        str(inspect.signature(contracts.active_contract))
        == "(membership) -> apps.hr.models.Contract | None"
    )
    amend = inspect.signature(contracts.amend)
    assert list(amend.parameters) == ["contract", "by", "effective_on", "changes", "reason"]
    assert list(inspect.signature(contracts.end).parameters) == [
        "contract",
        "by",
        "ended_on",
        "reason",
    ]

    contract = signed(staff.ali, staff.owner, starts_on=DAY - timedelta(days=30))
    amended = contracts.amend(
        contract,
        by=None,
        effective_on=DAY,
        changes={"weekly_hours": 36, "position": staff.office},
        reason="Ofisga o‘tdi",
    )
    assert amended.weekly_hours == 36 and amended.position == staff.office
    row = AuditLog.objects.get(action="hr.contract_amended")
    assert row.details["changes"]["position"] == ["Pharmacist", "Office"]
    with pytest.raises(services.DomainError):
        contracts.amend(contract, by=None, effective_on=DAY, changes={"number": "X"}, reason="x")

    ended = contracts.end(contract, by=None, ended_on=DAY, reason="Muddati tugadi")
    assert ended.status == "ended" and ended.terminated_on == DAY


def test_leaving_ends_the_contract_in_force(shop, staff, django_capture_on_commit_callbacks):
    first = signed(staff.ali, staff.owner, starts_on=DAY - timedelta(days=300))
    second = signed(
        staff.vali,
        staff.owner,
        kind="fixed_term",
        starts_on=DAY - timedelta(days=60),
        ends_on=DAY,
    )
    with django_capture_on_commit_callbacks(execute=True):
        members.offboard(staff.ali, by=staff.owner.user, terminated_on=DAY - timedelta(days=1))
        members.complete_offboarding(
            staff.vali,
            by=staff.owner,
            terminated_on=DAY,
            reason="contract_end",
            override_blockers=True,
        )

    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.status, first.terminated_on) == ("terminated", DAY - timedelta(days=1))
    assert (second.status, second.terminated_on) == ("ended", DAY)


# Probation ------------------------------------------------------------------------------------


def test_passing_and_extending_probation(shop, staff, owner_api):
    contract = signed(
        staff.ali,
        staff.owner,
        kind="fixed_term",
        starts_on=DAY - timedelta(days=80),
        ends_on=DAY + timedelta(days=200),
        probation_until=DAY + timedelta(days=5),
    )
    client = owner_api(staff.accountant)
    path = f"{base(shop)}contracts/{contract.pk}/"

    assert client.post(f"{path}extend-probation/", {"until": "2026-10-25"}).status_code == 400
    assert client.post(f"{path}extend-probation/", {"until": "2027-12-01"}).status_code == 400
    extended = client.post(f"{path}extend-probation/", {"until": "2026-11-26"})
    assert extended.status_code == 200 and extended.json()["probation_until"] == "2026-11-26"
    passed = client.post(f"{path}pass-probation/")
    assert passed.status_code == 200 and passed.json()["on_probation"] is False
    assert passed.json()["actions"]["pass_probation"] is False
    assert client.post(f"{path}pass-probation/").status_code == 400


# Templates and the PDF --------------------------------------------------------------------------


def test_templates_are_cleaned_and_only_know_the_fixed_placeholders(shop, staff, owner_api):
    client = owner_api(staff.accountant)
    path = f"{base(shop)}contract-templates/"

    saved = client.post(
        path,
        {
            "name": "Shartnoma",
            "body": '<p onclick="x()">Salom {{employee_full_name}}</p><script>bad()</script>',
        },
        format="json",
    )
    unknown = client.post(
        path, {"name": "Boshqa", "body": "<p>{{employee_salary}}</p>"}, format="json"
    )

    assert saved.status_code == 201, saved.content
    assert saved.json()["body"] == "<p>Salom {{employee_full_name}}</p>"
    assert unknown.status_code == 400 and "employee_salary" in str(unknown.json())
    assert client.get(f"{path}placeholders/").json()["placeholders"] == list(printing.PLACEHOLDERS)
    assert owner_api(staff.manager).get(path).status_code == 403  # templates are hr.manage


def test_the_preview_fills_in_a_chosen_person(shop, staff, owner_api, salary):
    services.update_profile(staff.ali, by=staff.owner, middle_name="Karimovich")
    services.update_settings(
        shop, by=staff.owner, employer_name="«Demo Dorixona» MChJ", employer_tin="305123456"
    )
    row = template(shop)
    signed(
        staff.ali,
        staff.owner,
        kind="fixed_term",
        ends_on=date(2027, 10, 20),
        probation_until=date(2027, 1, 20),
        weekly_hours="40",
    )

    as_owner = (
        owner_api(staff.owner)
        .post(f"{base(shop)}contract-templates/{row.pk}/preview/", {"member_id": staff.ali.pk})
        .json()
    )
    as_accountant_without_pay = owner_api(staff.lead).post(
        f"{base(shop)}contract-templates/{row.pk}/preview/", {"member_id": staff.ali.pk}
    )

    html = as_owner["html"]
    assert "«Demo Dorixona» MChJ (STIR 305123456)" in html
    assert "Valiyev Ali Karimovich" in html
    assert "lavozimi: Pharmacist, filial: Chilonzor" in html
    assert "Boshlanishi: 2026-yil 21-oktabr. Tugashi: 2027-yil 20-oktabr." in html
    assert "Sinov: 2027-yil 20-yanvar" in html and "Haftasiga 40 soat" in html
    assert "Ish haqi: 5 200 000 so‘m" in html and as_owner["has_salary"] is True
    # Someone without payroll.view gets a line to fill in by hand instead of the pay.
    lead = as_accountant_without_pay.json()
    assert "5 200 000" not in lead["html"] and printing.BLANK in lead["html"]
    assert lead["empty"] == ["salary_text"]


def test_unsaved_text_previews_too(shop, staff, owner_api):
    response = owner_api(staff.owner).post(
        f"{base(shop)}contract-templates/preview/",
        {
            "body": "<p>{{employee_full_name}} <b>{{today}}</b></p>",
            "member_id": staff.sara.pk,
            "language": "uz",
        },
        format="json",
    )
    in_russian = owner_api(staff.owner).post(
        f"{base(shop)}contract-templates/preview/",
        {"body": "<p>{{today}}</p>", "language": "ru"},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["html"] == "<p>Tosheva Sara <b>2026-yil 21-oktabr</b></p>"
    assert in_russian.json()["html"] == "<p>21 октября 2026 г.</p>"


def test_values_are_escaped(shop, staff):
    staff.ali.first_name = "<b>Ali</b>"
    staff.ali.save()
    filled = printing.fill("<p>{{employee_full_name}}</p>", {"employee_full_name": "<b>Ali</b>"})

    assert filled.html == "<p>&lt;b&gt;Ali&lt;/b&gt;</p>"


def test_a_pdf_with_the_pay_opens_only_for_payroll_view(
    shop, staff, owner_api, salary, private_media
):
    row = template(shop)
    contract = signed(staff.ali, staff.owner)

    made = owner_api(staff.owner).post(
        f"{base(shop)}contracts/{contract.pk}/generate-pdf/", {"template_id": row.pk}
    )

    assert made.status_code == 200, made.content
    assert made.json()["template"]["id"] == row.pk and made.json()["file_is_scan"] is False
    contract.refresh_from_db()
    assert contract.file_has_salary is True
    data = (private_media / contract.file.name).read_bytes()
    assert data.startswith(b"%PDF-")
    assert owner_api(staff.owner).get(made.json()["file"]).status_code == 200
    # The manager has hr.view but not payroll.view: no link, and a link made for them fails.
    as_manager = owner_api(staff.manager).get(f"{base(shop)}contracts/{contract.pk}/").json()
    assert as_manager["file"] is None and as_manager["file_hidden"] is True
    assert AuditLog.objects.filter(action="hr.contract_printed").exists()


def test_a_pdf_without_the_pay_opens_for_hr_view(shop, staff, owner_api, no_salary):
    row = template(shop)
    contract = signed(staff.ali, staff.owner)
    services.generate_pdf(contract, by=staff.owner, template=row)

    as_manager = owner_api(staff.manager).get(f"{base(shop)}contracts/{contract.pk}/").json()

    assert as_manager["file"] and as_manager["file_hidden"] is False
    assert owner_api(staff.manager).get(as_manager["file"]).status_code == 200


def test_a_signed_scan_counts_as_stating_the_pay(shop, staff, owner_api):
    contract = signed(staff.ali, staff.owner)

    response = owner_api(staff.owner).patch(
        f"{base(shop)}contracts/{contract.pk}/", {"file": pdf_upload()}, format="multipart"
    )

    assert response.json()["file_is_scan"] is True
    assert (
        owner_api(staff.manager).get(f"{base(shop)}contracts/{contract.pk}/").json()["file"] is None
    )


def test_without_a_template_there_is_no_pdf(shop, staff):
    contract = signed(staff.ali, staff.owner)

    with pytest.raises(services.DomainError):
        services.generate_pdf(contract, by=staff.owner)


# The person's own contract -------------------------------------------------------------------


def test_people_read_and_acknowledge_their_own_contract(shop, staff, api_as, no_salary):
    client = api_as(staff.ali)
    mine = f"/api/v1/companies/{shop.pk}/hr/contract/"
    contract = draft(staff.ali, staff.owner)
    assert client.get(mine).status_code == 404  # a draft isn't theirs to see yet

    services.activate_contract(contract, by=staff.owner)
    services.generate_pdf(contract, by=staff.owner, template=template(shop))
    body = client.get(mine).json()

    assert body["id"] == contract.pk and body["needs_acknowledgement"] is True
    assert client.get(body["file"]).status_code == 200
    assert client.get(f"{mine}pdf/").json()["url"].startswith("/api/v1/files/")
    done = client.post(f"/api/v1/companies/{shop.pk}/hr/contract/{contract.pk}/acknowledge/")
    assert done.status_code == 200 and done.json()["needs_acknowledgement"] is False
    theirs = signed(staff.vali, staff.owner)
    assert (
        client.post(f"/api/v1/companies/{shop.pk}/hr/contract/{theirs.pk}/acknowledge/").status_code
        == 404
    )
    theirs.refresh_from_db()
    assert theirs.acknowledged_at is None


def test_a_suspended_person_reads_their_contract(shop, staff, api_as):
    signed(staff.ali, staff.owner)
    members.suspend(staff.ali, by=staff.owner, until=None, reason="Tekshiruv")
    client = api_as(Membership.objects.get(pk=staff.ali.pk))

    assert client.get(f"/api/v1/companies/{shop.pk}/hr/contract/").status_code == 200


# The org ------------------------------------------------------------------------------------


def test_org_lists_departments_heads_and_managers(shop, staff):
    pharmacy = departments.create_department(shop, by=staff.owner, name="Dorixona")
    departments.update_department(pharmacy, by=staff.owner, head=staff.manager)
    departments.place(pharmacy, by=staff.owner, people=[staff.ali, staff.manager])

    found = queries.org(shop)

    [row] = found["departments"]
    assert (row["name"], row["head_id"], row["headcount"]) == ("Dorixona", staff.manager.pk, 2)
    people = {person["id"]: person for person in found["people"]}
    assert people[staff.ali.pk]["manager_id"] == staff.manager.pk
    assert people[staff.ali.pk]["department_id"] == pharmacy.pk
    assert people[staff.sara.pk]["manager_id"] is None
