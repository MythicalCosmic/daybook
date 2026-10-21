"""What a browser's User-Agent says about the device, in words a person recognises.

"Chrome · Windows" in the bot's "Sign in?" message and the sessions page, so the owner can tell
their own laptop from a stranger's. A handful of patterns cover what Uzbek owners use; anything
unknown reads as "Browser" / "Unknown system" rather than guessing.
"""

import ipaddress
import re
from dataclasses import dataclass

from django.utils.translation import gettext as _

# Order matters: Edge, Opera and Yandex also say "Chrome", Chrome also says "Safari".
_BROWSERS = (
    ("Telegram", re.compile(r"Telegram", re.I)),
    ("Edge", re.compile(r"Edg(?:e|A|iOS)?/")),
    ("Opera", re.compile(r"OPR/|Opera")),
    ("Yandex", re.compile(r"YaBrowser/")),
    ("Samsung Internet", re.compile(r"SamsungBrowser/")),
    ("Firefox", re.compile(r"Firefox/|FxiOS/")),
    ("Chrome", re.compile(r"Chrome/|CriOS/|Chromium/")),
    ("Safari", re.compile(r"Version/[\d.]+.*Safari/")),
)
_SYSTEMS = (
    ("iPadOS", re.compile(r"iPad")),
    ("iOS", re.compile(r"iPhone|iPod")),
    ("Android", re.compile(r"Android")),
    ("Windows", re.compile(r"Windows")),
    ("ChromeOS", re.compile(r"CrOS")),
    ("macOS", re.compile(r"Mac OS X|Macintosh")),
    ("Ubuntu", re.compile(r"Ubuntu")),
    ("Linux", re.compile(r"Linux|X11")),
)


@dataclass(frozen=True)
class Device:
    browser: str  # "" when unknown
    system: str  # "" when unknown
    kind: str  # "phone" | "tablet" | "desktop"

    @property
    def label(self) -> str:
        """Like "Chrome · Windows"; translated words only for the unknown parts."""
        return f"{self.browser or _('Browser')} · {self.system or _('Unknown system')}"


def describe(user_agent: str) -> Device:
    agent = user_agent or ""
    browser = next((name for name, pattern in _BROWSERS if pattern.search(agent)), "")
    system = next((name for name, pattern in _SYSTEMS if pattern.search(agent)), "")
    if system == "iPadOS" or re.search(r"Tablet|SM-T\d", agent):
        kind = "tablet"
    elif system in ("iOS", "Android") or "Mobile" in agent:
        kind = "phone"
    else:
        kind = "desktop"
    return Device(browser=browser, system=system, kind=kind)


def masked_ip(ip: str | None) -> str:
    """Like "213.230.x.x": enough to recognise a city's provider, not enough to track anyone."""
    if not ip:
        return ""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return ""
    if address.version == 4:
        first, second, *_rest = ip.split(".")
        return f"{first}.{second}.x.x"
    groups = address.exploded.split(":")
    return ":".join(groups[:3]) + ":…"
