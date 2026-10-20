import time
from types import SimpleNamespace

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from apps.core import files
from apps.core.files import (
    DuplicateFileCheck,
    PrivateFileSerializerField,
    register_file_check,
    signed_url,
)
from apps.core.storage import private_storage
from apps.members import services as members
from apps.members.models import Membership

pytestmark = pytest.mark.django_db

KIND = "core.testfile"


@pytest.fixture(autouse=True)
def private_root(settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "private"


@pytest.fixture
def allowed(monkeypatch):
    """The test check: object ids in `allowed` may be opened; every call is recorded."""
    state = SimpleNamespace(ids={1}, calls=[])

    def check(user, company_id, object_id):
        state.calls.append((user.pk, company_id, object_id))
        return object_id in state.ids

    monkeypatch.setitem(files._checks, KIND, check)
    return state


@pytest.fixture
def worker(company, member):
    return member.registered(company)


def stored(name: str, data: bytes = b"%PDF-1.7\n%%EOF") -> str:
    return private_storage.save(name, ContentFile(data))


def private_field(name: str):
    return SimpleNamespace(name=name, storage=private_storage)


def link(member, name, *, object_id=1, **kwargs) -> str:
    return signed_url(
        private_field(name),
        user=member.user,
        company_id=member.company_id,
        check=f"{KIND}:{object_id}",
        **kwargs,
    )


def body(response) -> bytes:
    return b"".join(response.streaming_content)


def test_a_signed_link_serves_the_file_to_a_member_who_may_open_it(client, worker, allowed):
    name = stored(f"payslips/{worker.company_id}/abc.pdf")

    url = link(worker, name)
    response = client.get(url)

    assert url.startswith("/api/v1/files/") and url.endswith("/")
    assert response.status_code == 200
    assert body(response) == b"%PDF-1.7\n%%EOF"
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"].startswith("inline")
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Content-Security-Policy"] == "sandbox; default-src 'none'"
    assert response["Cache-Control"] == "private, no-store"
    assert allowed.calls == [(worker.user_id, worker.company_id, 1)]


def test_pictures_open_inline_and_spreadsheets_download(client, worker, allowed):
    photo = client.get(link(worker, stored("r/1/a.jpg", b"\xff\xd8\xff")))
    sheet = client.get(link(worker, stored("r/1/a.xlsx", b"PK\x03\x04")))
    table = client.get(link(worker, stored("r/1/a.csv", b"a,b\n")))

    assert photo["Content-Type"] == "image/jpeg"
    assert photo["Content-Disposition"].startswith("inline")
    assert sheet["Content-Disposition"].startswith("attachment")
    assert table["Content-Disposition"].startswith("attachment")
    assert table["Content-Type"] == "text/csv; charset=utf-8"


def test_the_download_name_can_be_chosen(client, worker, allowed):
    response = client.get(link(worker, stored("r/1/a.pdf"), filename="Oylik — oktabr.pdf"))

    assert "filename*=utf-8''Oylik%20%E2%80%94%20oktabr.pdf" in response["Content-Disposition"]


def test_the_link_stops_working_when_the_person_loses_access(client, company, member, allowed):
    owner = member.registered(company, "Owner")
    worker = member.registered(company)
    url = link(worker, stored("r/1/a.pdf"))
    assert client.get(url).status_code == 200

    members.offboard(worker, by=owner.user)

    assert client.get(url).status_code == 404


def test_the_permission_check_runs_at_download_time(client, worker, allowed):
    url = link(worker, stored("r/1/a.pdf"))
    allowed.ids = set()  # e.g. their role lost hr.view

    assert client.get(url).status_code == 404


@pytest.mark.parametrize(
    "status", [Membership.Status.SUSPENDED, Membership.Status.BLOCKED, Membership.Status.LEFT]
)
def test_only_approved_members_can_open_files(client, worker, allowed, status):
    url = link(worker, stored("r/1/a.pdf"))
    Membership.objects.filter(pk=worker.pk).update(status=status)

    assert client.get(url).status_code == 404


def test_a_deactivated_company_closes_every_link(client, worker, allowed):
    url = link(worker, stored("r/1/a.pdf"))
    type(worker.company).objects.filter(pk=worker.company_id).update(is_active=False)

    assert client.get(url).status_code == 404


def test_a_link_for_another_company_does_not_open(client, worker, other_company, allowed):
    url = signed_url(
        private_field(stored("r/1/a.pdf")),
        user=worker.user,
        company_id=other_company.pk,
        check=f"{KIND}:1",
    )

    assert client.get(url).status_code == 404


def test_tampered_links_are_refused(client, worker, allowed):
    url = link(worker, stored("r/1/a.pdf"))
    token = url.removeprefix("/api/v1/files/").removesuffix("/")
    forged = token[:-3] + ("AAA" if not token.endswith("AAA") else "BBB")

    assert client.get(f"/api/v1/files/{forged}/").status_code == 404
    assert client.get("/api/v1/files/not-a-token/").status_code == 404


def test_expired_links_answer_gone(client, worker, allowed, monkeypatch):
    url = link(worker, stored("r/1/a.pdf"), ttl=60)
    later = time.time() + 61
    monkeypatch.setattr(files.time, "time", lambda: later)

    response = client.get(url)

    assert response.status_code == 410
    assert response["X-Content-Type-Options"] == "nosniff"


def test_a_missing_file_is_not_found(client, worker, allowed):
    assert client.get(link(worker, "r/1/gone.pdf")).status_code == 404


def test_only_get_and_head(client, worker, allowed):
    url = link(worker, stored("r/1/a.pdf"))

    assert client.head(url).status_code == 200
    assert client.post(url).status_code == 405


def test_files_of_other_types_are_never_signed(worker, allowed):
    with pytest.raises(ValueError, match="never served"):
        link(worker, "r/1/page.html")
    with pytest.raises(ValueError, match="never served"):
        link(worker, "r/1/image.svg")


def test_links_need_a_registered_check(worker):
    with pytest.raises(ValueError, match="No file check"):
        signed_url(
            private_field("r/1/a.pdf"),
            user=worker.user,
            company_id=worker.company_id,
            check="core.nothing:1",
        )
    with pytest.raises(ValueError, match="looks like"):
        signed_url(
            private_field("r/1/a.pdf"),
            user=worker.user,
            company_id=worker.company_id,
            check="core.testfile",
        )


def test_default_storage_files_can_be_signed_too(client, worker, allowed, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    name = default_storage.save("proofs/1/a.jpg", ContentFile(b"\xff\xd8\xff"))
    url = signed_url(
        SimpleNamespace(name=name, storage=default_storage),
        user=worker.user,
        company_id=worker.company_id,
        check=f"{KIND}:1",
    )

    assert body(client.get(url)) == b"\xff\xd8\xff"


def test_registration_rules(monkeypatch):
    monkeypatch.setattr(files, "_checks", {})

    register_file_check("core.one", lambda *args: True)
    with pytest.raises(DuplicateFileCheck):
        register_file_check("core.one", lambda *args: True)
    with pytest.raises(ValueError, match=r"'<app>\.<thing>'"):
        register_file_check("nodot", lambda *args: True)
    with pytest.raises(ValueError, match="installed app"):
        register_file_check("nosuchapp.thing", lambda *args: True)
    assert files.registered_kinds() == ["core.one"]


def test_every_registered_kind_starts_with_an_app_label():
    from django.apps import apps

    labels = {config.label for config in apps.get_app_configs()}
    assert all(kind.split(".")[0] in labels for kind in files.registered_kinds())


def test_the_serializer_field_renders_a_signed_link(worker, allowed, client):
    name = stored("r/1/a.pdf")
    document = SimpleNamespace(pk=1, company_id=worker.company_id, file=private_field(name))

    class DocumentSerializer(serializers.Serializer):
        file = PrivateFileSerializerField(check=KIND)
        other = PrivateFileSerializerField(source="file", check=lambda obj: f"{KIND}:{obj.pk}")

    request = APIRequestFactory().get("/")
    request.user = worker.user
    data = DocumentSerializer(document, context={"request": request}).data

    assert data["file"].startswith("/api/v1/files/")
    assert client.get(data["file"]).status_code == 200
    assert client.get(data["other"]).status_code == 200


def test_the_serializer_field_is_empty_without_a_file(worker, allowed):
    document = SimpleNamespace(pk=1, company_id=worker.company_id, file=None)

    class DocumentSerializer(serializers.Serializer):
        file = PrivateFileSerializerField(check=KIND)

    request = APIRequestFactory().get("/")
    request.user = worker.user
    assert DocumentSerializer(document, context={"request": request}).data["file"] is None
