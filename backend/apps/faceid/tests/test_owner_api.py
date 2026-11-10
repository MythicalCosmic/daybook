"""Face ID owner endpoints (`faceid/…`): permissions, another company, the module switch, branch
scope, hidden fields, audited writes and the shapes the dashboard reads."""

import json

import pytest

from apps.audit.models import AuditLog
from apps.faceid import hikvision
from apps.faceid import services as face
from apps.faceid.models import FaceDevice, FaceEvent, FaceLink
from apps.faceid.tests import samples as hik
from apps.faceid.tests.conftest import DAY, local
from apps.members.models import AccessRole
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db


def url(company, path):
    return f"/api/v1/owner/companies/{company.pk}/faceid/{path}"


@pytest.fixture
def device(device, freeze):
    freeze(local(DAY, 10, 0))
    return device


@pytest.fixture
def yunusobod_device(staff, yunusobod):
    return FaceDevice.objects.create(company=yunusobod.company, branch=yunusobod, name="Yunusobod")


def post(device, at=None, **fields):
    at = at or local(DAY, 9, 58)
    content_type, body = hik.multipart(hik.event(at=at.isoformat(), **fields), picture=hik.jpeg())
    return face.receive(device, hikvision.parse(content_type, body), received_at=at)


@pytest.fixture
def reader(staff, member):
    AccessRole.objects.create(
        company=staff.ali.company, name="Reader", permissions=[Perm.DASHBOARD_ACCESS]
    )
    return member.registered(staff.ali.company, "Reader")


@pytest.mark.parametrize("path", ["devices/", "links/", "settings/"])
def test_terminals_links_and_settings_need_attendance_manage(staff, owner_api, device, path):
    company = staff.ali.company
    assert owner_api(staff.manager).get(url(company, path)).status_code == 200
    assert owner_api(staff.accountant).get(url(company, path)).status_code == 403


@pytest.mark.parametrize("path", ["events/", "status/", "people/"])
def test_the_feed_people_and_status_need_attendance_view(staff, owner_api, device, reader, path):
    company = staff.ali.company
    assert owner_api(staff.accountant).get(url(company, path)).status_code == 200
    assert owner_api(reader).get(url(company, path)).status_code == 403


def test_another_company_is_a_404(staff, owner_api, device, other_company):
    assert owner_api(staff.manager).get(url(other_company, "devices/")).status_code == 404
    path = f"devices/{device.pk}/setup/"
    assert owner_api(staff.manager).get(url(other_company, path)).status_code == 404


def test_the_module_off_is_a_404(staff, owner_api, device):
    company = staff.ali.company
    company.features = ["attendance"]
    company.save()
    for path in ("devices/", "events/", "settings/", "people/"):
        assert owner_api(staff.manager).get(url(company, path)).status_code == 404


def test_add_a_terminal_and_read_off_its_setup(staff, owner_api, chilonzor, settings):
    settings.PUBLIC_DEVICE_HOST = ""
    settings.DASHBOARD_URL = "https://pharmacy.example.com/dashboard/"
    client = owner_api(staff.manager)
    company = staff.ali.company
    response = client.post(
        url(company, "devices/"),
        {"name": "Chilonzor kirish", "branch_id": chilonzor.pk, "direction": "toggle"},
        format="json",
    )
    assert response.status_code == 201, response.json()
    data = response.json()
    assert data["status"] == "never" and data["branch"]["name"] == "Chilonzor"
    assert "token" not in data  # the code only travels in the setup values
    made = FaceDevice.objects.get(pk=data["id"])
    setup = client.get(url(company, f"devices/{made.pk}/setup/")).json()
    assert setup["host"] == "pharmacy.example.com" and setup["recommended"] == "https"
    assert setup["path"] == f"/api/v1/devices/hik/{made.token}/"
    assert setup["https"]["port"] == 443 and setup["http"]["port"] == 80
    assert AuditLog.objects.filter(action="faceid.device_added").exists()


