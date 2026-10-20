"""Exports: the registry, requesting one (audited), building xlsx/csv, Telegram and pruning."""

import csv
import io
from datetime import datetime, timedelta
from decimal import Decimal
from types import ModuleType

import pytest
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.utils import timezone
from openpyxl import load_workbook
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.console import compat
from apps.console.registry import BadKey, DuplicateKey, RegistryError
from apps.core.exceptions import DomainError
from apps.core.storage import private_storage
from apps.exports import build, files, housekeeping, services
from apps.exports.models import Export
from apps.exports.registry import register_exporter

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(company, member):
    return member(company, "Owner")


@pytest.fixture
def accountant(company, member):
    return member(company, "Accountant")  # data.export, payroll.view; no tasks.view_all


def exports_url(company, path="") -> str:
    return f"/api/v1/owner/companies/{company.pk}/exports/{path}"


# Registry -------------------------------------------------------------------------------


@pytest.mark.usefixtures("isolated_registries")
def test_exporter_rules():
    def rows(member, params):
        return []

    register_exporter("exports.a", perm=None, label="A", columns=[("x", "X")], rows=rows)
    with pytest.raises(DuplicateKey):
        register_exporter("exports.a", perm=None, label="A", columns=[("x", "X")], rows=rows)
    with pytest.raises(BadKey):
        register_exporter("tasks.a", perm=None, label="A", columns=[("x", "X")], rows=rows)
    with pytest.raises(RegistryError):
        register_exporter("exports.b", perm=None, label="B", columns=[], rows=rows)
    with pytest.raises(RegistryError):
        register_exporter(
            "exports.c", perm=None, label="C", columns=[("x", "X"), ("x", "Y")], rows=rows
        )
    with pytest.raises(RegistryError):
        register_exporter(
            "exports.d", perm=None, label="D", columns=[("x", "X")], rows=rows, formats=("pdf",)
        )
    with pytest.raises(ValueError):
        register_exporter(
            "exports.e", perm=None, label="E", columns=[("x", "X", "html")], rows=rows
        )


# Requesting -----------------------------------------------------------------------------


