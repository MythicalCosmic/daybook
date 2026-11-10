"""Equipment (`lifecycle/equipment/…`), built on apps.assets: categories suggested for a
pharmacy, ten lab coats in one go, giving things with a photo (one notice, the person confirms
in the app), the photo's access, coming back (damaged and written off, lost) with a deduction
proposed to payroll, what a device needs, hidden values, scope, the handover list and the
evening job that never waits for them, and Person 360's tab.

The clock stands at 10:00 on Wednesday 21 October 2026 (Asia/Tashkent).
"""

import io
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.assets import defaults
from apps.assets.models import Asset, AssetAssignment, AssetCategory
from apps.assets.providers import may_open_handout
from apps.audit.models import AuditLog
from apps.hr.tests.conftest import local
from apps.inbox.models import Notification
from apps.lifecycle import terminations
from apps.lifecycle.equipment import services
from apps.members.models import AccessRole
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db

LAST = date(2026, 11, 4)


def base(company) -> str:
    return f"/api/v1/owner/companies/{company.pk}/lifecycle/equipment/"


def photo(name="coat.jpg", color="white") -> SimpleUploadedFile:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(out, "JPEG")
    return SimpleUploadedFile(name, out.getvalue(), content_type="image/jpeg")


@pytest.fixture
def run(django_capture_on_commit_callbacks):
    def call(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return call


@pytest.fixture
def kit(shop, staff, chilonzor):
    """Assets on, a lab coat category with two coats and a badge at Chilonzor, a device
    category with a phone."""
    shop.features = [*shop.features, "assets"]
    shop.save(update_fields=["features"])
    defaults.ensure(shop)
    coats = services.add_category(shop, by=staff.owner, suggestion="lab_coat")
    badges = services.add_category(shop, by=staff.owner, suggestion="badge")
    phones = services.add_category(shop, by=staff.owner, suggestion="phone")
    made = services.add_items(
        shop, by=staff.owner, category=coats, name="Xalat", quantity=2, branch=chilonzor, note="48"
    )
    [badge] = services.add_items(
        shop, by=staff.owner, category=badges, name="Beyj", branch=chilonzor
    )
    [phone] = services.add_items(
        shop,
        by=staff.owner,
        category=phones,
        name="Telefon Redmi",
        branch=chilonzor,
        cost="2400000",
        serial="RM-1188",
    )
    return {"coats": made, "badge": badge, "phone": phone, "coat_category": coats}


def holder_of(data, person) -> dict:
    return next(row for row in data["people"] if row["person"]["id"] == person.pk)


def issue(client, shop, person, items, **extra):
    return client.post(
        f"{base(shop)}issue/",
        {"person_id": person.pk, "asset_ids": [item.pk for item in items], **extra},
        format="multipart",
    )


# Adding things ---------------------------------------------------------------------------------


def test_ten_lab_coats_in_one_go_are_numbered_with_their_size(
    shop, staff, kit, owner_api, chilonzor
):
    client = owner_api(staff.lead)  # hr.manage at Chilonzor, no assets.manage

    response = client.post(
        f"{base(shop)}items/",
        {
            "category_id": kit["coat_category"].pk,
            "name": "Xalat",
            "quantity": 10,
            "branch_id": chilonzor.pk,
            "note": "O‘lcham 50",
        },
        format="json",
    )

    assert response.status_code == 201, response.content
    names = [row["name"] for row in response.json()["items"]]
    # The first two coats are №1 and №2: this batch goes on from №3.
    assert sorted(names, key=lambda n: int(n.split("№")[1])) == [
        f"Xalat №{n}" for n in range(3, 13)
    ]
    rows = Asset.objects.filter(company=shop, name__startswith="Xalat №")
    assert rows.count() == 12
    assert len({row.number for row in rows}) == 12  # each has its own inventory number
    assert set(rows.filter(notes="O‘lcham 50").values_list("branch_id", flat=True)) == {
        chilonzor.pk
    }
    assert AuditLog.objects.filter(action="lifecycle.equipment_added").exists()


def test_a_device_is_added_and_written_off_only_by_an_asset_manager(
    shop, staff, kit, owner_api, chilonzor
):
    client = owner_api(staff.lead)
    phones = AssetCategory.objects.get(company=shop, icon="smartphone")

    response = client.post(
        f"{base(shop)}items/",
        {"category_id": phones.pk, "name": "Telefon", "branch_id": chilonzor.pk, "cost": "900000"},
        format="json",
    )
    assert response.status_code == 403
    # Giving it out and taking it back is anyone's who runs the equipment.
    assert issue(client, shop, staff.ali, [kit["phone"]]).status_code == 200
    assignment = AssetAssignment.objects.get(asset=kit["phone"], returned_on__isnull=True)
    lost = client.post(
        f"{base(shop)}handouts/{assignment.pk}/return/", {"outcome": "lost"}, format="json"
    )
    assert lost.status_code == 403
    kit["phone"].refresh_from_db()
    assert kit["phone"].custodian_id == staff.ali.pk


def test_categories_suggested_for_a_pharmacy(shop, staff, kit, owner_api):
    owner = owner_api(staff.owner).get(f"{base(shop)}categories/").json()
    suggested = {row["key"] for row in owner["suggestions"]}
    assert "lab_coat" not in suggested and "badge" not in suggested  # made already
    assert {"key", "cash_key", "tablet", "scanner"} <= suggested
    coats = next(row for row in owner["categories"] if row["icon"] == "shirt")
    assert (coats["stock"], coats["out"], coats["kind"]) == (2, 0, "low_value")

    lead = owner_api(staff.lead).get(f"{base(shop)}categories/").json()
    assert {row["key"] for row in lead["suggestions"]} == {"key", "cash_key"}  # no devices

    made = owner_api(staff.lead).post(
        f"{base(shop)}categories/", {"suggestion": "cash_key"}, format="json"
    )
    assert made.status_code == 201
    assert AssetCategory.objects.filter(company=shop, icon="key-square", kind="low_value").exists()


# Giving out ----------------------------------------------------------------------------------


def test_given_with_a_photo_one_notice_and_confirmed_in_the_app(
    shop, staff, kit, owner_api, api_as, django_capture_on_commit_callbacks
):
    client = owner_api(staff.lead)
    with django_capture_on_commit_callbacks(execute=True):
        response = issue(
            client,
            shop,
            staff.ali,
            [kit["coats"][0], kit["badge"]],
            condition="new",
            note="Yangi",
            photo=photo(),
        )

    assert response.status_code == 200, response.content
    row = response.json()
    assert sorted(item["name"] for item in row["items"]) == ["Beyj", "Xalat №1"]
    assert row["unconfirmed"] == 2
    held = AssetAssignment.objects.filter(membership=staff.ali, returned_on__isnull=True)
    assert held.count() == 2
    assert len({assignment.photo_out.name for assignment in held}) == 1  # stored once
    assert all(item["photo_url"] for item in row["items"])
    notices = Notification.objects.filter(recipient=staff.ali, kind="assets.issued")
    assert notices.count() == 1
    assert "2" in notices.get().title

    # In the app: the photo and "I have it"; then the page says when.
    mine = api_as(staff.ali).get(f"/api/v1/companies/{shop.pk}/assets/mine/").json()
    assert len(mine) == 2 and all(item["photo_url"] for item in mine)
    first = mine[0]["id"]
    assert (
        api_as(staff.ali)
        .post(f"/api/v1/companies/{shop.pk}/assets/mine/{first}/acknowledge/")
        .status_code
        == 200
    )
    page = owner_api(staff.lead).get(base(shop)).json()
    ali = holder_of(page, staff.ali)
    assert ali["unconfirmed"] == 1
    assert sum(1 for item in ali["items"] if item["acknowledged_at"]) == 1
    assert page["totals"]["items"] == 2
    assert AuditLog.objects.filter(
        action="lifecycle.equipment_issued", target_id=staff.ali.pk
    ).exists()


def test_who_may_open_the_photo(shop, staff, kit, owner_api, outsider):
    issue(owner_api(staff.owner), shop, staff.ali, [kit["badge"]], photo=photo())
    assignment = AssetAssignment.objects.get(asset=kit["badge"], returned_on__isnull=True)

    assert may_open_handout(staff.ali.user, shop.pk, assignment.pk)  # who got it
    assert may_open_handout(staff.lead.user, shop.pk, assignment.pk)  # HR of the branch
    assert may_open_handout(staff.owner.user, shop.pk, assignment.pk)
    assert not may_open_handout(staff.vali.user, shop.pk, assignment.pk)  # a colleague
    assert not may_open_handout(staff.sara.user, shop.pk, assignment.pk)
    assert not may_open_handout(outsider.user, shop.pk, assignment.pk)


def test_nothing_is_given_when_one_thing_is_held_already(shop, staff, kit, owner_api):
    client = owner_api(staff.owner)
    assert issue(client, shop, staff.vali, [kit["badge"]]).status_code == 200

    response = issue(client, shop, staff.ali, [kit["coats"][0], kit["badge"]])

    assert response.status_code == 400
    assert not AssetAssignment.objects.filter(membership=staff.ali).exists()


# Coming back -----------------------------------------------------------------------------------


def test_back_damaged_written_off_with_a_deduction_payroll_approves(shop, staff, kit, owner_api):
    from apps.payroll.models import Adjustment

    client = owner_api(staff.owner)
    issue(client, shop, staff.ali, [kit["coats"][0]])
    assignment = AssetAssignment.objects.get(asset=kit["coats"][0], returned_on__isnull=True)

    response = client.post(
        f"{base(shop)}handouts/{assignment.pk}/return/",
        {
            "outcome": "returned",
            "condition": "damaged",
            "note": "Yengi yirtilgan",
            "photo": photo(color="gray"),
            "write_off": "true",
            "deduction": "95000",
        },
        format="multipart",
    )

    assert response.status_code == 200, response.content
    assert response.json()["items"] == []
    assignment.refresh_from_db()
    assert (assignment.condition_in, assignment.returned_on) == ("damaged", date(2026, 10, 21))
    assert assignment.photo_in
    coat = Asset.objects.get(pk=kit["coats"][0].pk)
    assert (coat.status, coat.disposal) == (Asset.Status.DISPOSED, Asset.Disposal.WRITTEN_OFF)
    fine = Adjustment.objects.get(pk=assignment.deduction_id)
    assert (fine.kind, fine.status, fine.amount) == ("fine", "proposed", Decimal("95000.00"))
    assert fine.membership_id == staff.ali.pk
    page = client.get(
        f"/api/v1/owner/companies/{shop.pk}/lifecycle/people/{staff.ali.pk}/equipment/"
    )
    [past] = page.json()["history"]
    assert past["outcome"] == "written_off"
    assert past["deduction"]["status"] == "proposed"
    assert past["photo_in_url"]


def test_lost_is_written_off_as_lost(shop, staff, kit, owner_api):
    client = owner_api(staff.lead)
    issue(client, shop, staff.ali, [kit["badge"]])
    assignment = AssetAssignment.objects.get(asset=kit["badge"], returned_on__isnull=True)

    response = client.post(
        f"{base(shop)}handouts/{assignment.pk}/return/",
        {"outcome": "lost", "note": "Yo‘qotib qo‘ydi"},
        format="json",
    )

    assert response.status_code == 200, response.content
    badge = Asset.objects.get(pk=kit["badge"].pk)
    assert (badge.status, badge.disposal) == (Asset.Status.DISPOSED, Asset.Disposal.LOST)
    history = client.get(
        f"/api/v1/owner/companies/{shop.pk}/lifecycle/people/{staff.ali.pk}/equipment/"
    ).json()["history"]
    assert history[0]["outcome"] == "lost"


def test_one_deduction_at_a_time_and_its_amount_only_with_payroll_view(shop, staff, kit, owner_api):
    client = owner_api(staff.lead)
    issue(client, shop, staff.ali, [kit["coats"][1]])
    assignment = AssetAssignment.objects.get(asset=kit["coats"][1], returned_on__isnull=True)
    url = f"{base(shop)}handouts/{assignment.pk}/deduction/"

    first = client.post(url, {"amount": "120000", "reason": "Yo‘qoldi"}, format="json")
    second = client.post(url, {"amount": "120000"}, format="json")

    assert first.status_code == 200, first.content
    assert second.status_code == 400
    item = first.json()["items"][0]
    assert item["deduction"]["status"] == "proposed"
    assert item["deduction"]["amount"] is None  # the lead doesn't see pay
    owner = holder_of(owner_api(staff.owner).get(base(shop)).json(), staff.ali)
    assert owner["items"][0]["deduction"]["amount"] == "120000.00"


def test_values_only_for_register_readers(shop, staff, kit, owner_api):
    client = owner_api(staff.owner)
    issue(client, shop, staff.ali, [kit["phone"]])

    owner = owner_api(staff.owner).get(base(shop)).json()
    lead = owner_api(staff.lead).get(base(shop)).json()

    assert holder_of(owner, staff.ali)["value"] == "2400000.00"
    assert owner["totals"]["value"] == "2400000.00"
    assert holder_of(lead, staff.ali)["value"] is None
    assert holder_of(lead, staff.ali)["items"][0]["value"] is None
    assert lead["totals"]["value"] is None
    assert lead["can"]["values"] is False


# Scope and switches ----------------------------------------------------------------------------


def test_scope_rights_and_the_modules(shop, staff, kit, owner_api, outsider, yunusobod):
    lead = owner_api(staff.lead)
    names = {row["person"]["name"] for row in lead.get(base(shop)).json()["people"]}
    assert "Sara Tosheva" not in names and "Ali Valiyev" in names
    assert issue(lead, shop, staff.sara, [kit["badge"]]).status_code == 404
    assert (
        lead.get(
            f"/api/v1/owner/companies/{shop.pk}/lifecycle/people/{staff.sara.pk}/equipment/"
        ).status_code
        == 404
    )
    assert lead.get(f"{base(shop)}?branch={yunusobod.pk}").status_code == 404
    assert owner_api(outsider).get(base(shop)).status_code == 404
    # The Manager role reads HR but runs neither HR nor assets.
    assert owner_api(staff.manager).get(base(shop)).status_code == 403
    AccessRole.objects.filter(company=shop, name="Branch HR").update(
        permissions=[Perm.DASHBOARD_ACCESS, Perm.ASSETS_MANAGE]
    )
    assert owner_api(staff.lead).get(base(shop)).status_code == 200  # assets.manage alone

    shop.features = ["hr", "payroll"]
    shop.save(update_fields=["features"])
    assert owner_api(staff.owner).get(base(shop)).status_code == 403
    shop.features = ["assets"]
    shop.save(update_fields=["features"])
    assert owner_api(staff.owner).get(base(shop)).status_code == 403


# Leaving ---------------------------------------------------------------------------------------


def test_leaving_lists_them_and_the_evening_never_waits_for_them(
    shop, staff, kit, owner_api, run, freeze
):
    client = owner_api(staff.owner)
    issue(client, shop, staff.ali, [kit["coats"][0], kit["badge"]])
    termination = run(
        terminations.request, staff.ali, by=staff.ali, wished_last_day=LAST, reason="Ko‘chyapman"
    )
    run(terminations.agree, termination, by=staff.owner)

    equipment = [item for item in termination.handover.all() if item.asset_id]
    assert len(equipment) == 2  # in R's handover list
    page = client.get(base(shop)).json()
    ali = holder_of(page, staff.ali)
    assert ali["leaving"]["day"] == LAST.isoformat()
    assert ali["leaving_soon"] is True
    assert page["totals"]["to_return"] == 2

    freeze(local(LAST, 20, 30))
    assert run(terminations.complete_due) == 1  # nothing handed back, it still completes
    termination.refresh_from_db()
    assert termination.status == "completed"
    assert len(termination.left_open) >= 2
    after = client.get(base(shop)).json()
    gone = holder_of(after, staff.ali)
    assert (gone["person"]["status"], gone["overdue"]) == ("left", 2)
    assert gone["left_on"] == LAST.isoformat()
    # Payroll's rule: no deductions for someone who has left; taking it back still works.
    assignment = AssetAssignment.objects.get(asset=kit["badge"], returned_on__isnull=True)
    refused = client.post(
        f"{base(shop)}handouts/{assignment.pk}/deduction/", {"amount": "50000"}, format="json"
    )
    assert refused.status_code == 400
    back = client.post(
        f"{base(shop)}handouts/{assignment.pk}/return/",
        {"condition": "good"},
        format="json",
    )
    assert back.status_code == 200, back.content
    assert holder_of(client.get(base(shop)).json(), staff.ali)["overdue"] == 1


def test_items_tab_stock_and_given_out(shop, staff, kit, owner_api):
    client = owner_api(staff.owner)
    issue(client, shop, staff.ali, [kit["badge"]])

    stock = client.get(f"{base(shop)}items/").json()
    out = client.get(f"{base(shop)}items/?status=out").json()

    assert {row["name"] for row in stock} == {"Xalat №1", "Xalat №2", "Telefon Redmi"}
    [badge] = out
    assert (badge["name"], badge["holder"]["id"]) == ("Beyj", staff.ali.pk)
    assert badge["acknowledged_at"] is None
    totals = client.get(base(shop)).json()["totals"]
    assert (totals["in_stock"], totals["unconfirmed"], totals["people"]) == (3, 1, 1)


def test_person_tab_holds_now_and_before(shop, staff, kit, owner_api):
    client = owner_api(staff.owner)
    issue(client, shop, staff.ali, [kit["coats"][0]])
    assignment = AssetAssignment.objects.get(asset=kit["coats"][0], returned_on__isnull=True)
    client.post(
        f"{base(shop)}handouts/{assignment.pk}/return/", {"condition": "worn"}, format="json"
    )
    issue(client, shop, staff.ali, [kit["badge"]])

    data = client.get(
        f"/api/v1/owner/companies/{shop.pk}/lifecycle/people/{staff.ali.pk}/equipment/"
    ).json()

    assert [item["name"] for item in data["holder"]["items"]] == ["Beyj"]
    assert [(row["name"], row["outcome"]) for row in data["history"]] == [
        ("Beyj", "held"),
        ("Xalat №1", "returned"),
    ]
    assert data["history"][1]["condition_in"] == "worn"
    assert data["today"] == "2026-10-21"
    assert (date(2026, 10, 21) - timedelta(days=0)).isoformat() == data["history"][0]["issued_on"]
