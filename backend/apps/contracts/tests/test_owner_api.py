"""The owner API of business contracts: the flows, permissions (403), another company's ids
(404), branch scope, files and who may open them, and the shapes the dashboard reads."""

from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.contracts import services
from apps.contracts.models import BusinessContract, ContractFile
from apps.core.files import signed_url

pytestmark = pytest.mark.django_db
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


def base(company) -> str:
    return f"/api/v1/owner/companies/{company.pk}/contracts"


def pdf(name="scan.pdf"):
    return SimpleUploadedFile(name, PDF, content_type="application/pdf")


@pytest.fixture
def far(shop, owner, yunusobod):
    """The Yunusobod lease, in dollars, 1 400 a month."""
    return services.create_contract(
        shop,
        by=owner,
        kind="lease",
        title="Yunusobod ijarasi",
        branch=yunusobod,
        starts_on=date(2026, 1, 1),
        ends_on=date(2026, 12, 21),
        amount=Decimal(1400),
        currency="USD",
    )


def test_add_a_lease_with_its_rent_in_the_forecast(shop, owner, owner_api, chilonzor, bank):
    client = owner_api(owner)
    reply = client.post(
        f"{base(shop)}/",
        {
            "kind": "lease",
            "title": "Chilonzor dorixonasi ijarasi",
            "branch": chilonzor.pk,
            "counterparty_name": "Rustam Qodirov (ijara)",
            "number": "IJ-2026/14",
            "signed_on": "2025-12-20",
            "starts_on": "2026-01-01",
            "ends_on": "2026-12-31",
            "amount": "9000000",
            "period": "monthly",
            "payment_day": 3,
            "in_forecast": True,
            "account": bank.pk,
        },
        format="json",
    )
    assert reply.status_code == 201, reply.content
    data = reply.json()
    assert data["status"] == "active"
    assert data["amount"] == "9000000.00"
    assert data["per_month"] == "9000000.00"
    assert data["counterparty"]["name"] == "Rustam Qodirov (ijara)"
    assert data["rule"]["account"]["id"] == bank.pk
    assert data["rule"]["next_due_on"] == "2026-12-03"
    assert data["payments"]["count"] == 0
    assert data["can"] == {"manage": True}
    assert [item["key"] for item in data["dates"]] == ["signed", "starts", "ends"]
    assert data["key_day"] == "2026-12-31" and data["days_left"] == 54

    rows = client.get(f"{base(shop)}/").json()
    assert [row["id"] for row in rows] == [data["id"]]
    assert rows[0]["has_rule"] is True and rows[0]["files"] == 0


def test_change_renew_terminate_and_delete(shop, owner, owner_api, lease):
    client = owner_api(owner)
    url = f"{base(shop)}/{lease.pk}/"
    reply = client.patch(url, {"auto_renews": True, "notice_days": 60}, format="json")
    assert reply.status_code == 200, reply.content
    assert reply.json()["notice_deadline"] == "2026-11-01"
    assert reply.json()["key_day"] == "2026-11-01"
    reply = client.post(f"{url}keep-renewing/", format="json")
    assert reply.status_code == 200 and reply.json()["renewal_confirmed"] is True
    reply = client.post(f"{url}stop-renewing/", format="json")
    assert reply.status_code == 200 and reply.json()["auto_renews"] is False
    reply = client.post(f"{url}renew/", {"ends_on": "2027-12-31"}, format="json")
    assert reply.status_code == 200 and reply.json()["ends_on"] == "2027-12-31"
    reply = client.post(f"{url}renew/", {"ends_on": "2027-01-01"}, format="json")
    assert reply.status_code == 400  # not after the current end
    reply = client.post(
        f"{url}terminate/", {"on": "2026-11-30", "reason": "Ko‘chamiz"}, format="json"
    )
    assert reply.status_code == 200
    assert reply.json()["status"] == "ending"
    assert reply.json()["termination_reason"] == "Ko‘chamiz"
    assert [item["key"] for item in reply.json()["dates"]][-1] == "terminated"
    assert client.delete(url).status_code == 204
    assert not BusinessContract.objects.filter(pk=lease.pk).exists()


