"""The owner endpoints of hiring (rule 21): company and branch scope, `hr.hiring`, the module
switch, audit on every change, the shapes the dashboard reads, and no Telegram id leaving."""

import pytest

from apps.audit.models import AuditLog
from apps.core.files import signed_url
from apps.hr.hiring import services
from apps.hr.models import Applicant, Vacancy
from apps.hr.tests.hiring.conftest import QUESTIONS, jpeg
from apps.members.models import Membership

pytestmark = pytest.mark.django_db


def url(company, rest: str) -> str:
    return f"/api/v1/owner/companies/{company.pk}/hr/{rest}"


@pytest.fixture
def bot_username(settings):
    settings.EMPLOYEE_BOT_USERNAME = "daybook_bot"


def test_vacancies_list_working_ones_first_with_counts(
    shop, hirers, vacancy, applicant, owner_api, bot_username
):
    closed = services.set_status(vacancy(title="Kuryer"), "closed", by=hirers.owner)
    draft = vacancy(title="Omborchi", publish=False)
    opening = vacancy(salary_from=3_000_000, salary_to=4_500_000)
    applicant(opening, 9001)
    second = applicant(opening, 9002, name="Sanjar Qosimov")
    services.move(second, "interview", by=hirers.owner, notify=False)

    response = owner_api(hirers.owner).get(url(shop, "vacancies/"))
    assert response.status_code == 200
    rows = response.json()["results"]
    assert [row["id"] for row in rows] == [opening.pk, draft.pk, closed.pk]
    first = rows[0]
    assert first["status"] == "open" and first["accepting"] is True
    assert first["counts"] == {
        "new": 1,
        "screening": 0,
        "interview": 1,
        "offer": 0,
        "hired": 0,
        "rejected": 0,
        "total": 2,
    }
    assert first["salary_from"] == "3000000.00" and first["currency"] == "UZS"
    assert first["link"] == f"https://t.me/daybook_bot?start=job_{opening.code}"
    assert first["qr_link"].endswith(f"job_{opening.code}-q")
    assert first["position"] == {"id": hirers.pharmacist.pk, "name": "Pharmacist"}
    assert first["branch"]["name"] == "Chilonzor" and first["role"]["name"] == "Employee"
    assert [q["kind"] for q in first["questions"]] == ["yes_no", "choice", "number"]
    assert first["hire_blocker"] is None
    only_drafts = owner_api(hirers.owner).get(url(shop, "vacancies/?status=draft"))
    assert [row["id"] for row in only_drafts.json()["results"]] == [draft.pk]


def test_create_edit_open_pause_close_delete(shop, hirers, owner_api, chilonzor):
    client = owner_api(hirers.manager)
    body = {
        "title": "Farmatsevt",
        "position_id": hirers.pharmacist.pk,
        "branch_id": chilonzor.pk,
        "description": "Chilonzor filialiga tajribali farmatsevt kerak.",
        "salary_from": "4000000",
        "questions": QUESTIONS,
        "asks_document": True,
    }
    created = client.post(url(shop, "vacancies/"), body, format="json")
    assert created.status_code == 201, created.json()
    data = created.json()
    assert data["status"] == "draft" and data["asks_document"] is True
    assert data["created_by"]["id"] == hirers.manager.pk
    vid = data["id"]

    changed = client.patch(
        url(shop, f"vacancies/{vid}/"), {"title": "Katta farmatsevt"}, format="json"
    )
    assert changed.status_code == 200 and changed.json()["title"] == "Katta farmatsevt"
    for verb, status in (("open", "open"), ("pause", "paused"), ("open", "open")):
        answer = client.post(url(shop, f"vacancies/{vid}/{verb}/"))
        assert answer.status_code == 200 and answer.json()["status"] == status
    assert client.post(url(shop, f"vacancies/{vid}/close/")).json()["status"] == "closed"
    assert client.delete(url(shop, f"vacancies/{vid}/")).status_code == 204
    assert not Vacancy.objects.filter(pk=vid).exists()
    assert list(
        AuditLog.objects.filter(target_type="vacancy", target_id=vid)
        .order_by("pk")
        .values_list("action", flat=True)
    ) == [
        "hr.vacancy_created",
        "hr.vacancy_changed",
        "hr.vacancy_opened",
        "hr.vacancy_paused",
        "hr.vacancy_opened",
        "hr.vacancy_closed",
        "hr.vacancy_deleted",
    ]


