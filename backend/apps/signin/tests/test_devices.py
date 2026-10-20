"""Telling devices apart from their User-Agent, and masking addresses."""

import pytest

from apps.signin import devices
from apps.signin.models import DeviceSession

AGENTS = {
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141.0 Safari/537.36": (
        "Chrome",
        "Windows",
        "desktop",
    ),
    "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/141.0 Safari/537.36 Edg/141.0": (
        "Edge",
        "Windows",
        "desktop",
    ),
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 Version/18.6 Safari/605": (
        "Safari",
        "macOS",
        "desktop",
    ),
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) Version/18.6 Mobile Safari/604.1": (
        "Safari",
        "iOS",
        "phone",
    ),
    "Mozilla/5.0 (Linux; Android 15; SM-A556E) Chrome/141.0 Mobile Safari/537.36": (
        "Chrome",
        "Android",
        "phone",
    ),
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:143.0) Gecko/20100101 Firefox/143.0": (
        "Firefox",
        "Ubuntu",
        "desktop",
    ),
    "Mozilla/5.0 (Windows NT 10.0) Chrome/141.0 YaBrowser/25.8 Safari/537.36": (
        "Yandex",
        "Windows",
        "desktop",
    ),
    "Mozilla/5.0 (iPad; CPU OS 18_6 like Mac OS X) Version/18.6 Safari/604.1": (
        "Safari",
        "iPadOS",
        "tablet",
    ),
}


@pytest.mark.parametrize(("agent", "expected"), AGENTS.items())
def test_common_browsers(agent, expected):
    device = devices.describe(agent)

    assert (device.browser, device.system, device.kind) == expected
    assert device.label == f"{expected[0]} · {expected[1]}"


def test_unknown_agents_read_plainly():
    device = devices.describe("")

    assert device.label == "Browser · Unknown system"
    assert device.kind == "desktop"


@pytest.mark.parametrize(
    ("ip", "masked"),
    [
        ("213.230.86.14", "213.230.x.x"),
        ("2001:db8:85a3::8a2e:370:7334", "2001:0db8:85a3:…"),
        (None, ""),
        ("", ""),
        ("not an ip", ""),
    ],
)
def test_addresses_are_masked(ip, masked):
    assert devices.masked_ip(ip) == masked


@pytest.mark.django_db
def test_demo_gives_the_owner_three_devices(company, demo_people):
    from django.utils import timezone

    from apps.signin import demo

    people = demo_people(company)
    demo.seed(company, people, timezone.now())
    demo.seed(company, people, timezone.now())  # running it again adds nothing

    sessions = DeviceSession.objects.filter(user=people["owner"].user)
    assert sessions.count() == 3
    labels = {devices.describe(s.user_agent).label for s in sessions}
    assert labels == {"Chrome · Windows", "Safari · iOS", "Firefox · Ubuntu"}