def test_the_list_filters(shop, owner, owner_api, lease, far, freeze):
    client = owner_api(owner)
    services.create_contract(
        shop,
        by=owner,
        kind="supply",
        title="Ko‘kterak Farm",
        counterparty_name="Ko‘kterak Farm Distribyutor",
        starts_on=date(2026, 1, 1),
    )

    def ids(**params):
        return [row["id"] for row in client.get(f"{base(shop)}/", params).json()]

    assert len(ids()) == 3
    assert ids(kind="lease") == [far.pk, lease.pk]  # soonest date first (21 and 31 December)
    assert ids(branch=far.branch_id) == [far.pk]
    assert ids(q="kokterak") == [] and len(ids(q="Ko‘kterak")) == 1
    assert ids(ending="1") == []
    services.update_settings(shop, by=owner, remind_days=45)
    assert ids(ending="1") == [far.pk]  # 44 days to 21 December
    rows = client.get(f"{base(shop)}/", {"ending": "1"}).json()
    assert rows[0]["attention"] == "ending" and rows[0]["status"] == "ending"
    services.terminate(lease, by=owner, on=date(2026, 11, 7))
    assert lease.pk not in ids()  # current: draft, active, ending
    assert ids(status="terminated") == [lease.pk]
    assert len(ids(status="all")) == 3
    assert client.get(f"{base(shop)}/", {"status": "nope"}).status_code == 400

    summary = client.get(f"{base(shop)}/summary/").json()
    assert summary["in_force"] == 2
    assert summary["ending_soon"] == 1
    assert summary["counts"]["terminated"] == 1
    assert summary["currency"] == "UZS"


def test_files_are_private_and_checked_when_opened(
    shop, owner, owner_api, client, lease, far, manager, other_company, member
):
    api = owner_api(owner)
    reply = api.post(
        f"{base(shop)}/{lease.pk}/files/", {"file": pdf(), "kind": "signed", "label": "Asl nusxa"}
    )
    assert reply.status_code == 201, reply.content
    item = reply.json()["file_list"][0]
    assert item["is_pdf"] and item["label"] == "Asl nusxa" and item["size"] == len(PDF)
    opened = client.get(item["url"])
    assert opened.status_code == 200
    assert b"".join(opened.streaming_content) == PDF
    # Not a PDF or a picture: refused.
    bad = SimpleUploadedFile("x.pdf", b"<html><script>", content_type="application/pdf")
    assert api.post(f"{base(shop)}/{lease.pk}/files/", {"file": bad}).status_code == 400

    row = ContractFile.objects.get(contract=lease)
    # The Chilonzor manager may open Chilonzor's file, not Yunusobod's.
    far_row = services.add_file(far, by=owner, file=pdf(), kind="annex")

    def link(person, file_row, company_id=None):
        return signed_url(
            file_row.file,
            user=person.user,
            company_id=company_id or shop.pk,
            check=f"contracts.file:{file_row.pk}",
        )

    assert client.get(link(manager, row)).status_code == 200
    assert client.get(link(manager, far_row)).status_code in (403, 404)
    # Someone of another company: neither through the API nor through a link.
    stranger = member(other_company, "Owner")
    assert owner_api(stranger).delete(f"{base(other_company)}/files/{row.pk}/").status_code == 404
    assert client.get(link(stranger, row, other_company.pk)).status_code in (403, 404)
    # The manager can't remove a file of a branch they don't see.
    assert owner_api(manager).delete(f"{base(shop)}/files/{far_row.pk}/").status_code == 404
    assert api.delete(f"{base(shop)}/files/{row.pk}/").status_code == 204
    assert not ContractFile.objects.filter(pk=row.pk).exists()


def test_another_companys_contract_is_not_found(
    shop, owner, owner_api, lease, other_company, member
):
    stranger = member(other_company, "Owner")
    client = owner_api(stranger)
    url = f"{base(other_company)}/{lease.pk}/"
    assert client.get(url).status_code == 404
    assert client.patch(url, {"title": "x"}, format="json").status_code == 404
    assert client.post(f"{url}terminate/", {"on": "2026-11-07"}, format="json").status_code == 404
    assert client.delete(url).status_code == 404
    # Its own company's URL with the other id: no membership there.
    assert client.get(f"{base(shop)}/{lease.pk}/").status_code == 404


