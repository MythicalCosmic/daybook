"""The API half of deploy/davomat/smoke.sh (standard library only, run on the host): sets the
organization up the way the browser's setup page does (docs/DAVOMAT.md §1), signs in with a
password, adds a terminal, posts its events the way a Hikvision terminal does (smoke_events.py),
and checks what Davomat made of them: the employees created from the unknown numbers, their
check-ins, the snapshots.

    python3 -I smoke_api.py scan --site https://localhost:18443 --http http://127.0.0.1:18080 \
        --http-name http://localhost:18080 --https-ip https://127.0.0.1:18443 \
        --cacert CA.pem --events EVENTS.json --state STATE.json
    python3 -I smoke_api.py change --site ... --cacert CA.pem --state STATE.json
    python3 -I smoke_api.py restored --site ... --cacert CA.pem --state STATE.json

Exits 1 with the reason when a check fails.
"""

import argparse
import base64
import http.client
import json
import secrets
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ORGANIZATION = "Namuna Smoke MChJ"
ADMIN = "admin"
DEVICE_NAME = "Kirish"
CHANGED_NAME = "Changed after the backup"
FIRST = ("00000002", "Гулирано")
SECOND = ("00000004", "Zulfiya")


class Failed(Exception):
    pass


def check(condition, message: str) -> None:
    if not condition:
        raise Failed(message)


def say(message: str) -> None:
    print(f"    ok  {message}", flush=True)


def rows(payload):
    """A list endpoint's rows, paginated or not."""
    if isinstance(payload, dict) and "results" in payload:
        return payload["results"]
    return payload


class Site:
    def __init__(self, base: str, cacert: str | None):
        self.base = base.rstrip("/")
        self.context = ssl.create_default_context(cafile=cacert) if cacert else None
        self.access = None

    def request(
        self,
        method,
        path,
        *,
        data=None,
        body=None,
        content_type=None,
        auth=True,
        base=None,
        context=None,
        expect=None,
    ):
        url = (base or self.base) + path
        headers = {
            "Accept": "application/json",
            "X-Requested-With": "dashboard",
            "Origin": self.base,
            "Accept-Language": "en",
        }
        payload = None
        if data is not None:
            payload = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        elif body is not None:
            payload = body
            headers["Content-Type"] = content_type
        if auth and self.access:
            headers["Authorization"] = f"Bearer {self.access}"
        request = urllib.request.Request(url, data=payload, method=method, headers=headers)
        try:
            with urllib.request.urlopen(
                request, timeout=30, context=context or self.context
            ) as answer:
                status, raw = answer.status, answer.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
        try:
            result = json.loads(raw) if raw else None
        except ValueError:
            result = raw.decode(errors="replace")[:300]
        if expect is not None:
            allowed = expect if isinstance(expect, tuple) else (expect,)
            check(status in allowed, f"{method} {url}: {status}, expected {expect}: {result}")
        return status, result

    def owner(self, method, path, **kwargs):
        return self.request(method, f"/api/v1/owner/{path}", **kwargs)

    def sign_in(self, password: str) -> None:
        _, session = self.owner(
            "POST",
            "auth/password/",
            data={"username": ADMIN, "password": password},
            auth=False,
            expect=200,
        )
        check(session and session.get("access"), f"no access token: {session}")
        self.access = session["access"]


def post_event(site, event, *, base, path, context=None):
    _, answer = site.request(
        "POST",
        path,
        body=base64.b64decode(event["body"]),
        content_type=event["content_type"],
        auth=False,
        base=base,
        context=context,
        expect=200,
    )
    ok = isinstance(answer, dict) and answer.get("statusCode") == 200
    check(ok, f"the terminal's answer: {answer}")


def redirect_of(url: str) -> tuple[int, str]:
    """The status and Location of a plain HTTP GET, without following it."""
    parts = urllib.parse.urlsplit(url)
    connection = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=15)
    connection.request("GET", parts.path or "/")
    answer = connection.getresponse()
    location = answer.getheader("Location") or ""
    connection.close()
    return answer.status, location


def wait_for(what: str, probe, seconds: int = 30):
    """probe() until it returns something true; its last answer otherwise fails the check."""
    deadline = time.monotonic() + seconds
    while True:
        result, detail = probe()
        if result:
            return result
        if time.monotonic() > deadline:
            raise Failed(f"{what}: {detail}")
        time.sleep(1)


