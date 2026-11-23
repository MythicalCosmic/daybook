"""A Hikvision NVR: ISAPI over HTTP with digest auth, and its RTSP streams.

- Channels: ``GET /ISAPI/ContentMgmt/InputProxy/channels`` (ids and names).
- Snapshot: ``GET /ISAPI/Streaming/channels/<ch>01/picture``.
- Live analysis on the sub-stream ``rtsp://<host>:554/Streaming/Channels/<ch>02``.
- Playback: ``rtsp://<host>:554/Streaming/tracks/<ch>01?starttime=YYYYMMDDTHHMMSSZ&endtime=…``,
  whose times Hikvision usually reads as the NVR's **local** time despite the ``Z``. The NVR's
  zone comes from ``/ISAPI/System/time`` (``CST-5:00:00`` in POSIX style means UTC+5) and can be
  overridden in the settings.

Passwords are never guessed or retried: a 401 raises ``NvrAuthError`` ("wrong NVR login") at
once, because Hikvision locks the account after a few failed logins.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from urllib.parse import quote

import httpx

from .logutil import mask_url

WRONG_LOGIN = "wrong NVR login"


class NvrError(RuntimeError):
    pass


class NvrAuthError(NvrError):
    def __init__(self, message: str = WRONG_LOGIN) -> None:
        super().__init__(message)


@dataclass(frozen=True)
class Channel:
    id: int
    name: str
    ip: str | None = None
    online: bool | None = None


@dataclass(frozen=True)
class NvrTime:
    offset_s: int  # local time = UTC + offset
    zone: str | None
    local_time: str | None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in element if _local(child.tag) == name]


def _text(element: ET.Element, name: str) -> str | None:
    for child in element.iter():
        if child is not element and _local(child.tag) == name:
            return (child.text or "").strip()
    return None


def parse_channels(xml: str | bytes) -> list[Channel]:
    """``InputProxyChannelList`` → channels, in id order (namespace-agnostic)."""
    root = ET.fromstring(xml)
    items = [root] if _local(root.tag) == "InputProxyChannel" else list(root.iter())
    channels = []
    for item in items:
        if _local(item.tag) != "InputProxyChannel":
            continue
        raw_id = _text(item, "id")
        if not raw_id or not raw_id.isdigit():
            continue
        name = _text(item, "name") or f"Camera {raw_id}"
        channels.append(Channel(id=int(raw_id), name=name, ip=_text(item, "ipAddress") or None))
    return sorted(channels, key=lambda c: c.id)


def parse_channel_status(xml: str | bytes) -> dict[int, bool]:
    """``InputProxyChannelStatusList`` → {channel id: online}."""
    root = ET.fromstring(xml)
    status = {}
    for item in root.iter():
        if _local(item.tag) != "InputProxyChannelStatus":
            continue
        raw_id = _text(item, "id")
        online = (_text(item, "online") or "").lower() == "true"
        if raw_id and raw_id.isdigit():
            status[int(raw_id)] = online
    return status


_POSIX = re.compile(r"^\s*([A-Za-z]+|<[^>]+>)?\s*([+-]?)(\d{1,2})(?::(\d{1,2}))?(?::(\d{1,2}))?")


def parse_posix_tz(value: str) -> int:
    """POSIX TZ → seconds east of UTC. The sign is inverted: ``CST-5:00:00`` is UTC+5.
    A DST part, if any, is ignored (Uzbekistan has none)."""
    match = _POSIX.match(value or "")
    if not match:
        raise ValueError(f"not a POSIX time zone: {value!r}")
    sign = -1 if match.group(2) == "-" else 1
    hours, minutes, seconds = (int(match.group(i) or 0) for i in (3, 4, 5))
    return -sign * (hours * 3600 + minutes * 60 + seconds)


def parse_time(xml: str | bytes) -> NvrTime:
    """``/ISAPI/System/time`` → the NVR's offset from UTC, preferring the offset written in
    ``localTime`` and falling back to the POSIX ``timeZone``."""
    root = ET.fromstring(xml)
    local_time = _text(root, "localTime")
    zone = _text(root, "timeZone")
    if local_time:
        try:
            parsed = datetime.fromisoformat(local_time.replace("Z", "+00:00"))
            if parsed.utcoffset() is not None:
                return NvrTime(int(parsed.utcoffset().total_seconds()), zone, local_time)
        except ValueError:
            pass
    if zone:
        return NvrTime(parse_posix_tz(zone), zone, local_time)
    raise NvrError("the NVR did not say its time zone")


def parse_offset(value: str) -> int:
    """A setting: ``+05:00``, ``-03:30``, ``UTC``, or a POSIX zone like ``CST-5:00:00``."""
    text = value.strip()
    if text.upper() in ("UTC", "Z", "+00:00", "0"):
        return 0
    match = re.fullmatch(r"([+-])(\d{1,2}):?(\d{2})?", text)
    if match:
        sign = -1 if match.group(1) == "-" else 1
        return sign * (int(match.group(2)) * 3600 + int(match.group(3) or 0) * 60)
    return parse_posix_tz(text)


def _credentials(user: str, password: str) -> str:
    return f"{quote(user, safe='')}:{quote(password, safe='')}@"


def live_url(host: str, channel: int, user: str, password: str, *, port: int = 554,
             stream: int = 2) -> str:
    """The RTSP URL of a channel's sub-stream (``stream=2``) or main stream (``stream=1``)."""
    return f"rtsp://{_credentials(user, password)}{host}:{port}/Streaming/Channels/{channel}0{stream}"