@pytest.mark.usefixtures("exporters")
def test_requesting_an_export_is_audited_and_queues_the_build(
    owner, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        export = services.request_export(
            owner, "exports.tasks", format="xlsx", params={"status": "todo"}
        )

    assert (export.status, export.sensitive, export.requested_by) == ("pending", False, owner)
    log = AuditLog.objects.get(action="data.exported")
    assert log.actor == owner.user and log.target_id == export.pk
    assert log.details == {
        "kind": "exports.tasks",
        "format": "xlsx",
        "params": {"status": "todo"},
        "sensitive": False,
        "deliver_telegram": False,
    }
    assert len(callbacks) == 2  # the build and the pulse bump


@pytest.mark.usefixtures("exporters")
def test_exporting_needs_data_export_and_the_exporters_permission(company, member, accountant):
    manager = member(company, "Manager")  # tasks.view_all but no data.export

    with pytest.raises(services.PermissionDenied):
        services.request_export(manager, "exports.tasks", format="csv")
    with pytest.raises(services.PermissionDenied):
        services.request_export(accountant, "exports.tasks", format="csv")
    assert services.request_export(accountant, "exports.salaries", format="csv").sensitive


@pytest.mark.usefixtures("exporters")
def test_unknown_kinds_formats_modules_and_params_are_refused(owner):
    with pytest.raises(DomainError):
        services.request_export(owner, "exports.nothing", format="csv")
    with pytest.raises(DomainError):
        services.request_export(owner, "exports.tasks", format="zip")
    with pytest.raises(services.PermissionDenied):
        services.request_export(owner, "exports.sales_only", format="csv")  # module off
    with pytest.raises(ValidationError):
        services.request_export(owner, "exports.tasks", format="csv", params={"status": "lost"})
    assert not Export.objects.exists()


# Building -------------------------------------------------------------------------------


def built(member, kind="exports.tasks", format="xlsx", **kwargs) -> Export:
    export = services.request_export(member, kind, format=format, **kwargs)
    build.build(export.pk)
    export.refresh_from_db()
    return export


def test_xlsx_has_typed_cells_and_no_formulas(owner, exporters):
    export = built(owner, params={"status": "todo"})

    assert (export.status, export.rows, export.error) == ("ready", 2, "")
    assert export.file.name.startswith(
        f"exports/{owner.company_id}/"
    ) and export.file.name.endswith(".xlsx")
    assert exporters.calls == [(owner.pk, {"status": "todo"})]
    with private_storage.open(export.file.name, "rb") as file:
        sheet = load_workbook(file).active
    assert sheet.title == "Tasks  today all"
    assert [cell.value for cell in sheet[1]] == [
        "Title",
        "Amount",
        "Due",
        "Done at",
        "Done",
        "Count",
    ]
    first = [cell.value for cell in sheet[2]]
    assert first[0] == "Count the till"
    assert first[1] == Decimal("1250000.5") or first[1] == 1250000.5
    assert sheet["B2"].number_format == "#,##0.00"
    assert first[2] == datetime(2026, 10, 20)
    assert first[3] == datetime(2026, 10, 20, 9, 30)  # the company's wall clock
    assert (first[4], first[5]) == (True, 3)
    assert sheet["A3"].value == '=HYPERLINK("http://evil")'
    assert sheet["A3"].data_type == "s"  # stays text, never runs


def test_csv_has_a_bom_and_defuses_formulas(owner, exporters):
    export = built(owner, format="csv")

    with private_storage.open(export.file.name, "rb") as file:
        raw = file.read()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    assert rows[0] == ["Title", "Amount", "Due", "Done at", "Done", "Count"]
    assert rows[1] == ["Count the till", "1250000.50", "2026-10-20", "2026-10-20 09:30", "Yes", "3"]
    assert rows[2] == ['\'=HYPERLINK("http://evil")', "", "", "", "No", ""]


def test_a_failing_exporter_fails_the_export_with_a_safe_message(owner, exporters, caplog):
    exporters.rows = [{"title": "ok", "amount": "not money"}]

    export = built(owner)

    assert export.status == "failed"
    assert export.error == "Something went wrong while building this export."
    assert not export.file
    assert "Export" in caplog.text


def test_losing_the_permission_before_the_build_fails_it(owner, exporters):
    export = services.request_export(owner, "exports.tasks", format="csv")
    owner.status = owner.Status.BLOCKED
    owner.save()

    build.build(export.pk)

    export.refresh_from_db()
    assert export.status == "failed"
    assert "no longer have permission" in export.error
    assert exporters.calls == []


def test_too_many_rows_fail_with_a_hint(owner, exporters, monkeypatch):
    monkeypatch.setattr(build, "MAX_ROWS", 1)

    export = built(owner, format="csv")

    assert export.status == "failed"
    assert "narrow the filters" in export.error


def test_a_build_runs_once(owner, exporters):
    export = built(owner, format="csv")
    build.build(export.pk)

    assert len(exporters.calls) == 1


def test_the_file_goes_to_telegram_only_when_asked(owner, exporters, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "apps.notifications.telegram.send_document",
        lambda *args, **kwargs: sent.append((args, kwargs)),
    )

    built(owner, format="csv")
    assert sent == []

    export = built(owner, format="csv", deliver_telegram=True)
    [(args, kwargs)] = sent
    assert args == ("employee", owner.user.telegram_id, export.file.name)
    assert kwargs["storage"] == "private"
    assert kwargs["filename"] == f"tasks-todayall-{timezone.localdate():%Y-%m-%d}.csv"
    assert kwargs["caption"] == "Tasks: today/all · 2 rows"


def test_telegram_delivery_prefers_the_owner_bot(owner, exporters, monkeypatch, settings):
    settings.OWNER_BOT_TOKEN = "2:OWNER"
    owner.user.owner_bot_started_at = timezone.now()
    owner.user.save()
    sent = []
    monkeypatch.setattr("apps.notifications.telegram.send_document", lambda *a, **k: sent.append(a))

    built(owner, kind="exports.salaries", format="xlsx", deliver_telegram=True)

    assert sent[0][0] == "owner"


def test_the_requester_alone_may_download(company, member, owner, exporters):
    export = built(owner, format="csv")
    colleague = member(company, "Owner")

    assert files.can_download(owner.user, company.pk, export.pk)
    assert files.can_download(owner.user, company.pk, str(export.pk))
    assert not files.can_download(colleague.user, company.pk, export.pk)
    assert not files.can_download(owner.user, company.pk + 1, export.pk)
    assert not files.can_download(owner.user, company.pk, "x")


def test_download_stops_when_the_permission_goes(company, accountant, exporters):
    export = built(accountant, kind="exports.salaries", format="csv")
    accountant.role.permissions.remove("payroll.view")
    accountant.role.save()

    assert not files.can_download(accountant.user, company.pk, export.pk)


# Pruning --------------------------------------------------------------------------------


def test_old_exports_and_their_files_are_pruned(owner, exporters):
    old = built(owner, format="csv")
    fresh = built(owner, format="csv")
    Export.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=8))
    stuck = services.request_export(owner, "exports.tasks", format="csv")
    Export.objects.filter(pk=stuck.pk).update(created_at=timezone.now() - timedelta(hours=7))

    assert housekeeping.prune_exports() == 1

    assert not Export.objects.filter(pk=old.pk).exists()
    assert not private_storage.exists(old.file.name)
    assert private_storage.exists(fresh.file.name)
    stuck.refresh_from_db()
    assert stuck.status == "failed" and "too long" in stuck.error


def test_pruning_runs_from_beat(settings):
    assert (
        settings.CELERY_BEAT_SCHEDULE["exports-prune"]["task"] == "apps.exports.tasks.prune_exports"
    )


# API ------------------------------------------------------------------------------------


