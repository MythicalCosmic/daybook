"""Demo data of owner sign-in: the owner's other devices, so the sessions page has a story.

Dilnoza signs in on her shop laptop most days, checks the dashboard on her iPhone in the
evening, and once signed in from her brother's PC at home. The demo rows carry no real refresh
token, so they can be revoked but never used.
"""

import secrets
from datetime import timedelta

from apps.signin.models import DeviceSession

DEVICES = (
    # (user agent, ip, signed in days ago, last seen minutes ago)
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/141.0.0.0 Safari/537.36",
        "213.230.86.14",
        12,
        25,
    ),
    (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1",
        "84.54.71.203",
        3,
        14 * 60,
    ),
    (
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:143.0) Gecko/20100101 Firefox/143.0",
        "195.158.9.77",
        6,
        5 * 24 * 60,
    ),
)


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    owner = people.get("owner")
    if owner is None or DeviceSession.objects.filter(user=owner.user).exists():
        return
    for agent, ip, days, minutes in DEVICES:
        session = DeviceSession.objects.create(
            user=owner.user,
            refresh_jti=secrets.token_hex(16),
            user_agent=agent,
            ip=ip,
            last_seen_at=now - timedelta(minutes=minutes),
        )
        # created_at is auto_now_add: set the story's sign-in day afterwards.
        DeviceSession.objects.filter(pk=session.pk).update(created_at=now - timedelta(days=days))