def hik_time(t_utc: float, offset_s: int) -> str:
    """A playback time as Hikvision wants it: the NVR's local wall time, written with a ``Z``."""
    local = datetime.fromtimestamp(t_utc, UTC) + timedelta(seconds=offset_s)
    return local.strftime("%Y%m%dT%H%M%SZ")


def playback_url(
    host: str,
    channel: int,
    start_utc: float,
    end_utc: float,
    user: str,
    password: str,
    *,
    offset_s: int = 0,
    port: int = 554,
) -> str:
    start, end = hik_time(start_utc, offset_s), hik_time(end_utc, offset_s)
    return (
        f"rtsp://{_credentials(user, password)}{host}:{port}/Streaming/tracks/{channel}01"
        f"?starttime={start}&endtime={end}"
    )


def tz_label(offset_s: int) -> str:
    sign = "+" if offset_s >= 0 else "-"
    minutes = abs(offset_s) // 60
    return f"UTC{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def offset_timezone(offset_s: int) -> timezone:
    return timezone(timedelta(seconds=offset_s))


class NvrClient:
    """ISAPI calls. One wrong login stops everything: no retry, ever, until the user types a new
    password with ``koz-agent nvr set``."""

    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        *,
        port: int = 80,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 8.0,
    ) -> None:
        self.host = host
        self.port = port
        self.auth_failed = False
        base = f"http://{host}" if port == 80 else f"http://{host}:{port}"
        self._http = httpx.Client(
            base_url=base,
            auth=httpx.DigestAuth(user, password),
            transport=transport,
            timeout=timeout,
        )

    def close(self) -> None:
        self._http.close()

    def _get(self, path: str) -> httpx.Response:
        if self.auth_failed:
            raise NvrAuthError()
        try:
            response = self._http.get(path)
        except httpx.TransportError as exc:
            raise NvrError(f"cannot reach the NVR at {self.host}: {type(exc).__name__}") from exc
        if response.status_code == 401:
            self.auth_failed = True
            raise NvrAuthError()
        if response.status_code >= 400:
            raise NvrError(f"the NVR answered HTTP {response.status_code} for {mask_url(path)}")
        return response

    def channels(self) -> list[Channel]:
        channels = parse_channels(self._get("/ISAPI/ContentMgmt/InputProxy/channels").content)
        try:
            status = parse_channel_status(
                self._get("/ISAPI/ContentMgmt/InputProxy/channels/status").content
            )
        except NvrAuthError:
            raise
        except (NvrError, ET.ParseError):
            status = {}
        return [Channel(c.id, c.name, c.ip, status.get(c.id)) for c in channels]

    def snapshot(self, channel: int) -> bytes:
        return self._get(f"/ISAPI/Streaming/channels/{channel}01/picture").content

    def time(self) -> NvrTime:
        return parse_time(self._get("/ISAPI/System/time").content)