@pytest.mark.usefixtures("exporters")
def test_post_returns_202_with_the_id(
    company, owner, owner_api, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = owner_api(owner).post(
            exports_url(company), {"kind": "exports.tasks", "format": "csv"}, format="json"
        )

    assert response.status_code == 202
    export = Export.objects.get(pk=response.data["id"])
    assert export.status == "ready"  # built eagerly in tests


@pytest.mark.usefixtures("exporters")
def test_post_needs_data_export_and_the_exporters_permission(
    company, member, accountant, owner_api
):
    manager = member(company, "Manager")
    body = {"kind": "exports.tasks", "format": "csv"}

    assert owner_api(manager).post(exports_url(company), body, format="json").status_code == 403
    assert owner_api(accountant).post(exports_url(company), body, format="json").status_code == 403


@pytest.mark.usefixtures("exporters")
def test_post_validates_the_request(company, owner, owner_api):
    client = owner_api(owner)

    assert (
        client.post(
            exports_url(company), {"kind": "exports.nothing", "format": "csv"}, format="json"
        ).status_code
        == 400
    )
    assert (
        client.post(
            exports_url(company), {"kind": "exports.tasks", "format": "pdf"}, format="json"
        ).status_code
        == 400
    )
    bad_params = {"kind": "exports.tasks", "format": "csv", "params": {"status": "lost"}}
    assert client.post(exports_url(company), bad_params, format="json").status_code == 400


@pytest.mark.usefixtures("exporters")
def test_list_and_detail_show_only_my_exports(company, member, owner, owner_api):
    mine = built(owner, format="csv")
    theirs = built(member(company, "Owner"), format="csv")
    client = owner_api(owner)

    listed = client.get(exports_url(company)).data["results"]
    assert [row["id"] for row in listed] == [mine.pk]
    detail = client.get(exports_url(company, f"{mine.pk}/")).data
    assert (
        detail["status"] == "ready"
        and detail["rows"] == 2
        and detail["label"] == "Tasks: today/all"
    )
    assert detail["file_name"].endswith(".csv")
    assert client.get(exports_url(company, f"{theirs.pk}/")).status_code == 404


@pytest.mark.usefixtures("exporters")
def test_the_detail_carries_a_signed_link(company, owner, owner_api, monkeypatch):
    fake = ModuleType("apps.core.files")
    fake.signed_url = lambda file, *, user, company_id, check, ttl: (
        f"/api/v1/files/{check}:{user.pk}:{ttl}/"
    )
    monkeypatch.setattr(compat, "files", lambda: fake)
    export = built(owner, format="csv")

    detail = owner_api(owner).get(exports_url(company, f"{export.pk}/")).data

    assert detail["file_url"] == f"/api/v1/files/exports.export:{export.pk}:{owner.user_id}:600/"


@pytest.mark.usefixtures("exporters")
def test_no_link_until_ready(company, owner, owner_api):
    export = services.request_export(owner, "exports.tasks", format="csv")

    assert owner_api(owner).get(exports_url(company, f"{export.pk}/")).data["file_url"] is None


@pytest.mark.usefixtures("exporters")
def test_kinds_lists_what_i_may_export(company, owner, accountant, owner_api):
    as_owner = {row["kind"] for row in owner_api(owner).get(exports_url(company, "kinds/")).data}
    as_accountant = owner_api(accountant).get(exports_url(company, "kinds/")).data

    assert {"exports.tasks", "exports.salaries"} <= as_owner
    assert "exports.sales_only" not in as_owner  # module off
    assert [row["kind"] for row in as_accountant if row["kind"].startswith("exports.")] == [
        "exports.salaries"
    ]
    assert as_accountant[0]["sensitive"] is True
    assert as_accountant[0]["columns"][1] == {"key": "salary", "label": "Salary", "kind": "money"}


@pytest.mark.parametrize("path", ["", "kinds/"])
def test_exports_are_company_scoped(company, other_company, member, owner_api, path):
    assert (
        owner_api(member(other_company, "Owner")).get(exports_url(company, path)).status_code == 404
    )
    assert owner_api(member(company, "Manager")).get(exports_url(company, path)).status_code == 403


def test_another_companys_export_is_404(company, other_company, member, exporters, owner_api):
    outsider = member(other_company, "Owner")
    export = built(member(company, "Owner"), format="csv")

    assert owner_api(outsider).get(exports_url(other_company, f"{export.pk}/")).status_code == 404


def test_download_name_survives_a_removed_exporter(owner, exporters):
    export = built(owner, format="csv")
    export.kind = "exports.gone"

    assert build.download_name(export).startswith("exportsgone-")


def test_files_saved_by_hand_get_a_server_chosen_name(owner, exporters):
    export = services.request_export(owner, "exports.tasks", format="csv")
    export.file.save("../../etc/passwd.csv", ContentFile(b"x"), save=False)

    assert export.file.name.startswith(f"exports/{owner.company_id}/")
    assert ".." not in export.file.name and "passwd" not in export.file.name


@pytest.mark.usefixtures("exporters")
def test_asking_for_exports_is_throttled(company, owner, owner_api):
    cache.clear()
    client = owner_api(owner)
    body = {"kind": "exports.tasks", "format": "csv"}

    statuses = [
        client.post(exports_url(company), body, format="json").status_code for _ in range(11)
    ]

    assert statuses[:10] == [202] * 10
    assert statuses[10] == 429
    assert client.get(exports_url(company)).status_code == 200  # reading isn't throttled
