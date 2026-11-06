"""Owner endpoints of sale lines (PLAN-OWNER §14.7, rule 21): permissions (403), another
company (404), the module switch, branch isolation, the cost field only for finance.view,
audit entries, and the whole path from a profile through an upload to the match list."""

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audit.models import AuditLog
from apps.inventory.tests.factories import ProductFactory
from apps.members.permissions import Perm
from apps.sales import lines, services
from apps.sales.models import PosCashier, SaleLine, SalesImport, SalesSettings
from apps.sales.tests.factories import make_member, scoped_role
from apps.sales.tests.test_lines import AMOXICILLIN, COLUMNS, HEADER, PARACETAMOL, UNKNOWN, line


def url(company, path: str) -> str:
    return f"/api/v1/owner/companies/{company.pk}/sales/{path}"


def upload(*rows: str, name="export.csv") -> SimpleUploadedFile:
    text = "\n".join([HEADER, *rows]) + "\n"
    return SimpleUploadedFile(name, text.encode(), content_type="text/csv")


@pytest.fixture
def pharmacy(shop):
    SalesSettings.objects.filter(company=shop.company).update(
        sales_lines=SalesSettings.Lines.IMPORT
    )
    shop.paracetamol = ProductFactory(company=shop.company, barcode=PARACETAMOL, units_per_pack=1)
    shop.amoxicillin = ProductFactory(
        company=shop.company,
        name="Amoksitsillin 500 mg kapsula №16",
        barcode=AMOXICILLIN,
        units_per_pack=1,
        rx_required=True,
        reference_price=Decimal("12000.00"),
    )
    shop.profile = services.create_import_profile(
        shop.company, by=shop.owner, name="Apteka Pro", columns=COLUMNS, branch=shop.branch
    )
    return shop


def imported(shop, *rows) -> SalesImport:
    imp = services.start_import(shop.profile, by=shop.owner, file=upload(*rows))
    lines.process(imp.pk)
    imp.refresh_from_db()
    return imp


def person_with(shop, *perms, branches=None):
    role = scoped_role(shop.company, *perms)
    member = make_member(shop.company, "Owner", branches=branches or (shop.branch,))
    member.role = role
    member.save(update_fields=["role"])
    return member


MANAGE_READS = ["import-profiles/", "imports/", "lines/codes/", "pos-cashiers/"]


@pytest.mark.parametrize("path", MANAGE_READS)
def test_import_reads_need_sales_manage_and_hide_other_companies(
    pharmacy, owner_api, other_company, member, path
):
    assert owner_api(pharmacy.owner).get(url(pharmacy.company, path)).status_code == 200
    viewer = person_with(pharmacy, Perm.SALES_VIEW, Perm.BRANCHES_ALL)
    assert owner_api(viewer).get(url(pharmacy.company, path)).status_code == 403
    stranger = member(other_company, "Owner")
    assert owner_api(stranger).get(url(pharmacy.company, path)).status_code == 404


def test_lines_and_products_need_sales_view(pharmacy, owner_api, other_company, member):
    for path in ("lines/", "products/?q=para"):
        assert owner_api(pharmacy.owner).get(url(pharmacy.company, path)).status_code == 200
        nobody = person_with(pharmacy, Perm.BRANCHES_ALL)
        assert owner_api(nobody).get(url(pharmacy.company, path)).status_code == 403
        stranger = member(other_company, "Owner")
        assert owner_api(stranger).get(url(pharmacy.company, path)).status_code == 404


def test_the_endpoints_vanish_while_sales_is_off(pharmacy, owner_api):
    pharmacy.company.features = ["finance"]
    pharmacy.company.save(update_fields=["features"])
    assert owner_api(pharmacy.owner).get(url(pharmacy.company, "lines/")).status_code == 404
    assert owner_api(pharmacy.owner).get(url(pharmacy.company, "imports/")).status_code == 404


def test_a_profile_through_the_mapper_an_upload_and_the_match_list(
    pharmacy, owner_api, django_capture_on_commit_callbacks
):
    client = owner_api(pharmacy.owner)
    company = pharmacy.company
    # The mapper reads the file's headers and proposes the map.
    preview = client.post(
        url(company, "import-profiles/preview/"),
        {"file": upload(line(), line(receipt="2")), "file_kind": "csv"},
        format="multipart",
    )
    assert preview.status_code == 200, preview.content
    body = preview.json()
    assert body["headers"][0] == "Чек" and body["total_rows"] == 2 and len(body["rows"]) == 2
    assert body["guess"]["code"] == "Штрихкод" and body["file_kind"] == "csv"
    # A profile with that map.
    made = client.post(
        url(company, "import-profiles/"),
        {
            "name": "Kassa 2",
            "file_kind": "csv",
            "columns": body["guess"],
            "branch_id": pharmacy.branch.pk,
        },
        format="json",
    )
    assert made.status_code == 201, made.content
    profile_id = made.json()["id"]
    assert made.json()["branch"]["id"] == pharmacy.branch.pk
    assert AuditLog.objects.filter(action="sales.import_profile_created").exists()
    # An upload is read in the background.
    with django_capture_on_commit_callbacks(execute=True):
        sent = client.post(
            url(company, "imports/"),
            {"profile_id": profile_id, "file": upload(line(), line(receipt="2", code=UNKNOWN))},
            format="multipart",
        )
    assert sent.status_code == 201, sent.content
    detail = client.get(url(company, f"imports/{sent.json()['id']}/")).json()
    assert detail["status"] == "ready" and detail["matched"] == 1 and detail["unmatched"] == 1
    assert detail["profile"]["name"] == "Kassa 2"
    # The match list, then matching the unknown code.
    codes = client.get(url(company, "lines/codes/")).json()["results"]
    assert [row["code"] for row in codes] == [UNKNOWN]
    found = client.get(url(company, "products/"), {"q": "Amoks"}).json()["results"]
    assert [row["id"] for row in found] == [pharmacy.amoxicillin.pk]
    matched = client.post(
        url(company, "lines/match/"),
        {"code": UNKNOWN, "product_id": pharmacy.amoxicillin.pk},
        format="json",
    )
    assert matched.status_code == 200 and matched.json() == {"lines": 1}
    assert client.get(url(company, "lines/codes/")).json()["results"] == []
    assert AuditLog.objects.filter(action="sales.code_matched").exists()
    # A code nothing waits for.
    again = client.post(
        url(company, "lines/match/"),
        {"code": UNKNOWN, "product_id": pharmacy.amoxicillin.pk},
        format="json",
    )
    assert again.status_code == 400


