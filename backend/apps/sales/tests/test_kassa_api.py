"""The mini app's Kassa endpoints: open, movements, receipts, close (multipart, blind) and the
receiver's handover answers. The blind count never leaks expected cash to the cashier."""

import json
from decimal import Decimal

import pytest

from apps.members.models import Membership
from apps.sales import services
from apps.sales.models import CashMovement, CashShift, SalesSettings
from apps.sales.tests.factories import jpeg, make_member


def url(company, path: str) -> str:
    return f"/api/v1/companies/{company.pk}/sales/{path}"


def forbidden_words(payload) -> set[str]:
    """Keys whose value would tell a blind cashier how much cash there should be."""
    found = set()

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if (
                    key in ("expected_cash", "difference", "expected", "expected_float")
                    and item is not None
                ):
                    found.add(key)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return found


@pytest.fixture
def client(shop, api_as):
    return api_as(shop.cashier)


def open_via_api(shop, client, count=None):
    return client.post(
        url(shop.company, "shifts/"),
        {"register_id": shop.register.pk, "opening_count": count or {"50000": 4}},
        format="json",
    )


def close_via_api(shop, client, shift_id, *, counted="1150000", photos=True):
    data = {
        "payments": json.dumps(
            [
                {"method_id": shop.method("cash").pk, "sales": "1000000", "refunds": "0"},
                {"method_id": shop.method("uzcard").pk, "sales": "400000"},
            ]
        ),
        "closing_count": json.dumps({"50000": int(Decimal(counted) // 50000)}) if counted else "{}",
        "counted_cash": counted,
        "receipts": "18",
        "z_number": "0412",
    }
    if photos:
        data["z_photo"] = jpeg("z.jpg")
        data["terminal_photo"] = jpeg("slip.jpg")
    return client.post(url(shop.company, f"shifts/{shift_id}/close/"), data, format="multipart")


def test_current_gives_kassa_everything(shop, client):
    data = client.get(url(shop.company, "shifts/current/")).json()
    assert data["shift"] is None
    assert [r["id"] for r in data["registers"]] == [shop.register.pk]  # only my branch
    assert data["settings"]["blind_cash_count"] is True
    assert {m["name"] for m in data["methods"]} >= {"Cash", "Uzcard", "Click"}
    assert shop.manager.pk in {r["id"] for r in data["receivers"]}
    assert shop.cashier.pk not in {r["id"] for r in data["receivers"]}
    assert "goods" in {c["code"] for c in data["categories"]}
    assert "salaries" not in {c["code"] for c in data["categories"]}


def test_open_then_close_without_seeing_expected_cash(shop, client, owner_api):
    response = open_via_api(shop, client)
    assert response.status_code == 201, response.json()
    shift = response.json()
    assert shift["opening_float"] == "200000.00" and shift["status"] == "open"
    assert not forbidden_words(response.json())
    current = client.get(url(shop.company, "shifts/current/")).json()
    assert current["shift"]["id"] == shift["id"]
    assert not forbidden_words(current)

    response = close_via_api(shop, client, shift["id"], counted="1150000")
    assert response.status_code == 200, response.json()
    closed = response.json()
    assert closed["status"] == "closed" and closed["counted_cash"] == "1150000.00"
    assert not forbidden_words(closed)
    assert CashShift.objects.get(pk=shift["id"]).difference == Decimal("-50000.00")
    history = client.get(url(shop.company, "shifts/")).json()["results"]
    assert not forbidden_words(history)
    assert not forbidden_words(client.get(url(shop.company, f"shifts/{shift['id']}/")).json())

    # Once a manager verified it, the cashier sees the difference.
    owner_api(shop.manager).post(
        f"/api/v1/owner/companies/{shop.company.pk}/sales/shifts/{shift['id']}/verify/", {}
    )
    detail = client.get(url(shop.company, f"shifts/{shift['id']}/")).json()
    assert detail["difference"] == "-50000.00" and detail["status"] == "verified"


def test_without_blind_count_the_result_shows_after_close(shop, client):
    SalesSettings.objects.filter(company=shop.company).update(blind_cash_count=False)
    shift = open_via_api(shop, client).json()
    closed = close_via_api(shop, client, shift["id"], counted="1200000").json()
    assert closed["difference"] == "0.00" and closed["expected_cash"] == "1200000.00"


def test_close_needs_the_photos_and_a_lost_response_can_be_retried(shop, client):
    shift = open_via_api(shop, client).json()
    response = close_via_api(shop, client, shift["id"], photos=False)
    assert response.status_code == 400
    assert close_via_api(shop, client, shift["id"]).status_code == 200
    # The same request again (bad signal ate the answer) is answered with the closed shift.
    again = close_via_api(shop, client, shift["id"])
    assert again.status_code == 200 and again.json()["status"] == "closed"
    assert CashShift.objects.filter(pk=shift["id"]).count() == 1


def test_movements_from_the_app(shop, client):
    shift = open_via_api(shop, client).json()
    response = client.post(
        url(shop.company, f"shifts/{shift['id']}/movements/"),
        {"kind": "payout", "amount": "90000", "reason": "Water", "photo": jpeg()},
        format="multipart",
    )
    assert response.status_code == 201, response.json()
    assert response.json()["photo"].startswith("/api/v1/files/")
    response = client.post(
        url(shop.company, f"shifts/{shift['id']}/movements/"),
        {"kind": "handover", "amount": "100000", "receiver_id": shop.manager.pk},
        format="json",
    )
    assert response.json()["status"] == "pending"
    # A bank transfer is a manager's job in the dashboard.
    response = client.post(
        url(shop.company, f"shifts/{shift['id']}/movements/"),
        {"kind": "to_bank", "amount": "100000"},
        format="json",
    )
    assert response.status_code == 400
    detail = client.get(url(shop.company, f"shifts/{shift['id']}/")).json()
    assert [m["kind"] for m in detail["movements"]] == ["handover", "payout"]
    assert detail["moved"] == {"handover": "100000.00", "payout": "90000.00"}


def test_receipts_only_in_receipts_mode(shop, client):
    open_via_api(shop, client)
    body = {"payments": [{"method_id": shop.method("cash").pk, "amount": "45000"}]}
    assert client.post(url(shop.company, "entries/"), body, format="json").status_code == 400
    SalesSettings.objects.filter(company=shop.company).update(mode="receipts")
    response = client.post(url(shop.company, "entries/"), body, format="json")
    assert response.status_code == 201 and response.json()["total"] == "45000.00"
    sale_id = response.json()["id"]
    assert (
        client.post(
            url(shop.company, f"entries/{sale_id}/void/"), {"reason": "Mistake"}, format="json"
        ).status_code
        == 200
    )


def test_handovers_are_answered_by_their_receiver(shop, api_as):
    services.open_shift(by=shop.cashier, register=shop.register, opening_float="500000")
    movement = services.record_movement(
        by=shop.cashier,
        register=shop.register,
        kind="handover",
        amount="300000",
        receiver=shop.colleague,
    )
    colleague = api_as(shop.colleague)
    pending = colleague.get(url(shop.company, "handovers/pending/")).json()["results"]
    assert [row["id"] for row in pending] == [movement.pk]
    assert pending[0]["from"]["id"] == shop.cashier.pk
    assert (
        api_as(shop.manager)
        .post(url(shop.company, f"handovers/{movement.pk}/confirm/"))
        .status_code
        == 404
    )
    response = colleague.post(
        url(shop.company, f"handovers/{movement.pk}/decline/"), {"reason": "No"}, format="json"
    )
    assert response.json()["status"] == "declined"
    assert CashMovement.objects.get(pk=movement.pk).declined_at is not None


def test_kassa_needs_sales_operate(shop, api_as):
    worker = make_member(shop.company, "Employee", branches=(shop.branch,))
    client = api_as(worker)
    assert client.get(url(shop.company, "shifts/current/")).status_code == 403
    assert (
        client.post(
            url(shop.company, "shifts/"), {"register_id": shop.register.pk}, format="json"
        ).status_code
        == 403
    )
    # Answering a handover needs no permission.
    assert client.get(url(shop.company, "handovers/pending/")).status_code == 200


def test_another_branch_till_is_refused(shop, client):
    response = client.post(
        url(shop.company, "shifts/"), {"register_id": shop.other_register.pk}, format="json"
    )
    assert response.status_code == 400


def test_suspended_cashier_is_turned_away(shop, client):
    Membership.objects.filter(pk=shop.cashier.pk).update(status=Membership.Status.SUSPENDED)
    response = client.get(url(shop.company, "shifts/current/"))
    assert response.status_code == 403 and response.json()["code"] == "suspended"


def test_someone_elses_shift_is_404(shop, client, api_as):
    theirs = services.open_shift(by=shop.colleague, register=shop.other_register, opening_float="0")
    assert client.get(url(shop.company, f"shifts/{theirs.pk}/")).status_code == 404
    assert close_via_api(shop, client, theirs.pk).status_code == 404


def test_module_off_hides_kassa(shop, client):
    shop.company.features = []
    shop.company.save(update_fields=["features"])
    assert client.get(url(shop.company, "shifts/current/")).status_code == 404