def employees_by_number(site, company):
    _, payload = site.owner("GET", f"companies/{company}/employees/", expect=200)
    found = {}
    for employee in rows(payload):
        for number in employee.get("face_numbers") or []:
            found[number.lstrip("0")] = employee
    return found, payload


def cmd_scan(args) -> dict:
    site = Site(args.site, args.cacert)
    with open(args.events) as handle:
        events = json.load(handle)

    _, health = site.request("GET", "/health/", auth=False, expect=200)
    check(health.get("status") == "ok", f"health: {health}")
    say(f"health over HTTPS (Caddy's certificate checked): version {health.get('version')}")

    _, edition = site.owner("GET", "edition/", auth=False, expect=200)
    check(edition.get("edition") == "davomat", f"edition: {edition}")
    check(edition.get("needs_setup") is True, f"a fresh install needs its setup: {edition}")
    say(f"edition {edition['edition']}, product {edition.get('product')}, needs setup")

    password = "Smoke-" + secrets.token_urlsafe(12)
    setup = {
        "organization": ORGANIZATION,
        "timezone": "Asia/Tashkent",
        "language": "uz",
        "admin": {
            "username": ADMIN,
            "password": password,
            "first_name": "Smoke",
            "last_name": "Admin",
        },
    }
    _, session = site.owner("POST", "edition/setup/", data=setup, auth=False, expect=(200, 201))
    check(session and session.get("access"), f"the setup signs the admin in: {session}")
    status, _ = site.owner("POST", "edition/setup/", data=setup, auth=False)
    check(status >= 400, f"a second setup must be refused, got {status}")
    _, edition = site.owner("GET", "edition/", auth=False, expect=200)
    check(edition.get("needs_setup") is False, f"set up: {edition}")
    check((edition.get("organization") or {}).get("name") == ORGANIZATION, f"name: {edition}")
    say(f"setup through the API: {ORGANIZATION}, a second setup refused ({status})")

    status, _ = site.owner(
        "POST",
        "auth/password/",
        data={"username": ADMIN, "password": password + "x"},
        auth=False,
        expect=400,
    )
    site.sign_in(password)
    say("password sign-in: a wrong password 400, the right one signs in")

    _, me = site.owner("GET", "me/", expect=200)
    companies = me.get("companies") or []
    check(len(companies) == 1, f"one organization: {companies}")
    company = companies[0]["id"]
    _, branches = site.owner("GET", f"companies/{company}/branches/", expect=200)
    branch = rows(branches)[0]["id"]

    _, device = site.owner(
        "POST",
        f"companies/{company}/faceid/devices/",
        data={"name": DEVICE_NAME, "branch_id": branch, "direction": "in"},
        expect=201,
    )
    _, setup_values = site.owner(
        "GET", f"companies/{company}/faceid/devices/{device['id']}/setup/", expect=200
    )
    path = setup_values["path"]
    check(
        setup_values.get("host") == args.device_host,
        f"the terminal's host is PUBLIC_DEVICE_HOST: {setup_values}",
    )
    say(f"terminal {DEVICE_NAME} added; it posts to {setup_values['host']}, {path[:30]}…")

    site.request("GET", path, auth=False, base=args.http, expect=200)
    say("the terminal's Test button (GET, plain HTTP, bare address): 200")
    post_event(site, events["heartbeat"], base=args.http_name, path=path)
    say("a heartbeat over plain HTTP to the site's name: 200")
    post_event(site, events["first"], base=args.http, path=path)
    say(f"scan of No {FIRST[0]} ({FIRST[1]}): multipart + snapshot, plain HTTP, bare address: 200")
    # A terminal on HTTPS to the bare address: no SNI, the site's certificate, never checked.
    unchecked = ssl.create_default_context()
    unchecked.check_hostname = False
    unchecked.verify_mode = ssl.CERT_NONE
    post_event(site, events["second"], base=args.https_ip, path=path, context=unchecked)
    say(f"scan of No {SECOND[0]} ({SECOND[1]}): HTTPS to the bare address: 200")
    site.request(
        "POST",
        "/api/v1/devices/hik/" + "x" * 24 + "/",
        body=b"{}",
        content_type="application/json",
        auth=False,
        base=args.http,
        expect=404,
    )
    status, location = redirect_of(args.http + "/dashboard/")
    check(
        status in (301, 308) and location.startswith("https://"), f"redirect: {status} {location}"
    )
    say(f"an unknown terminal code 404; the rest of plain HTTP redirects ({status} {location})")

    def both_created():
        found, payload = employees_by_number(site, company)
        return (found if {"2", "4"} <= set(found) else None), payload

    found = wait_for("the employees made from the terminal's numbers", both_created)
    first, second = found["2"], found["4"]
    check(FIRST[1] in (first.get("full_name") or ""), f"named from the terminal: {first}")
    check(SECOND[1] in (second.get("full_name") or ""), f"named from the terminal: {second}")
    say(
        f"employees created from the unknown numbers: {first['full_name']} "
        f"{first['face_numbers']}, {second['full_name']} {second['face_numbers']}"
    )

    _, page = site.owner(
        "GET", f"companies/{company}/faceid/events/?device={device['id']}", expect=200
    )
    scans = [event for event in rows(page) if event.get("action") == "checked_in"]
    check(len(scans) == 2, f"two check-ins in the feed: {rows(page)}")
    check(all(event.get("photo_url") for event in scans), f"snapshots kept: {scans}")
    check(all(event.get("member") for event in scans), f"linked to the employees: {scans}")
    say("the live feed: 2 scans checked in, each with its snapshot and its employee")

    today = events["at"][:10]
    _, records = site.owner(
        "GET", f"companies/{company}/attendance/records/?from={today}&to={today}", expect=200
    )
    checked_in = [record for record in rows(records) if record.get("check_in_at")]
    check(len(checked_in) == 2, f"two attendance records today: {rows(records)}")
    say(
        f"attendance: 2 check-ins on {today} "
        f"({', '.join(record['check_in_at'][11:19] for record in checked_in)})"
    )

    def first_is_in():
        _, employee = site.owner("GET", f"companies/{company}/employees/{first['id']}/", expect=200)
        state = (employee.get("today") or {}).get("state")
        return state == "in", employee.get("today")

    wait_for("the employee's today state", first_is_in, seconds=10)
    say(f"{first['full_name']}: today in")

    return {
        "company": company,
        "device": device["id"],
        "password": password,
        "employees": sorted(employee["id"] for employee in found.values()),
    }


