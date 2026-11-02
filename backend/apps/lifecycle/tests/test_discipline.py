"""Disciplinary records: who may give them, what the person sees and answers, the fine proposed
through payroll (patched: package H lands on its own branch), withdrawing, and the AI tool."""

import json
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.exceptions import PermissionDenied

from apps.ai.tools.testing import call_tool
from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.hr.tests.conftest import DAY, local, pdf_upload
from apps.inbox.models import Notification
from apps.lifecycle import services
from apps.lifecycle.models import DisciplinaryRecord
from apps.members import services as members
from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db

STORY = "Muzlatgich harorati 12 °C gacha ko‘tarilgan, jurnalga yozilmagan."


def base(company) -> str:
    return f"/api/v1/owner/companies/{company.pk}/lifecycle/"


def give(member, by, **fields) -> DisciplinaryRecord:
    fields.setdefault("kind", "written_warning")
    fields.setdefault("category", "storage_breach")
    fields.setdefault("description", STORY)
    return services.issue(member, by=by, **fields)


@pytest.fixture
def payroll(monkeypatch):
    """payroll.services.propose_fine as package H will provide it (patched here)."""
    calls = []

    def propose_fine(membership, *, by, amount, reason, source):
        calls.append(
            {"member": membership, "by": by, "amount": amount, "reason": reason, "source": source}
        )
        return SimpleNamespace(pk=7001)

    monkeypatch.setattr("apps.payroll.services.propose_fine", propose_fine, raising=False)
    return calls


# Giving a record ----------------------------------------------------------------------------


