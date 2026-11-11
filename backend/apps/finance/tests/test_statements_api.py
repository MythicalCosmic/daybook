"""The reports for banks and investors (v12) over the owner API: the balance sheet, what the
business is worth and the statement packs; tenancy, permissions, branch scope, audit, the pack's
build, its download check, Telegram and pruning."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.companies.models import Branch
from apps.core.storage import private_storage
from apps.finance import queries, services, statement_pack
from apps.finance.models import MoneyAccount, StatementPack
from apps.finance.tests.factories import MoneyAccountFactory
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db

D = Decimal


def url(company, path: str) -> str:
    return f"/api/v1/owner/companies/{company.pk}/finance/{path}"


@pytest.fixture
def today(fin):
    return queries.local_today(fin)


@pytest.fixture
def boss(fin, member):
    return member(fin, "Owner", first_name="Dilnoza")


@pytest.fixture
def client(owner_api, boss):
    return owner_api(boss)


@pytest.fixture
def branches(fin):
    first = fin.branches.order_by("pk").first()
    second = Branch.objects.create(company=fin, name="Yunusobod", order=1)
    return first, second


@pytest.fixture
def books_of_two(fin, boss, branches, today):
    """A company account and one till per branch, each with a sale; a supplier on credit."""
    first, second = branches
    kassa = MoneyAccount.objects.get(company=fin, kind=MoneyAccount.Kind.CASH)
    tills = [
        MoneyAccountFactory(company=fin, name=f"Till {branch.name}", kind="cash", branch=branch)
        for branch in (first, second)
    ]
    start = today - timedelta(days=90)
    services.record_transaction(
        fin, by=boss, kind="opening", amount=D("5000000"), occurred_on=start, account=kassa
    )
    for till, amount in zip(tills, ("700000", "300000"), strict=True):
        services.record_transaction(
            fin,
            by=boss,
            kind="income",
            amount=D(amount),
            occurred_on=today,
            account=till,
            category="sales",
            branch=till.branch,
        )
    return {"kassa": kassa, "tills": tills}


def scoped(fin, role, person, branch, perms):
    return person(fin, role(fin, "Head", perms), branches=[branch])


class TestBalanceSheet:
    def test_the_owner_reads_it_with_money_as_strings(self, client, fin, books_of_two):
        body = client.get(url(fin, "reports/balance-sheet/")).json()
        assert body["whole_company"] is True
        assert body["assets"]["total"] == "6000000.00"
        assert body["check"]["balanced"] is True
        assert body["equity"]["lines"][-1] == {"key": "retained", "amount": "6000000.00"}
        assert {"key": "no_stock_module", "params": {}} in body["gaps"]

    def test_another_companys_id_answers_404(self, owner_api, member, other_company, fin):
        stranger = member(other_company, "Owner")
        assert owner_api(stranger).get(url(fin, "reports/balance-sheet/")).status_code == 404

    def test_without_finance_view_it_answers_403(self, owner_api, fin, role, person):
        recorder = person(fin, role(fin, "Recorder", [Perm.FINANCE_RECORD]))
        assert owner_api(recorder).get(url(fin, "reports/balance-sheet/")).status_code == 403

    def test_the_finance_module_off_answers_404(self, client, fin):
        fin.features = []
        fin.save(update_fields=["features"])
        assert client.get(url(fin, "reports/balance-sheet/")).status_code == 404

    def test_a_branch_head_sees_their_branch_only(
        self, owner_api, fin, role, person, branches, books_of_two
    ):
        head = scoped(fin, role, person, branches[0], [Perm.FINANCE_VIEW])
        body = owner_api(head).get(url(fin, "reports/balance-sheet/")).json()
        assert body["whole_company"] is False
        assert body["assets"]["total"] == "700000.00"
        assert [row["name"] for row in body["accounts"]] == ["Till " + branches[0].name]
        assert body["reconciliation"] is None
        assert body["equity"]["lines"] == [{"key": "net_assets", "amount": "700000.00"}]

    def test_the_owner_narrows_it_to_a_branch(self, client, fin, branches, books_of_two):
        body = client.get(url(fin, f"reports/balance-sheet/?branch={branches[1].pk}")).json()
        assert body["assets"]["total"] == "300000.00"

    def test_a_past_day(self, client, fin, books_of_two, today):
        day = (today - timedelta(days=1)).isoformat()
        body = client.get(url(fin, f"reports/balance-sheet/?on={day}")).json()
        assert body["on"] == day
        assert body["assets"]["total"] == "5000000.00"


class TestValuation:
    def test_the_owner_sees_both_methods(self, client, fin, books_of_two):
        body = client.get(url(fin, "valuation/")).json()
        assert body["multiple_low"] == "2.0" and body["multiple_high"] == "3.0"
        assert body["net_assets"]["value"] == "6000000.00"
        assert body["earnings_method"]["applies"] is True  # 90 days of books, a profit
        assert body["editable"] is True
        assert D(body["range"]["low"]) <= D(body["range"]["high"])

    def test_a_branch_head_may_not_value_the_whole_business(
        self, owner_api, fin, role, person, branches
    ):
        head = scoped(fin, role, person, branches[0], [Perm.FINANCE_VIEW])
        assert owner_api(head).get(url(fin, "valuation/")).status_code == 403

    def test_the_owner_changes_the_multiples_and_it_is_audited(self, client, fin, books_of_two):
        response = client.patch(
            url(fin, "valuation/"), {"multiple_low": "3.5", "multiple_high": "1.5"}, format="json"
        )
        assert response.status_code == 200
        assert (response.json()["multiple_low"], response.json()["multiple_high"]) == (
            "1.5",
            "3.5",
        )
        log = AuditLog.objects.get(company=fin, action="finance.valuation_set")
        assert log.details["after"] == {"multiple_low": "1.5", "multiple_high": "3.5"}
        back = client.patch(
            url(fin, "valuation/"), {"multiple_low": None, "multiple_high": None}, format="json"
        )
        assert back.json()["multiple_low"] == "2.0"

    def test_changing_them_needs_finance_manage(self, owner_api, fin, role, person):
        viewer = person(fin, role(fin, "Viewer", [Perm.FINANCE_VIEW, Perm.BRANCHES_ALL]))
        api = owner_api(viewer)
        assert api.get(url(fin, "valuation/")).json()["editable"] is False
        response = api.patch(url(fin, "valuation/"), {"multiple_low": "4"}, format="json")
        assert response.status_code == 403

    def test_a_multiple_out_of_range_is_refused(self, client, fin):
        response = client.patch(url(fin, "valuation/"), {"multiple_high": "50"}, format="json")
        assert response.status_code == 400


@pytest.fixture
def ask(django_capture_on_commit_callbacks):
    """POST statements/ and run what waits for the commit (the build, in eager Celery)."""

    def post(client, fin, today, **extra):
        body = {"period": "month", "of": today.isoformat(), "purpose": "bank", "language": "uz"}
        with django_capture_on_commit_callbacks(execute=True):
            return client.post(url(fin, "statements/"), {**body, **extra}, format="json")

    return post


class TestStatementPacks:
    def test_options(self, ask, client, fin, books_of_two, today):
        body = client.get(url(fin, "statements/options/")).json()
        assert body["may_prepare"] is True
        assert body["whole_company"] is True
        assert body["books_start"] == (today - timedelta(days=90)).isoformat()

    def test_a_pack_is_prepared_audited_and_downloaded(
        self, ask, client, fin, boss, books_of_two, today
    ):
        response = ask(client, fin, today, purpose="sale", language="en")
        assert response.status_code == 202
        pack = StatementPack.objects.get(pk=response.json()["id"])
        # Celery runs eagerly in tests: the pack is built already.
        assert pack.status == "ready" and pack.progress == 100 and pack.pages >= 6
        assert private_storage.open(pack.file.name).read(4) == b"%PDF"
        assert AuditLog.objects.filter(
            company=fin, action="finance.statements_prepared", target_id=str(pack.pk)
        ).exists()
        detail = client.get(url(fin, f"statements/{pack.pk}/")).json()
        assert detail["status"] == "ready"
        assert detail["file_url"].startswith("/api/v1/files/")
        assert detail["file_name"].endswith(".pdf")
        download = client.get(detail["file_url"])
        assert download.status_code == 200
        assert b"".join(download.streaming_content)[:4] == b"%PDF"
        assert [row["id"] for row in client.get(url(fin, "statements/")).json()] == [pack.pk]

    def test_it_needs_the_export_permission(self, ask, owner_api, fin, role, person, today):
        viewer = person(fin, role(fin, "Viewer", [Perm.FINANCE_VIEW]))
        api = owner_api(viewer)
        assert api.get(url(fin, "statements/options/")).json()["may_prepare"] is False
        assert ask(api, fin, today).status_code == 403
        assert not StatementPack.objects.exists()

    def test_without_finance_view_it_answers_403(self, ask, owner_api, fin, role, person, today):
        exporter = person(fin, role(fin, "Exporter", [Perm.DATA_EXPORT, Perm.FINANCE_RECORD]))
        assert ask(owner_api(exporter), fin, today).status_code == 403

    def test_another_companys_id_answers_404(
        self, ask, owner_api, member, other_company, fin, today
    ):
        stranger = member(other_company, "Owner")
        assert ask(owner_api(stranger), fin, today).status_code == 404

    def test_someone_elses_pack_answers_404(
        self, ask, client, owner_api, member, fin, books_of_two, today
    ):
        pack_id = ask(client, fin, today).json()["id"]
        colleague = member(fin, "Owner")
        assert owner_api(colleague).get(url(fin, f"statements/{pack_id}/")).status_code == 404
        pack = StatementPack.objects.get(pk=pack_id)
        assert statement_pack.can_download(pack.requested_by.user, fin.pk, pack_id)
        assert not statement_pack.can_download(colleague.user, fin.pk, pack_id)
        assert not statement_pack.can_download(pack.requested_by.user, fin.pk + 1, pack_id)
        assert not statement_pack.can_download(pack.requested_by.user, fin.pk, "x")

    def test_a_branch_head_packs_their_branch(
        self, ask, owner_api, fin, role, person, branches, books_of_two, today
    ):
        head = scoped(fin, role, person, branches[0], [Perm.FINANCE_VIEW, Perm.DATA_EXPORT])
        api = owner_api(head)
        assert api.get(url(fin, "statements/options/")).json()["whole_company"] is False
        refused = ask(api, fin, today, branch=[branches[1].pk])
        assert refused.status_code == 400
        pack = StatementPack.objects.get(pk=ask(api, fin, today).json()["id"])
        assert pack.params["branch"] == [branches[0].pk]
        assert pack.status == "ready"

    def test_a_period_not_started_or_unknown_is_refused(
        self, ask, client, fin, books_of_two, today
    ):
        assert (
            ask(client, fin, today, of=(today + timedelta(days=400)).isoformat()).status_code == 400
        )
        assert ask(client, fin, today, language="de").status_code == 400
        assert ask(client, fin, today, purpose="tax").status_code == 400

    def test_empty_books_have_nothing_to_report(self, ask, client, fin, today):
        assert ask(client, fin, today).status_code == 400

    def test_it_goes_to_the_owner_bot_when_asked(
        self, ask, client, fin, boss, books_of_two, today, monkeypatch, settings
    ):
        settings.OWNER_BOT_TOKEN = "123:owner"
        boss.user.telegram_id = 99001
        boss.user.owner_bot_started_at = timezone.now()
        boss.user.save()
        sent = []
        monkeypatch.setattr(
            "apps.notifications.telegram.send_document", lambda *a, **k: sent.append((a, k))
        )
        ask(client, fin, today, deliver_telegram=True)
        assert sent and sent[0][0][0] == "owner"
        assert sent[0][1]["filename"].endswith(".pdf")

    def test_a_pack_stops_when_the_permission_goes(
        self, ask, owner_api, fin, role, person, books_of_two, today, monkeypatch
    ):
        perms = [Perm.FINANCE_VIEW, Perm.DATA_EXPORT, Perm.BRANCHES_ALL]
        accountant = person(fin, role(fin, "Bookkeeper", perms))
        monkeypatch.setattr("apps.finance.tasks.build_statement_pack.delay", lambda pk: None)
        body = {"period": "month", "of": today.isoformat(), "purpose": "bank", "language": "ru"}
        pack_id = (
            owner_api(accountant).post(url(fin, "statements/"), body, format="json").json()["id"]
        )
        accountant.role.permissions = [Perm.DASHBOARD_ACCESS, Perm.FINANCE_VIEW]
        accountant.role.save()
        statement_pack.build(pack_id)
        pack = StatementPack.objects.get(pk=pack_id)
        assert pack.status == "failed" and not pack.file

    def test_old_packs_are_pruned_and_stuck_ones_fail(self, ask, client, fin, books_of_two, today):
        old = StatementPack.objects.get(pk=ask(client, fin, today).json()["id"])
        StatementPack.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=8)
        )
        stuck = StatementPack.objects.create(
            company=fin,
            requested_by=old.requested_by,
            period="month",
            start=date(today.year, today.month, 1),
            end=today,
            purpose="bank",
            language="ru",
        )
        StatementPack.objects.filter(pk=stuck.pk).update(
            created_at=timezone.now() - timedelta(hours=3)
        )
        assert statement_pack.prune() == 1
        assert not StatementPack.objects.filter(pk=old.pk).exists()
        assert not private_storage.exists(old.file.name)
        stuck.refresh_from_db()
        assert stuck.status == "failed"

    def test_pruning_runs_from_beat(self, ask, settings):
        entry = settings.CELERY_BEAT_SCHEDULE["finance-prune-statement-packs"]
        assert entry["task"] == "apps.finance.tasks.prune_statement_packs"


def test_the_balance_sheet_export_is_registered(client, fin, books_of_two):
    response = client.get(f"/api/v1/owner/companies/{fin.pk}/exports/kinds/")
    kinds = {row["kind"]: row for row in response.json()}
    assert "finance.balance_sheet" in kinds
    from apps.exports.registry import get_exporter

    rows = list(get_exporter("finance.balance_sheet").rows(fin.memberships.first(), {}))
    assert rows[-1]["amount"] == D("6000000.00")
