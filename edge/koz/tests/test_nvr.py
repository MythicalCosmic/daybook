"""The Hikvision NVR: URLs, XML from fixtures, time zones, and the no-retry wrong login."""

from pathlib import Path

import httpx
import pytest

from koz_agent.clock import parse_iso
from koz_agent.logutil import mask_url, redact
from koz_agent.nvr import (
    NvrAuthError,
    NvrClient,
    hik_time,
    live_url,
    parse_channel_status,
    parse_channels,
    parse_offset,
    parse_posix_tz,
    parse_time,
    playback_url,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_channels_from_the_channel_list():
    channels = parse_channels(fixture("input_proxy_channels.xml"))
    assert [(c.id, c.name) for c in channels] == [(1, "Kassa 1"), (2, "Zal"), (3, "Kirish")]
    assert channels[0].ip == "192.168.254.2"


def test_channel_status():
    assert parse_channel_status(fixture("input_proxy_channels_status.xml")) == {
        1: True, 2: False, 3: True}


@pytest.mark.parametrize(
    ("zone", "offset"),
    [
        ("CST-5:00:00", 5 * 3600),
        ("CST-5", 5 * 3600),
        ("CST+3:00:00", -3 * 3600),
        ("<+0530>-5:30", 5 * 3600 + 1800),
        ("UTC0", 0),
        ("EST5EDT,M3.2.0,M11.1.0", -5 * 3600),
    ],
)
def test_posix_time_zones_have_the_sign_inverted(zone, offset):
    assert parse_posix_tz(zone) == offset


def test_nvr_time_prefers_the_offset_of_local_time():
    assert parse_time(fixture("system_time.xml")).offset_s == 5 * 3600
    no_offset = parse_time(fixture("system_time_no_offset.xml"))
    assert no_offset.offset_s == 5 * 3600 and no_offset.zone == "CST-5:00:00"


def test_offset_settings():
    assert parse_offset("+05:00") == 18000 and parse_offset("-03:30") == -12600
    assert parse_offset("utc") == 0 and parse_offset("CST-5:00:00") == 18000


def test_live_url_is_the_sub_stream_with_escaped_credentials():
    url = live_url("192.168.0.250", 3, "admin", "p@ss:w/rd#1")
    assert url == "rtsp://admin:p%40ss%3Aw%2Frd%231@192.168.0.250:554/Streaming/Channels/302"
    assert live_url("10.0.0.5", 12, "u", "p", port=8554, stream=1).endswith(":8554/Streaming/Channels/1201")


def test_playback_url_uses_the_nvr_local_time():
    start = parse_iso("2026-11-23T16:30:50Z")
    end = parse_iso("2026-11-23T16:31:10Z")
    url = playback_url("192.168.0.250", 3, start, end, "admin", "secret", offset_s=5 * 3600)
    assert url == ("rtsp://admin:secret@192.168.0.250:554/Streaming/tracks/301"
                   "?starttime=20261123T213050Z&endtime=20261123T213110Z")
    assert hik_time(start, 0) == "20261123T163050Z"


def test_urls_are_masked_in_logs():
    url = live_url("192.168.0.250", 3, "admin", "secret")
    assert mask_url(url) == "rtsp://***@192.168.0.250:554/Streaming/Channels/302"
    line = f"cannot open {url} with Bearer koz_{'x' * 40} password=hunter2"
    clean = redact(line)
    assert "secret" not in clean and "koz_xxxx" not in clean and "hunter2" not in clean


CHALLENGE = 'Digest realm="DS-7608NI", qop="auth", nonce="4e7a1d", opaque="c0ffee"'


def digest_nvr(good_password: bool, calls: list):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, "authorization" in request.headers))
        if "authorization" not in request.headers or not good_password:
            return httpx.Response(401, headers={"WWW-Authenticate": CHALLENGE})
        assert 'username="admin"' in request.headers["authorization"]
        if request.url.path.endswith("/channels/status"):
            return httpx.Response(200, content=fixture("input_proxy_channels_status.xml"))
        return httpx.Response(200, content=fixture("input_proxy_channels.xml"))

    return httpx.MockTransport(handler)


def test_digest_login_lists_channels():
    calls: list = []
    client = NvrClient("192.168.0.250", "admin", "right", transport=digest_nvr(True, calls))
    channels = client.channels()
    assert [c.id for c in channels] == [1, 2, 3] and channels[1].online is False
    assert calls[0] == ("/ISAPI/ContentMgmt/InputProxy/channels", False)  # the challenge
    assert calls[1] == ("/ISAPI/ContentMgmt/InputProxy/channels", True)


def test_a_wrong_login_stops_at_once_and_never_retries():
    calls: list = []
    client = NvrClient("192.168.0.250", "admin", "wrong", transport=digest_nvr(False, calls))
    with pytest.raises(NvrAuthError, match="wrong NVR login"):
        client.channels()
    tried = sum(1 for _path, with_auth in calls if with_auth)
    assert tried == 1  # one login attempt, then nothing
    for call in (client.channels, lambda: client.snapshot(3), client.time):
        with pytest.raises(NvrAuthError):
            call()
    assert sum(1 for _path, with_auth in calls if with_auth) == 1