def cmd_change(args, state) -> None:
    site = Site(args.site, args.cacert)
    site.sign_in(state["password"])
    site.owner(
        "PATCH",
        f"companies/{state['company']}/faceid/devices/{state['device']}/",
        data={"name": CHANGED_NAME},
        expect=200,
    )
    say(f"after the backup: the terminal renamed to {CHANGED_NAME!r}")


def cmd_restored(args, state) -> None:
    site = Site(args.site, args.cacert)
    site.sign_in(state["password"])
    company = state["company"]
    _, devices = site.owner("GET", f"companies/{company}/faceid/devices/", expect=200)
    names = [device["name"] for device in rows(devices)]
    check(names == [DEVICE_NAME], f"the terminal as it was in the backup: {names}")
    found, _ = employees_by_number(site, company)
    check(
        sorted(employee["id"] for employee in found.values()) == state["employees"],
        f"the same employees: {found}",
    )
    _, page = site.owner("GET", f"companies/{company}/faceid/events/", expect=200)
    with_photo = [event for event in rows(page) if event.get("photo_url")]
    check(len(with_photo) >= 2, f"the snapshots came back: {rows(page)}")
    say(
        f"the data as in the backup: terminal {names[0]!r}, {len(found)} employees, "
        f"{len(with_photo)} snapshots"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["scan", "change", "restored"])
    parser.add_argument("--site", required=True, help="https://<DOMAIN>:<port>")
    parser.add_argument("--cacert", help="Caddy's root certificate (and the system's)")
    parser.add_argument("--http", help="plain HTTP to the bare address, http://127.0.0.1:<port>")
    parser.add_argument("--http-name", help="plain HTTP to the site's name")
    parser.add_argument("--https-ip", help="HTTPS to the bare address")
    parser.add_argument("--device-host", default="127.0.0.1", help="PUBLIC_DEVICE_HOST")
    parser.add_argument("--events", help="smoke_events.py's output")
    parser.add_argument("--state", required=True, help="what scan learned, for the later steps")
    args = parser.parse_args()
    try:
        if args.command == "scan":
            state = cmd_scan(args)
            with open(args.state, "w") as handle:
                json.dump(state, handle)
        else:
            with open(args.state) as handle:
                state = json.load(handle)
            (cmd_change if args.command == "change" else cmd_restored)(args, state)
    except Failed as error:
        print(f"    FAILED  {error}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