def test_lines_hide_the_cost_without_finance_view_and_filter_breaches(pharmacy, owner_api):
    imported(
        pharmacy,
        line(receipt="1", code=AMOXICILLIN, total="13500"),
        line(receipt="2", code=AMOXICILLIN, total="11000"),
        line(receipt="3"),
    )
    SaleLine.objects.update(cost=Decimal("9000.00"))
    owner = owner_api(pharmacy.owner).get(url(pharmacy.company, "lines/")).json()
    assert owner["count"] == 3 and all("cost" in row for row in owner["results"])
    seller = person_with(pharmacy, Perm.SALES_VIEW, Perm.BRANCHES_ALL)
    rows = owner_api(seller).get(url(pharmacy.company, "lines/")).json()["results"]
    assert rows and all("cost" not in row for row in rows)
    breaches = owner_api(seller).get(url(pharmacy.company, "lines/"), {"cap": "true"}).json()
    assert breaches["count"] == 1
    [row] = breaches["results"]
    assert row["over_cap"] is True and row["pack_price"] == "13500.00" and row["cap"] == "12000.00"
    rx = owner_api(seller).get(url(pharmacy.company, "lines/"), {"rx": "true"}).json()
    assert rx["count"] == 2


def test_a_branch_lead_sees_only_their_branchs_lines_and_profiles(pharmacy, owner_api):
    imported(pharmacy, line(receipt="1"))
    other = services.create_import_profile(
        pharmacy.company,
        by=pharmacy.owner,
        name="Yunusobod kassa",
        columns=COLUMNS,
        branch=pharmacy.other_branch,
    )
    lead = person_with(
        pharmacy, Perm.SALES_VIEW, Perm.SALES_MANAGE, branches=(pharmacy.other_branch,)
    )
    client = owner_api(lead)
    assert client.get(url(pharmacy.company, "lines/")).json()["count"] == 0
    profiles = client.get(url(pharmacy.company, "import-profiles/")).json()
    assert [row["id"] for row in profiles] == [other.pk]
    # Someone else's profile can't be used to upload.
    sent = client.post(
        url(pharmacy.company, "imports/"),
        {"profile_id": pharmacy.profile.pk, "file": upload(line())},
        format="multipart",
    )
    assert sent.status_code == 400
    imp = SalesImport.objects.get(profile=pharmacy.profile)
    assert client.get(url(pharmacy.company, f"imports/{imp.pk}/")).status_code == 404
    # A profile with a branch column (every branch) is for people who see every branch.
    made = client.post(
        url(pharmacy.company, "import-profiles/"),
        {"name": "All", "columns": {**COLUMNS, "branch": "Аптека"}, "branch_id": None},
        format="json",
    )
    assert made.status_code == 400


def test_cashier_codes_map_once_through_the_api(pharmacy, owner_api):
    imported(pharmacy, line(cashier="K09"))
    client = owner_api(pharmacy.owner)
    [row] = client.get(url(pharmacy.company, "pos-cashiers/")).json()
    assert row["code"] == "K09" and row["member"] is None and row["receipts"] == 1
    changed = client.patch(
        url(pharmacy.company, f"pos-cashiers/{row['id']}/"),
        {"member_id": pharmacy.cashier.pk},
        format="json",
    )
    assert changed.status_code == 200, changed.content
    assert changed.json()["member"]["id"] == pharmacy.cashier.pk
    assert PosCashier.objects.get(pk=row["id"]).membership_id == pharmacy.cashier.pk
    assert AuditLog.objects.filter(action="sales.cashier_mapped").exists()


def test_the_settings_carry_where_lines_come_from(pharmacy, owner_api):
    client = owner_api(pharmacy.owner)
    got = client.get(url(pharmacy.company, "settings/")).json()
    assert got["sales_lines"] == "import"
    changed = client.patch(
        url(pharmacy.company, "settings/"), {"sales_lines": "none"}, format="json"
    )
    assert changed.status_code == 200 and changed.json()["sales_lines"] == "none"
    refused = client.patch(
        url(pharmacy.company, "settings/"), {"sales_lines": "receipts"}, format="json"
    )
    assert refused.status_code == 400
    assert client.get(url(pharmacy.company, "options/")).json()["settings"]["sales_lines"] == "none"
