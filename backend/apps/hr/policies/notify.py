"""Who hears about policies, through the inbox (`apps.inbox.services.notify`; the Telegram copy
goes out after commit, with an "Open in app" button that opens the policy in the mini app).

To the person (the employee bot): rules to read and sign (one message per policy, or one about
all of them when several wait at once, as for someone who just joined), a reminder before the
deadline, and rules that only ask to be read. To their manager: who didn't sign in time, one
message per policy listing them.

Each goes out once: the acknowledgement rows remember when (`notified_at`, `reminded_at`,
`late_notified_at`) and every message carries a `dedupe_key`.
"""

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime

from apps.hr import notify as hr_notify
from apps.hr.models import Policy, PolicyAcknowledgement, PolicyVersion
from apps.hr.policies import bot_messages
from apps.inbox import services as inbox
from apps.members import departments
from apps.members.models import Membership

POLICY = "hr.policy"
POLICY_LATE = "hr.policy_late"
# The mini app's pages (features/hr): one policy (`hr.policy:<id>`), and the list.
SCREEN = "hr.policy"
LIST_SCREEN = "hr.policies"


def _digest(values: Iterable) -> str:
    joined = "-".join(str(value) for value in sorted(values))
    return hashlib.sha1(joined.encode(), usedforsecurity=False).hexdigest()[:16]


def _is_new_version(row: PolicyAcknowledgement) -> bool:
    """Asked when a later version came out (not as a newcomer to the policy)."""
    version = row.version
    return (
        version.number > 1
        and version.published_at is not None
        and row.asked_at == (version.published_at)
    )


def tell(rows: list[PolicyAcknowledgement]) -> int:
    """Tell each person about the policies they newly owe a signature for. Returns the messages
    made (a person who turned the kind off, or heard already, gets none)."""
    by_person: dict[int, list[PolicyAcknowledgement]] = defaultdict(list)
    for row in rows:
        by_person[row.membership_id].append(row)
    sent = 0
    for items in by_person.values():
        person = items[0].membership
        if len(items) == 1:
            sent += _tell_one(person, items[0])
        else:
            sent += _tell_many(person, items)
    return sent


def _tell_one(person: Membership, row: PolicyAcknowledgement) -> int:
    policy = row.version.policy
    new_version = _is_new_version(row)
    return len(
        inbox.notify(
            [person],
            POLICY,
            title=lambda reader: bot_messages.to_sign_title(policy.title, new_version=new_version),
            body=lambda reader: bot_messages.sign_by(row.due_on),
            app_screen=f"{SCREEN}:{policy.pk}",
            target=policy,
            dedupe_key=f"{POLICY}:{row.version_id}",
        )
    )


def _tell_many(person: Membership, items: list[PolicyAcknowledgement]) -> int:
    titles = sorted((row.version.policy.title for row in items), key=str.casefold)
    due_on = min(row.due_on for row in items)
    return len(
        inbox.notify(
            [person],
            POLICY,
            title=lambda reader: bot_messages.many_to_sign_title(len(titles)),
            body=lambda reader: bot_messages.many_to_sign_body(titles, due_on),
            app_screen=LIST_SCREEN,
            dedupe_key=f"{POLICY}s:{_digest(row.version_id for row in items)}",
        )
    )


def to_read(version: PolicyVersion, people: Iterable[Membership]) -> int:
    """A policy that asks no signature: its readers hear there is something new to read."""
    policy = version.policy
    return len(
        inbox.notify(
            list(people),
            POLICY,
            title=lambda reader: bot_messages.to_read_title(policy.title),
            body=lambda reader: bot_messages.to_read_body(),
            app_screen=f"{SCREEN}:{policy.pk}",
            target=policy,
            dedupe_key=f"{POLICY}:read:{version.pk}",
        )
    )


def remind(row: PolicyAcknowledgement, today: date, now: datetime, *, manual: bool) -> int:
    """One reminder: automatic ones once a day at most, "Remind now" each time HR asks."""
    policy = row.version.policy
    stamp = now.strftime("%Y%m%dT%H%M") if manual else today.isoformat()
    return len(
        inbox.notify(
            [row.membership],
            POLICY,
            title=lambda reader: bot_messages.reminder_title(policy.title, row.due_on, today),
            body=lambda reader: bot_messages.reminder_body(row.due_on, today),
            app_screen=f"{SCREEN}:{policy.pk}",
            target=policy,
            dedupe_key=f"{POLICY}:remind:{row.pk}:{stamp}",
        )
    )


def managers_of(person: Membership, org: departments.Org | None = None) -> list[Membership]:
    """Who hears that someone is late: their head (departments), else the manager of their home
    branch, else HR in their branches."""
    approved = Membership.Status.APPROVED
    head = departments.manager_of(person, org)
    if head is not None and head.pk != person.pk and head.status == approved:
        return [head]
    branch = person.home_branch
    if branch is not None and branch.manager_id and branch.manager_id != person.pk:
        manager = (
            Membership.objects.filter(pk=branch.manager_id, status=approved)
            .select_related("user", "role", "company")
            .first()
        )
        if manager is not None:
            return [manager]
    return hr_notify.recipients(person)


def late(policy: Policy, rows: list[PolicyAcknowledgement]) -> int:
    """The people late with `policy`'s signature, to each one's manager: one message per manager
    naming everyone of theirs."""
    org = departments.Org(policy.company_id)
    people: dict[int, list[PolicyAcknowledgement]] = defaultdict(list)
    readers: dict[int, Membership] = {}
    for row in rows:
        for manager in managers_of(row.membership, org):
            readers[manager.pk] = manager
            people[manager.pk].append(row)
    sent = 0
    for manager_id, items in people.items():
        names = sorted((str(row.membership) for row in items), key=str.casefold)
        due_on = min(row.due_on for row in items)
        sent += len(
            inbox.notify(
                [readers[manager_id]],
                POLICY_LATE,
                title=lambda reader: bot_messages.late_title(policy.title),
                body=lambda reader, names=names, due_on=due_on: bot_messages.late_body(
                    names, due_on
                ),
                url=f"/c/{policy.company_id}/hr/policies/{policy.pk}?state=late",
                target=policy,
                severity="warning",
                dedupe_key=f"{POLICY_LATE}:{policy.ack_version_id}:{manager_id}:"
                f"{_digest(row.pk for row in items)}",
            )
        )
    return sent