def test_publishing_at_once_and_bad_bodies(shop, hirers, owner_api, chilonzor):
    client = owner_api(hirers.owner)
    made = client.post(
        url(shop, "vacancies/"),
        {"title": "Kassir", "branch_id": chilonzor.pk, "publish": True},
        format="json",
    )
    assert made.status_code == 201 and made.json()["status"] == "open"
    choice = {"text": "Smena?", "kind": "choice", "options": ["Kunduzgi"]}
    bad = client.post(
        url(shop, "vacancies/"),
        {"title": "Kassir", "branch_id": chilonzor.pk, "questions": [choice]},
        format="json",
    )
    assert bad.status_code == 400 and "two options" in bad.json()["detail"]
    missing = client.post(url(shop, "vacancies/"), {"branch_id": chilonzor.pk}, format="json")
    assert missing.status_code == 400 and "title" in missing.json()
    foreign = client.post(
        url(shop, "vacancies/"), {"title": "Kassir", "position_id": 999999}, format="json"
    )
    assert foreign.status_code == 404


def test_the_qr_code_is_a_png(shop, hirers, vacancy, owner_api, settings):
    opening = vacancy()
    client = owner_api(hirers.owner)
    settings.EMPLOYEE_BOT_USERNAME = ""
    assert client.get(url(shop, f"vacancies/{opening.pk}/qr/")).status_code == 404
    settings.EMPLOYEE_BOT_USERNAME = "daybook_bot"
    response = client.get(url(shop, f"vacancies/{opening.pk}/qr/"))
    assert response.status_code == 200 and response["Content-Type"] == "image/png"
    assert (
        response.content.startswith(b"\x89PNG") and "farmatsevt" in response["Content-Disposition"]
    )


def test_applicants_with_filters_and_their_history(shop, hirers, vacancy, applicant, owner_api):
    opening = vacancy(asks_document=True)
    first = applicant(opening, 9101, name="Elena Kim")
    second = applicant(opening, 9102, name="Sanjar Qosimov", source="qr")
    services.move(second, "screening", by=hirers.manager, message="Ertaga qo‘ng‘iroq qilamiz")
    services.add_note(second, by=hirers.owner, text="Yaxshi taassurot")
    client = owner_api(hirers.owner)

    listed = client.get(url(shop, f"applicants/?vacancy={opening.pk}")).json()
    assert listed["count"] == 2 and [row["id"] for row in listed["results"]] == [
        second.pk,
        first.pk,
    ]
    row = listed["results"][0]
    assert row["vacancy"] == {"id": opening.pk, "name": "Farmatsevt"}
    assert row["stage"] == "screening" and row["source"] == "qr"
    assert row["telegram_username"] == "user9102" and row["has_document"] is False
    assert "telegram_id" not in str(listed) and "9102" not in {str(v) for v in row.values()}
    assert client.get(url(shop, "applicants/?stage=new")).json()["count"] == 1
    assert client.get(url(shop, "applicants/?source=qr")).json()["count"] == 1
    assert client.get(url(shop, "applicants/?q=kim")).json()["count"] == 1

    detail = client.get(url(shop, f"applicants/{second.pk}/")).json()
    assert detail["document"] is None
    assert [event["kind"] for event in detail["events"]] == ["applied", "moved", "note"]
    moved = detail["events"][1]
    assert (moved["from_stage"], moved["to_stage"]) == ("new", "screening")
    assert moved["by"]["id"] == hirers.manager.pk and moved["notified"] is True
    assert moved["message"] == "Ertaga qo‘ng‘iroq qilamiz"
    assert detail["events"][2]["text"] == "Yaxshi taassurot"


def test_move_reject_hire_and_notes(shop, hirers, vacancy, applicant, owner_api, chilonzor):
    opening = vacancy()
    first = applicant(opening, 9201)
    second = applicant(opening, 9202, name="Nilufar Sobirova")
    client = owner_api(hirers.owner)

    moved = client.post(
        url(shop, f"applicants/{first.pk}/move/"), {"stage": "interview"}, format="json"
    )
    assert moved.status_code == 200 and moved.json()["stage"] == "interview"
    wrong = client.post(
        url(shop, f"applicants/{first.pk}/move/"), {"stage": "hired"}, format="json"
    )
    assert wrong.status_code == 400

    noted = client.post(
        url(shop, f"applicants/{first.pk}/notes/"), {"text": "Keldi"}, format="json"
    )
    assert noted.status_code == 201 and noted.json()["events"][-1]["text"] == "Keldi"

    no_reason = client.post(url(shop, f"applicants/{second.pk}/reject/"), {}, format="json")
    assert no_reason.status_code == 400
    rejected = client.post(
        url(shop, f"applicants/{second.pk}/reject/"),
        {"reason": "Tajriba kam", "notify": False},
        format="json",
    )
    assert rejected.status_code == 200 and rejected.json()["rejected_reason"] == "Tajriba kam"

    hired = client.post(url(shop, f"applicants/{first.pk}/hire/"), {}, format="json")
    assert hired.status_code == 200, hired.json()
    member = Membership.objects.get(pk=hired.json()["member"]["id"])
    assert member.status == Membership.Status.APPROVED and member.home_branch == chilonzor
    again = client.post(url(shop, f"applicants/{first.pk}/hire/"), {}, format="json")
    assert again.status_code == 400 and "already hired" in again.json()["detail"]
    assert Membership.objects.filter(user=first.user, company=shop).count() == 1


