"""The address terminals post to (`/api/v1/devices/hik/<code>/`) and the admin pages platform
support uses to add one."""

import json

import pytest
from django.test import Client

from apps.faceid import device_api
from apps.faceid.models import FaceDevice, FaceEvent
from apps.faceid.tests import samples as hik
from apps.faceid.tests.conftest import DAY, local

pytestmark = pytest.mark.django_db


@pytest.fixture
def device(device, freeze):
    """The Chilonzor terminal (Ali is number 12), at 08:58."""
    freeze(local(DAY, 8, 58))
    return device


def url(device_or_token, slash=True):
    token = getattr(device_or_token, "token", device_or_token)
    return f"/api/v1/devices/hik/{token}" + ("/" if slash else "")


def test_a_multipart_scan_is_answered_200_and_checks_in(device, staff):
    content_type, body = hik.multipart(hik.event(), picture=hik.jpeg())
    response = Client().post(url(device), data=body, content_type=content_type)
    assert response.status_code == 200
    assert response.json()["statusString"] == "OK"
    event = FaceEvent.objects.get()
    assert event.action == "checked_in" and event.membership == staff.ali and event.photo
    device.refresh_from_db()
    assert device.last_event_at is not None and device.ip == "192.168.1.250"


def test_json_xml_and_no_trailing_slash(device):
    client = Client()
    body = json.dumps(hik.event(serial=1)).encode()
    assert (
        client.post(url(device, slash=False), body, content_type="application/json").status_code
        == 200
    )
    assert (
        client.post(url(device), hik.xml(serial=2), content_type="application/xml").status_code
        == 200
    )
    assert FaceEvent.objects.count() == 2


def test_the_terminals_connection_test_and_unknown_codes(device):
    client = Client()
    assert client.get(url(device)).status_code == 200
    assert client.get(url("x" * 24)).status_code == 404
    assert client.post(url("y" * 24), b"{}", content_type="application/json").status_code == 404
    assert client.get("/api/v1/devices/hik/short/").status_code == 404


def test_an_unreadable_body_is_answered_200_and_kept_once(device):
    client = Client()
    for _ in range(3):
        response = client.post(url(device), b"{not json", content_type="application/json")
        assert response.status_code == 200
    (event,) = FaceEvent.objects.all()
    assert "unreadable" in event.flags and event.raw["excerpt"].startswith("{not json")


def test_a_heartbeat_keeps_the_terminal_fresh(device):
    body = json.dumps(hik.heartbeat(at=local(DAY, 8, 58).isoformat())).encode()
    assert Client().post(url(device), body, content_type="application/json").status_code == 200
    device.refresh_from_db()
    assert device.last_seen_at is not None and device.last_event_at is None
    assert device.clock_offset_s == 0
    assert FaceEvent.objects.count() == 0


def test_too_big_a_body_is_refused(device, monkeypatch):
    monkeypatch.setattr(device_api, "MAX_BODY_BYTES", 1000)
    content_type, body = hik.multipart(hik.event(), picture=b"\xff\xd8\xff" + b"0" * 2000)
    assert Client().post(url(device), body, content_type=content_type).status_code == 413
    assert FaceEvent.objects.count() == 0


def test_each_code_has_its_own_throttle(device, monkeypatch):
    monkeypatch.setattr(device_api, "RATE_PER_MINUTE", 2)
    client = Client()
    body = json.dumps(hik.heartbeat()).encode()
    codes = [
        client.post(url(device), body, content_type="application/json").status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]


def test_an_event_we_cant_handle_is_still_answered_200(device, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("apps.faceid.services.receive", broken)
    body = json.dumps(hik.event()).encode()
    assert Client().post(url(device), body, content_type="application/json").status_code == 200


def test_no_session_or_csrf_is_needed(device):
    client = Client(enforce_csrf_checks=True)
    body = json.dumps(hik.event()).encode()
    assert client.post(url(device), body, content_type="application/json").status_code == 200


def test_admin_shows_what_to_type_into_the_terminal(admin_client, device, settings):
    settings.PUBLIC_DEVICE_HOST = "144.91.81.29"
    response = admin_client.get(f"/admin/faceid/facedevice/{device.pk}/change/")
    assert response.status_code == 200
    content = response.content.decode()
    assert device.token in content
    assert f"http://144.91.81.29/api/v1/devices/hik/{device.token}/" in content
    for path in ("facedevice", "faceevent", "facelink"):
        assert admin_client.get(f"/admin/faceid/{path}/").status_code == 200


def test_admin_adds_a_terminal_with_a_code(admin_client, chilonzor):
    response = admin_client.post(
        "/admin/faceid/facedevice/add/",
        {
            "company": chilonzor.company_id,
            "branch": chilonzor.pk,
            "name": "Chilonzor kirish",
            "direction": "toggle",
            "enabled": "on",
        },
    )
    assert response.status_code == 302, response.content.decode()[:2000]
    made = FaceDevice.objects.get(name="Chilonzor kirish")
    assert len(made.token) == 24


def test_the_command_adds_lists_and_switches_the_module_on(staff, chilonzor, settings):
    from io import StringIO

    from django.core.management import call_command

    from apps.audit.models import AuditLog

    company = chilonzor.company
    company.features = ["attendance"]
    company.save()
    settings.PUBLIC_DEVICE_HOST = "144.91.81.29.nip.io"
    out = StringIO()
    call_command(
        "faceid_device", "add", "--company", company.pk, "--branch", chilonzor.pk,
        "--name", "Kirish", stdout=out,
    )  # fmt: skip
    text = out.getvalue()
    made = FaceDevice.objects.get(company=company, name="Kirish")
    assert f"https://144.91.81.29.nip.io/api/v1/devices/hik/{made.token}/" in text
    assert f"http://144.91.81.29.nip.io/api/v1/devices/hik/{made.token}/" in text
    assert "enable-module" in text  # Face ID is still off
    call_command("faceid_device", "enable-module", "--company", company.pk, stdout=StringIO())
    company.refresh_from_db()
    assert "face_id" in company.features and "attendance" in company.features
    assert AuditLog.objects.filter(action="companies.features_changed").exists()
    out = StringIO()
    call_command("faceid_device", "list", "--company", company.pk, stdout=out)
    assert "Kirish" in out.getvalue() and "never" in out.getvalue()


def test_the_command_takes_a_branch_by_name(chilonzor):
    from io import StringIO

    from django.core.management import CommandError, call_command

    company = chilonzor.company
    out = StringIO()
    call_command(
        "faceid_device", "add", "--company", company.pk, "--branch", chilonzor.name.upper(),
        "--name", "Kirish", stdout=out,
    )  # fmt: skip
    assert FaceDevice.objects.get(company=company, name="Kirish").branch == chilonzor
    with pytest.raises(CommandError) as refused:
        call_command(
            "faceid_device", "add", "--company", company.pk, "--branch", "Nowhere",
            "--name", "Chiqish", stdout=StringIO(),
        )  # fmt: skip
    assert f"{chilonzor.pk} {chilonzor.name}" in str(refused.value)
