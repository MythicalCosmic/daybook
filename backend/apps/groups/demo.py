"""Demo data of Telegram groups: the chats a two-branch shop really keeps.

A private management chat that gets money news, one team chat per branch, and a "Kassa" chat
for the cashiers. The chat ids are made up (negative, like real supergroups) and never reached
in development (`TELEGRAM_DRY_RUN`).
"""

from apps.groups.models import GroupEvent, TelegramGroup
from apps.members.models import Position

E = GroupEvent

GROUPS = (
    # (chat id, title, events, branch name or None, position names)
    (
        -1001900000101,
        "Demo Shop · Rahbariyat",
        [E.LATE, E.MEMBERS, E.EVENING, E.CASH, E.SALES, E.SHIFTS, E.CELEBRATIONS],
        None,
        (),
    ),
    (
        -1001900000102,
        "Chilonzor jamoasi",
        [E.DAILY_DONE, E.TASKS_DONE, E.LATE, E.MORNING, E.EVENING, E.ATTENDANCE, E.KUDOS],
        "Chilonzor",
        (),
    ),
    (
        -1001900000103,
        "Yunusobod jamoasi",
        [E.DAILY_DONE, E.LATE, E.MORNING, E.EVENING, E.CELEBRATIONS],
        "Yunusobod",
        (),
    ),
    (
        -1001900000104,
        "Kassa · Chilonzor",
        [E.CASH, E.SHIFTS, E.SALES],
        "Chilonzor",
        ("Cashier",),
    ),
)


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    branches = {branch.name: branch for branch in company.branches.all()}
    linked_by = people.get("manager") or people.get("owner")
    for chat_id, title, events, branch, positions in GROUPS:
        group, created = TelegramGroup.objects.get_or_create(
            chat_id=chat_id,
            defaults={
                "company": company,
                "title": title,
                "events": [str(event) for event in events],
                "linked_by": linked_by,
            },
        )
        if not created or group.company_id != company.pk:
            continue
        if branch and branch in branches:
            group.branches.set([branches[branch]])
        if positions:
            group.positions.set(Position.objects.for_company(company).filter(name__in=positions))