def test_hiring_without_the_right_to_let_people_in_is_403(
    shop, hirers, vacancy, applicant, owner_api
):
    made = applicant(vacancy(), 9301)
    answer = owner_api(hirers.recruiter).post(url(shop, f"applicants/{made.pk}/hire/"), {})
    assert answer.status_code == 403 and "approve join requests" in answer.json()["detail"]
    detail = owner_api(hirers.recruiter).get(url(shop, "vacancies/")).json()["results"][0]
    assert "approve join requests" in detail["hire_blocker"]


def test_without_hr_hiring_everything_is_403(shop, hirers, vacancy, applicant, owner_api):
    made = applicant(vacancy(), 9401)
    client = owner_api(hirers.accountant)
    for method, path in (
        ("get", "vacancies/"),
        ("post", "vacancies/"),
        ("get", f"vacancies/{made.vacancy_id}/qr/"),
        ("get", "applicants/"),
        ("get", f"applicants/{made.pk}/"),
        ("post", f"applicants/{made.pk}/move/"),
        ("post", f"applicants/{made.pk}/hire/"),
    ):
        assert getattr(client, method)(url(shop, path)).status_code == 403, path


def test_another_companys_ids_are_404(shop, hirers, vacancy, applicant, owner_api, outsider):
    made = applicant(vacancy(), 9501)
    theirs = owner_api(outsider)
    company = outsider.company
    for method, path in (
        ("get", f"vacancies/{made.vacancy_id}/"),
        ("patch", f"vacancies/{made.vacancy_id}/"),
        ("post", f"vacancies/{made.vacancy_id}/close/"),
        ("get", f"applicants/{made.pk}/"),
        ("post", f"applicants/{made.pk}/hire/"),
    ):
        assert getattr(theirs, method)(url(company, path)).status_code == 404, path
    # And our own URL with their token: not a member here.
    assert theirs.get(url(shop, "vacancies/")).status_code == 404


def test_a_branch_hirer_sees_only_their_branches(
    shop, hirers, vacancy, applicant, owner_api, yunusobod
):
    near = applicant(vacancy(), 9601)
    far = applicant(vacancy(branch=yunusobod, title="Kassir"), 9602)
    whole = vacancy(branch=None, title="Kuryer")
    client = owner_api(hirers.scout)
    listed = client.get(url(shop, "vacancies/")).json()["results"]
    assert [row["id"] for row in listed] == [near.vacancy_id]
    assert client.get(url(shop, f"vacancies/{far.vacancy_id}/")).status_code == 404
    assert client.get(url(shop, f"vacancies/{whole.pk}/")).status_code == 404
    assert client.get(url(shop, f"applicants/{far.pk}/")).status_code == 404
    assert [row["id"] for row in client.get(url(shop, "applicants/")).json()["results"]] == [
        near.pk
    ]
    assert (
        client.post(url(shop, f"applicants/{far.pk}/move/"), {"stage": "offer"}).status_code == 404
    )
    other_branch = client.post(
        url(shop, "vacancies/"), {"title": "Kassir", "branch_id": yunusobod.pk}, format="json"
    )
    assert other_branch.status_code == 403


def test_hr_switched_off_is_403(shop, hirers, owner_api):
    shop.features = []
    shop.save(update_fields=["features"])
    assert owner_api(hirers.owner).get(url(shop, "vacancies/")).status_code == 403


def test_the_diploma_photo_opens_through_a_signed_link(shop, hirers, vacancy, applicant, owner_api):
    made = applicant(vacancy(asks_document=True), 9701, document=jpeg())
    client = owner_api(hirers.owner)
    link = client.get(url(shop, f"applicants/{made.pk}/")).json()["document"]
    assert link.startswith("/api/v1/files/")
    opened = client.get(link)
    assert opened.status_code == 200 and opened["Content-Type"] == "image/jpeg"
    # A link made for someone without hr.hiring opens nothing.
    theirs = signed_url(
        made.document,
        user=hirers.accountant.user,
        company_id=shop.pk,
        check=f"hr.applicant:{made.pk}",
    )
    assert owner_api(hirers.accountant).get(theirs).status_code == 404


def test_the_pulse_counts_new_applicants_in_scope(shop, hirers, vacancy, applicant, owner_api):
    applicant(vacancy(), 9801)
    pulse = owner_api(hirers.owner).get(f"/api/v1/owner/companies/{shop.pk}/pulse/").json()
    assert pulse["counters"]["hr.applicants"] == 1
    assert Applicant.objects.count() == 1