def test_change_switch_off_and_new_code(staff, owner_api, device, yunusobod):
    client = owner_api(staff.manager)
    company = staff.ali.company
    response = client.patch(
        url(company, f"devices/{device.pk}/"),
        {"direction": "in", "enabled": False, "branch_id": yunusobod.pk},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["status"] == "disabled"
    assert response.json()["branch"]["name"] == "Yunusobod"
    old = device.token
    setup = client.post(url(company, f"devices/{device.pk}/regenerate/")).json()
    device.refresh_from_db()
    assert device.token != old and device.token in setup["path"]
    actions = set(AuditLog.objects.values_list("action", flat=True))
    assert {"faceid.device_changed", "faceid.code_changed"} <= actions
    assert old not in str(list(AuditLog.objects.values_list("details", flat=True)))


def test_a_branch_lead_sees_only_their_terminals(staff, owner_api, device, yunusobod_device):
    company = staff.ali.company
    client = owner_api(staff.lead)  # Chilonzor only
    assert [row["name"] for row in client.get(url(company, "devices/")).json()] == ["Kirish"]
    path = f"devices/{yunusobod_device.pk}/setup/"
    assert client.get(url(company, path)).status_code == 404
    response = client.post(
        url(company, "devices/"),
        {"name": "X", "branch_id": yunusobod_device.branch_id, "direction": "in"},
        format="json",
    )
    assert response.status_code == 404


def test_the_feed_lists_every_scan_with_its_snapshot(staff, owner_api, device, yunusobod_device):
    post(device)
    post(yunusobod_device, number="21", name="Sara", serial=2)
    post(device, number="77", name="Dilshod", serial=3, at=local(DAY, 9, 59))
    company = staff.ali.company
    rows = owner_api(staff.manager).get(url(company, "events/")).json()["results"]
    assert len(rows) == 3
    ali = next(row for row in rows if row["member"] and row["member"]["id"] == staff.ali.pk)
    assert ali["action"] == "checked_in" and ali["photo_url"].startswith("/api/v1/files/")
    assert ali["record"]["check_in_at"].startswith("2026-10-21T09:58")
    stranger = next(row for row in rows if row["employee_no"] == "77")
    assert stranger["action"] == "not_linked" and stranger["member"] is None
    assert stranger["photo_url"] and stranger["name_on_device"] == "Dilshod"
    lead_rows = owner_api(staff.lead).get(url(company, "events/")).json()["results"]
    assert {row["device"]["name"] for row in lead_rows} == {"Kirish"}
    client = owner_api(staff.manager)
    assert len(client.get(url(company, f"events/?device={device.pk}")).json()["results"]) == 2
    assert len(client.get(url(company, "events/?action=not_linked")).json()["results"]) == 1
    assert len(client.get(url(company, f"events/?date={DAY}")).json()["results"]) == 3
    assert len(client.get(url(company, "events/?number=0077")).json()["results"]) == 1


def test_the_snapshot_opens_for_viewers_of_the_branch_and_the_person(staff, owner_api, device):
    from apps.faceid import providers

    post(device)
    company = staff.ali.company
    row = owner_api(staff.manager).get(url(company, "events/")).json()["results"][0]
    assert owner_api(staff.manager).get(row["photo_url"]).status_code == 200
    event = FaceEvent.objects.get()
    assert providers.photo_check(staff.ali.user, company.pk, event.pk)
    assert providers.photo_check(staff.lead.user, company.pk, event.pk)
    assert not providers.photo_check(staff.vali.user, company.pk, event.pk)
    assert not providers.photo_check(staff.sara.user, company.pk, event.pk)  # Yunusobod only


def test_people_suggestions_link_and_ignore(staff, owner_api, device):
    for person, (first, last) in (
        (staff.bob, ("Gulirano", "Saidova")),
        (staff.accountant, ("Gulnora", "Azimova")),
    ):
        person.first_name, person.last_name = first, last
        person.save()
    staff.manager.first_name = "Gulirano"  # two Gulirano: no automatic link
    staff.manager.save()
    post(device, number="00000008", name="Гулирано", serial=1)
    post(device, number="00000044", name="Guard", serial=2)
    client = owner_api(staff.manager)
    company = staff.ali.company
    rows = client.get(url(company, "people/?linked=0")).json()
    assert {row["employee_no"] for row in rows} == {"00000008", "00000044"}
    gulirano = next(row for row in rows if row["employee_no"] == "00000008")
    assert gulirano["member"] is None and gulirano["photo_url"]
    top = [suggestion["member"]["id"] for suggestion in gulirano["suggestions"]]
    assert set(top[:2]) == {staff.bob.pk, staff.manager.pk}
    response = client.post(
        url(company, "links/"), {"employee_no": "8", "member_id": staff.bob.pk}, format="json"
    )
    assert response.status_code == 201
    assert response.json()["employee_no"] == "8"
    ignored = client.post(
        url(company, "people/ignore/"), {"employee_no": "00000044"}, format="json"
    )
    assert ignored.status_code == 201
    linked = client.get(url(company, "people/?linked=1")).json()
    assert [row["member"]["id"] for row in linked if row["member"]] == [staff.bob.pk]
    missing = client.post(url(company, "people/ignore/"), {"employee_no": "99"}, format="json")
    assert missing.status_code == 404
    actions = set(AuditLog.objects.values_list("action", flat=True))
    assert {"faceid.linked", "faceid.ignored"} <= actions
    # The earlier scan of 00000008 is Bob's now, and the next one counts for him.
    assert FaceEvent.objects.filter(number_key="8", membership=staff.bob).exists()
    assert post(device, number="00000008", name="Гулирано", serial=3)[0].membership == staff.bob


def test_links_list_add_and_remove(staff, owner_api, device):
    client = owner_api(staff.manager)
    company = staff.ali.company
    rows = client.get(url(company, f"links/?member={staff.ali.pk}")).json()
    assert [row["employee_no"] for row in rows] == ["12"]
    response = client.post(
        url(company, "links/"), {"employee_no": "0012", "member_id": staff.vali.pk}, format="json"
    )
    assert response.status_code == 400  # 12 is Ali's
    added = client.post(
        url(company, "links/"), {"employee_no": "112", "member_id": staff.ali.pk}, format="json"
    ).json()
    assert client.delete(url(company, f"links/{added['id']}/")).status_code == 204
    assert AuditLog.objects.filter(action="faceid.unlinked").exists()
    response = owner_api(staff.lead).post(
        url(company, "links/"), {"employee_no": "77", "member_id": staff.sara.pk}, format="json"
    )
    assert response.status_code == 404  # Sara works at Yunusobod


def test_an_automatic_link_is_replaced_in_one_tap(staff, owner_api, device):
    staff.bob.first_name = "Zulfiya"
    staff.bob.save()
    (event,) = post(device, number="4", name="Zulfiya", serial=1)
    assert event.membership == staff.bob and FaceLink.objects.get(number_key="4").auto
    response = owner_api(staff.manager).post(
        url(staff.ali.company, "links/"),
        {"employee_no": "4", "member_id": staff.vali.pk},
        format="json",
    )
    assert response.status_code == 201
    link = FaceLink.objects.get(number_key="4")
    assert link.membership == staff.vali and not link.auto


def test_status_counts_terminals(staff, owner_api, device, yunusobod_device):
    post(device)
    data = owner_api(staff.manager).get(url(staff.ali.company, "status/")).json()
    assert (data["total"], data["online"], data["never"]) == (2, 1, 1)
    assert data["unlinked"] == 0
    viewer = owner_api(staff.accountant).get(url(staff.ali.company, "status/")).json()
    assert viewer["unlinked"] is None


def test_the_terminal_and_its_setup_show_the_old_history_coming_in(
    staff, owner_api, device, freeze
):
    """While a terminal uploads its stored history the card and the setup's last step say so,
    with the count; when it stops coming the count stays."""
    company = staff.ali.company
    client = owner_api(staff.manager)
    path = f"devices/{device.pk}/"
    assert client.get(url(company, "devices/")).json()[0]["history"] == {
        "skipped": 0, "until": None, "active": False, "clock_hides": False,
    }  # fmt: skip
    for serial, day in ((1, "2022-10-11T16:00:00"), (2, "2023-03-02T09:15:00")):
        content_type, body = hik.multipart(hik.event(serial=serial, at=day + "+08:00"))
        face.receive(device, hikvision.parse(content_type, body), received_at=local(DAY, 10, 0))
    history = client.get(url(company, "devices/")).json()[0]["history"]
    assert history["skipped"] == 2 and history["active"] and not history["clock_hides"]
    assert history["until"].startswith("2023-03-02T09:15:00")
    setup = client.get(url(company, path + "setup/")).json()
    assert setup["history"]["active"] and setup["last_event_at"] is None and setup["last_seen_at"]
    freeze(local(DAY, 10, 20))
    history = client.get(url(company, "devices/")).json()[0]["history"]
    assert history["skipped"] == 2 and not history["active"]


def test_a_clock_days_behind_is_told_apart_from_history(staff, owner_api, device):
    """A terminal whose clock is years behind makes every live scan look old: its heartbeats
    show it, and the card asks for the clock to be set instead of waiting for the history."""
    company = staff.ali.company
    body = json.dumps(hik.heartbeat(at="2000-01-01T10:00:00+08:00")).encode()
    face.receive(device, hikvision.parse("application/json", body), received_at=local(DAY, 10, 0))
    history = owner_api(staff.manager).get(url(company, "devices/")).json()[0]["history"]
    assert history["clock_hides"] and history["skipped"] == 0


def test_the_catchup_helper_downloads_with_the_terminals_address_filled_in(
    staff, owner_api, device, yunusobod_device, other_company, settings
):
    """While a terminal uploads its old history, managers download catchup.py from its page: the
    terminal's address on the server (the URL the setup wizard shows) is filled in."""
    from apps.companies.models import Branch

    settings.PUBLIC_DEVICE_HOST = "davomat.example.uz"
    company = staff.ali.company
    path = f"devices/{device.pk}/catchup/"
    response = owner_api(staff.manager).get(url(company, path))
    assert response.status_code == 200
    assert response["Content-Disposition"] == 'attachment; filename="catchup.py"'
    assert response["Content-Type"].startswith("text/x-python")
    assert response["Cache-Control"] == "private, no-store"
    script = response.content.decode()
    shown = owner_api(staff.manager).get(url(company, f"devices/{device.pk}/setup/")).json()
    address = shown[shown["recommended"]]["url"]
    assert address == f"https://davomat.example.uz/api/v1/devices/hik/{device.token}/"
    assert f'DEVICE_URL = "{address}"' in script and 'DEVICE_URL = ""' not in script
    compile(script, "catchup.py", "exec")
    # Asked for as a Python file, it answers the same.
    asked = owner_api(staff.manager).get(url(company, path), HTTP_ACCEPT="text/x-python")
    assert asked.status_code == 200 and asked.content == response.content

    assert owner_api(staff.accountant).get(url(company, path)).status_code == 403  # view only
    # Another company: its id, or its terminal's id under ours.
    assert owner_api(staff.manager).get(url(other_company, path)).status_code == 404
    branch = other_company.branches.first() or Branch.objects.create(
        company=other_company, name="Other", code="OTH"
    )
    theirs = FaceDevice.objects.create(company=other_company, branch=branch, name="Theirs")
    path = f"devices/{theirs.pk}/catchup/"
    assert owner_api(staff.manager).get(url(company, path)).status_code == 404
    # A branch lead gets their own branch's terminals only.
    path = f"devices/{yunusobod_device.pk}/catchup/"
    assert owner_api(staff.lead).get(url(company, path)).status_code == 404
    path = f"devices/{device.pk}/catchup/"
    assert owner_api(staff.lead).get(url(company, path)).status_code == 200
    # Face ID switched off: nothing.
    company.features = ["attendance"]
    company.save()
    assert owner_api(staff.manager).get(url(company, path)).status_code == 404


def test_the_setup_values_carry_the_terminals_own_address(staff, owner_api, device):
    """The wizard's catch-up command names the terminal by the address it reports."""
    company = staff.ali.company
    path = url(company, f"devices/{device.pk}/setup/")
    assert owner_api(staff.manager).get(path).json()["ip"] == ""
    post(device)  # the terminal says it is 192.168.1.250
    assert owner_api(staff.manager).get(path).json()["ip"] == "192.168.1.250"


def test_the_image_carries_the_catchup_helper():
    """The download reads deploy/faceid/catchup.py: the production image must have it."""
    from pathlib import Path

    from django.conf import settings as django_settings

    root = Path(django_settings.BASE_DIR).parent
    assert "COPY deploy/faceid ./deploy/faceid" in (root / "Dockerfile").read_text()
    assert face.CATCHUP_SCRIPT.is_file()
    assert root / "deploy" / "faceid" / "catchup.py" == face.CATCHUP_SCRIPT


def test_a_test_scan_from_the_setup_card(staff, owner_api, device):
    company = staff.ali.company
    response = owner_api(staff.manager).post(url(company, f"devices/{device.pk}/simulate/"))
    assert response.status_code == 201
    row = response.json()
    assert "simulated" in row["flags"] and row["member"]["id"] == staff.manager.pk
    setup = owner_api(staff.manager).get(url(company, f"devices/{device.pk}/setup/")).json()
    assert setup["last_test_at"] and setup["last_event_at"] is None
    assert owner_api(staff.manager).get(url(company, "events/")).json()["results"] == []
    tests = owner_api(staff.manager).get(url(company, "events/?tests=1")).json()["results"]
    assert len(tests) == 1


def test_settings(staff, owner_api):
    path = url(staff.ali.company, "settings/")
    client = owner_api(staff.manager)
    data = client.get(path).json()
    assert data == {
        "attendance": True,
        "telegram": "arrivals",
        "group_posts": False,
        "group_photos": False,
        "notify_employee": True,
        "alert_strangers": False,
        "repeat_minutes": 2,
        "photo_days": 30,
    }
    response = client.patch(path, {"telegram": "every_scan", "repeat_minutes": 5}, format="json")
    assert response.status_code == 200 and response.json()["telegram"] == "every_scan"
    assert client.patch(path, {"repeat_minutes": 0}, format="json").status_code == 400
    assert AuditLog.objects.filter(action="faceid.settings_changed").exists()