def test_permissions(shop, owner_api, lease, reader, ali):
    client = owner_api(reader)  # finance.view only
    assert client.get(f"{base(shop)}/").status_code == 200
    detail = client.get(f"{base(shop)}/{lease.pk}/").json()
    assert detail["can"] == {"manage": False}
    assert (
        client.patch(f"{base(shop)}/{lease.pk}/", {"title": "x"}, format="json").status_code == 403
    )
    assert client.post(f"{base(shop)}/", {"title": "x"}, format="json").status_code == 403
    assert client.get(f"{base(shop)}/options/").status_code == 403
    assert (
        client.patch(f"{base(shop)}/settings/", {"remind_days": 10}, format="json").status_code
        == 403
    )
    assert client.get(f"{base(shop)}/settings/").status_code == 200
    # Without money permissions there is nothing to see (rent, payments).
    assert owner_api(ali).get(f"{base(shop)}/").status_code in (403, 404)


def test_branch_scope(shop, owner, owner_api, manager, lease, far, chilonzor):
    company_wide = services.create_contract(
        shop, by=owner, kind="insurance", title="Sug‘urta", starts_on=date(2026, 1, 1)
    )
    client = owner_api(manager)  # Chilonzor only
    assert [row["id"] for row in client.get(f"{base(shop)}/").json()] == [lease.pk]
    assert client.get(f"{base(shop)}/{far.pk}/").status_code == 404
    assert client.get(f"{base(shop)}/{company_wide.pk}/").status_code == 404
    assert client.get(f"{base(shop)}/", {"branch": far.branch_id}).status_code == 404
    # Adding: only for their branch, and a branch is a must.
    reply = client.post(
        f"{base(shop)}/",
        {"kind": "service", "title": "Tozalash", "starts_on": "2026-01-01"},
        format="json",
    )
    assert reply.status_code == 400 and "branch" in reply.json()
    reply = client.post(
        f"{base(shop)}/",
        {
            "kind": "service",
            "title": "Tozalash",
            "starts_on": "2026-01-01",
            "branch": far.branch_id,
        },
        format="json",
    )
    assert reply.status_code == 400
    reply = client.post(
        f"{base(shop)}/",
        {"kind": "service", "title": "Tozalash", "starts_on": "2026-01-01", "branch": chilonzor.pk},
        format="json",
    )
    assert reply.status_code == 201
    summary = client.get(f"{base(shop)}/summary/").json()
    assert summary["total"] == 2


def test_options_and_settings(shop, owner, owner_api, lease, bank, dollars):
    client = owner_api(owner)
    options = client.get(f"{base(shop)}/options/").json()
    assert options["finance"] is True
    assert any(row["system_code"] == "rent" for row in options["categories"])
    assert {row["currency"] for row in options["accounts"]} == {"UZS", "USD"}
    assert [row["name"] for row in options["parties"]] == ["Rustam Qodirov (ijara)"]
    reply = client.patch(
        f"{base(shop)}/settings/", {"remind_days": 45, "notice_remind_days": 21}, format="json"
    )
    assert reply.json() == {"remind_days": 45, "notice_remind_days": 21}
    assert (
        client.patch(f"{base(shop)}/settings/", {"remind_days": 0}, format="json").status_code
        == 400
    )


def test_the_history_tab_reads_its_audit(shop, owner, owner_api, manager, far, lease):
    def history(person, contract):
        return owner_api(person).get(
            f"/api/v1/owner/companies/{shop.pk}/audit/records/",
            {"target_type": "businesscontract", "target_id": contract.pk},
        )

    reply = history(owner, lease)
    assert reply.status_code == 200, reply.content
    assert "contracts.created" in str(reply.json())
    # A contract outside the manager's branches has no history for them.
    assert history(manager, far).status_code in (403, 404)


def test_a_file_downloads_under_a_readable_name(shop, owner, owner_api, client, lease):
    reply = owner_api(owner).post(
        f"{base(shop)}/{lease.pk}/files/", {"file": pdf(), "kind": "annex", "label": "Ijara haqi"}
    )
    opened = client.get(reply.json()["file_list"][0]["url"])
    disposition = opened["Content-Disposition"]
    assert 'filename="Chilonzor dorixonasi ijarasi - Ijara haqi.pdf"' in disposition