def test_a_manager_gives_a_written_warning_and_the_person_hears(
    shop, staff, owner_api, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = owner_api(staff.manager).post(
            f"{base(shop)}discipline/",
            {
                "member_id": staff.ali.pk,
                "kind": "written_warning",
                "category": "storage_breach",
                "incident_on": "2026-10-19",
                "description": STORY,
                "evidence": pdf_upload("log.pdf"),
            },
            format="multipart",
        )

    assert response.status_code == 201, response.content
    body = response.json()
    assert body["issued_on"] == "2026-10-21" and body["expires_on"] == "2027-04-21"
    assert body["active"] is True and body["status"] == "issued"
    assert body["issued_by"]["name"] == "Bekzod Mirzayev"
    assert body["evidence"].startswith("/api/v1/files/")
    assert owner_api(staff.accountant).get(body["evidence"]).status_code == 200
    notice = Notification.objects.get(recipient=staff.ali, kind="lifecycle.record")
    assert notice.title == "Written warning"
    assert notice.app_screen == f"lifecycle.record:{body['id']}"
    assert "Storage conditions breached" in notice.body
    row = AuditLog.objects.get(action="lifecycle.record_issued")
    assert row.target_id == staff.ali.pk and row.details["kind"] == "written_warning"
    assert STORY not in json.dumps(row.details, ensure_ascii=False)


@pytest.mark.parametrize(
    ("kind", "expires"),
    [
        ("verbal_warning", date(2027, 1, 21)),
        ("written_warning", date(2027, 4, 21)),
        ("final_warning", date(2027, 10, 21)),
        ("reprimand", date(2027, 10, 21)),
        ("other", None),
    ],
)
def test_each_kind_counts_for_its_own_time(shop, staff, kind, expires):
    assert give(staff.ali, staff.manager, kind=kind).expires_on == expires


def test_who_may_give_a_record(shop, staff, owner_api, outsider):
    path = f"{base(shop)}discipline/"
    payload = {
        "member_id": staff.ali.pk,
        "kind": "verbal_warning",
        "category": "lateness",
        "description": "Uch marta kechikdi",
    }

    assert owner_api(staff.accountant).post(path, payload).status_code == 403  # reads only
    assert owner_api(staff.accountant).get(path).status_code == 200
    assert owner_api(staff.vali).get(path).status_code == 403  # no dashboard
    assert (
        owner_api(staff.manager).post(path, {**payload, "member_id": outsider.pk}).status_code
        == 404
    )
    with pytest.raises(DomainError):
        give(staff.manager, staff.manager)  # not themselves
    with pytest.raises(PermissionDenied):
        give(staff.owner, staff.manager)  # an owner only by an owner
    # Someone who disciplines at Chilonzor only can't reach Yunusobod.
    role = AccessRole.objects.create(
        company=shop,
        name="Chilonzor head",
        permissions=[Perm.DASHBOARD_ACCESS, Perm.HR_DISCIPLINE],
    )
    head = staff.lead
    head.role = role
    head.save()
    assert owner_api(head).post(path, {**payload, "member_id": staff.sara.pk}).status_code == 404
    assert owner_api(head).post(path, payload).status_code == 201
    listed = owner_api(head).get(path).json()["results"]
    assert [row["member"]["name"] for row in listed] == ["Ali Valiyev"]


@pytest.mark.parametrize(
    "fields",
    [
        {"description": " "},
        {"incident_on": date(2026, 11, 1)},
        {"issued_on": date(2026, 10, 20), "incident_on": date(2026, 10, 21)},
        {"kind": "warning"},
        {"category": "stealing"},
        {"expires_on": date(2026, 10, 1)},
    ],
)
def test_a_record_must_make_sense(shop, staff, fields):
    with pytest.raises(DomainError):
        give(staff.ali, staff.manager, **fields)


def test_a_person_who_left_gets_no_record(shop, staff):
    members.offboard(staff.ali, by=staff.owner.user)

    with pytest.raises(DomainError):
        give(Membership.objects.get(pk=staff.ali.pk), staff.manager)


# The fine through payroll -----------------------------------------------------------------------


def test_a_fine_goes_to_payroll_as_a_proposal(shop, staff, owner_api, payroll, monkeypatch):
    response = owner_api(staff.manager).post(
        f"{base(shop)}discipline/",
        {
            "member_id": staff.ali.pk,
            "kind": "written_warning",
            "category": "storage_breach",
            "description": STORY,
            "fine_amount": "200000",
        },
        format="json",
    )

    assert response.status_code == 201, response.content
    assert response.json()["fine_id"] == 7001
    assert payroll == [
        {
            "member": staff.ali,
            "by": staff.manager,
            "amount": Decimal("200000.00"),
            "reason": "Written warning: Storage conditions breached",
            "source": "discipline",
        }
    ]
    # The amount itself only for payroll.view (the manager has none; the owner has).
    monkeypatch.setattr(
        "apps.lifecycle.integrations.fine_summary",
        lambda company, fine_id: {
            "id": fine_id,
            "amount": "200000.00",
            "currency": "UZS",
            "status": "proposed",
        },
    )
    record = response.json()["id"]
    assert owner_api(staff.manager).get(f"{base(shop)}discipline/{record}/").json()["fine"] is None
    owner_view = owner_api(staff.owner).get(f"{base(shop)}discipline/{record}/").json()
    assert owner_view["fine"]["amount"] == "200000.00"
    # One fine per record.
    again = owner_api(staff.manager).post(
        f"{base(shop)}discipline/{record}/fine/", {"amount": "50000"}
    )
    assert again.status_code == 400


def test_without_payroll_the_fine_is_refused_and_nothing_is_given(shop, staff, owner_api):
    response = owner_api(staff.manager).post(
        f"{base(shop)}discipline/",
        {
            "member_id": staff.ali.pk,
            "kind": "written_warning",
            "category": "storage_breach",
            "description": STORY,
            "fine_amount": "200000",
        },
        format="json",
    )

    assert response.status_code == 400
    assert "payroll" in response.json()["detail"].lower()
    assert not DisciplinaryRecord.objects.exists()


def test_a_company_with_payroll_off_gets_no_fine(shop, staff, payroll):
    shop.features = ["hr"]
    shop.save()
    staff.ali.company.refresh_from_db()

    with pytest.raises(DomainError):
        give(staff.ali, staff.manager, fine_amount=Decimal("100000"))
    assert payroll == []


def test_a_fine_can_follow_a_record(shop, staff, owner_api, payroll):
    record = give(staff.ali, staff.manager)

    response = owner_api(staff.manager).post(
        f"{base(shop)}discipline/{record.pk}/fine/", {"amount": "150000"}
    )

    assert response.status_code == 200 and response.json()["fine_id"] == 7001
    assert payroll[0]["amount"] == Decimal("150000.00")


# Changing, withdrawing, removing -----------------------------------------------------------------


def test_withdrawing_keeps_the_record_marked(shop, staff, owner_api):
    record = give(staff.ali, staff.manager)
    path = f"{base(shop)}discipline/{record.pk}/withdraw/"

    assert owner_api(staff.manager).post(path, {}).status_code == 400  # a reason is needed
    done = owner_api(staff.manager).post(path, {"reason": "Xato yozilgan"})

    assert done.status_code == 200
    assert done.json()["status"] == "withdrawn" and done.json()["active"] is False
    active = owner_api(staff.manager).get(f"{base(shop)}discipline/?active=true").json()
    assert active["count"] == 0


def test_changing_the_kind_moves_the_expiry(shop, staff, owner_api):
    record = give(staff.ali, staff.manager, kind="verbal_warning")

    response = owner_api(staff.manager).patch(
        f"{base(shop)}discipline/{record.pk}/", {"kind": "final_warning"}, format="json"
    )

    assert response.json()["expires_on"] == "2027-10-21"


def test_a_record_the_person_has_seen_is_withdrawn_not_removed(shop, staff, owner_api, api_as):
    unseen = give(staff.ali, staff.manager)
    seen = give(staff.vali, staff.manager)
    api_as(staff.vali).get(f"/api/v1/companies/{shop.pk}/lifecycle/records/{seen.pk}/")

    assert (
        owner_api(staff.manager).delete(f"{base(shop)}discipline/{unseen.pk}/").status_code == 204
    )
    assert owner_api(staff.manager).delete(f"{base(shop)}discipline/{seen.pk}/").status_code == 400


def test_filters(shop, staff, owner_api):
    give(staff.ali, staff.manager, kind="verbal_warning", category="lateness")
    give(staff.vali, staff.manager, issued_on=DAY - timedelta(days=40))
    client = owner_api(staff.owner)

    def names(query):
        rows = client.get(f"{base(shop)}discipline/?{query}").json()["results"]
        return [row["member"]["name"] for row in rows]

    assert names("category=lateness") == ["Ali Valiyev"]
    assert names("kind=written_warning") == ["Vali Aliyev"]
    assert names("from=2026-10-01") == ["Ali Valiyev"]
    assert names(f"member={staff.vali.pk}") == ["Vali Aliyev"]
    assert names("q=vali") == ["Ali Valiyev", "Vali Aliyev"]


# The person's own side ---------------------------------------------------------------------------


def test_the_person_reads_acknowledges_and_explains(
    shop, staff, api_as, django_capture_on_commit_callbacks
):
    record = give(staff.ali, staff.manager)
    theirs = give(staff.vali, staff.manager)
    client = api_as(staff.ali)
    mine = f"/api/v1/companies/{shop.pk}/lifecycle/records/"

    listed = client.get(mine).json()
    assert [row["id"] for row in listed] == [record.pk]
    assert listed[0]["description"] == STORY and "evidence" not in listed[0]
    detail = client.get(f"{mine}{record.pk}/").json()
    assert detail["read_at"] is not None
    acknowledged = client.post(f"{mine}{record.pk}/acknowledge/").json()
    assert acknowledged["status"] == "acknowledged"
    with django_capture_on_commit_callbacks(execute=True):
        explained = client.post(
            f"{mine}{record.pk}/explain/",
            {"text": "Muzlatgich buzilgan edi, ustaga xabar berganman."},
            format="json",
        )
    assert explained.json()["employee_response"].startswith("Muzlatgich buzilgan")
    notice = Notification.objects.get(kind="lifecycle.explanation")
    assert notice.recipient == staff.manager
    assert notice.title == "Explanation from: Ali Valiyev"
    assert client.get(f"{mine}{theirs.pk}/").status_code == 404
    assert client.post(f"{mine}{theirs.pk}/acknowledge/").status_code == 404
    assert client.post(f"{mine}{theirs.pk}/explain/", {"text": "x"}).status_code == 404


def test_a_suspended_person_reads_but_doesnt_answer(shop, staff, api_as):
    record = give(staff.ali, staff.manager)
    members.suspend(staff.ali, by=staff.owner, until=None, reason="Tekshiruv")
    client = api_as(Membership.objects.get(pk=staff.ali.pk))
    mine = f"/api/v1/companies/{shop.pk}/lifecycle/records/"

    assert client.get(mine).status_code == 200
    assert client.post(f"{mine}{record.pk}/acknowledge/").status_code == 403


# The AI tool --------------------------------------------------------------------------------


def test_the_overview_tool_never_tells_what_a_record_says(shop, staff, payroll):
    give(staff.ali, staff.manager, fine_amount=Decimal("200000"))
    give(staff.sara, staff.manager, kind="verbal_warning", category="lateness")
    services.explain(
        DisciplinaryRecord.objects.get(membership=staff.ali),
        by=staff.ali,
        text="Ustaga xabar berganman",
    )
    members.suspend(staff.vali, by=staff.owner, until=DAY + timedelta(days=5), reason="Kamomad")

    result = call_tool("lifecycle_overview", staff.owner, _now=local(DAY, 10))

    data = result["data"]
    assert data["given"] == 2 and data["suspended_now"] == 1
    assert data["by_category"] == {"storage_breach": 1, "lateness": 1}
    assert data["with_fine"] == 1 and data["explained"] == 1
    records = [row for row in result["rows"] if row["type"] == "record"]
    assert {row["name"] for row in records} == {"Ali Valiyev", "Sara Tosheva"}
    suspension = next(row for row in result["rows"] if row["type"] == "suspension")
    assert suspension["until"] == "2026-10-26"
    text = json.dumps(result, ensure_ascii=False)
    for secret in (STORY, "Muzlatgich", "Ustaga", "Kamomad", "200000"):
        assert secret not in text
    lead = call_tool("lifecycle_overview", staff.lead, _now=local(DAY, 10))
    assert "Sara Tosheva" not in json.dumps(lead, ensure_ascii=False)
    assert call_tool("lifecycle_overview", staff.ali) == {"error": "not_allowed"}
