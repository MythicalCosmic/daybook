"""Who hears about courses, through the inbox (`apps.inbox.services.notify`), docs/PLAN-LEARNING.md
§4.5 and §9.1. Plain words, no emoji; each text is worded in the reader's language.

- `learning.assigned`: the learner, once per burst (a new hire given four mandatory courses at
  once hears one message);
- `learning.due_soon`, `learning.overdue`: the learner, from the morning reminder run;
- `learning.escalated`: a manager, one digest of the people late with training;
- `learning.certificate`: the learner, when a course gives a certificate.

The mini app opens `course:<id>` (one course) or `learning` (several); managers get the
dashboard's people page.
"""

from __future__ import annotations

import contextvars
from collections import defaultdict
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

from django.db import transaction
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.inbox import services as inbox
from apps.learning import queries
from apps.learning.models import Assignment
from apps.members.models import Membership

ASSIGNED = "learning.assigned"
DUE_SOON = "learning.due_soon"
OVERDUE = "learning.overdue"
ESCALATED = "learning.escalated"
CERTIFICATE = "learning.certificate"
HOME_SCREEN = "learning"
LIST_LIMIT = 8

_collecting: contextvars.ContextVar[list[int] | None] = contextvars.ContextVar(
    "learning_assigned_burst", default=None
)


def course_screen(course_id: int) -> str:
    return f"course:{course_id}"


def _screen(rows: list[Assignment]) -> str:
    courses = {row.course_id for row in rows}
    return course_screen(rows[0].course_id) if len(courses) == 1 else HOME_SCREEN


def _day(company, moment) -> str:
    return queries.local_day(company, moment).strftime("%d.%m.%Y")


def _people_url(company_id: int) -> str:
    return f"/c/{company_id}/learning/people"


def _course_lines(company, rows: list[Assignment]) -> str:
    """One line per course: "Sovuq zanjir, due 14.11.2026"."""
    lines = []
    for row in rows[:LIST_LIMIT]:
        if row.due_at is None:
            lines.append(row.course.title)
        else:
            lines.append(
                _("%(course)s, due %(date)s")
                % {"course": row.course.title, "date": _day(company, row.due_at)}
            )
    return "\n".join(lines)


# Assigned -------------------------------------------------------------------------------


@contextmanager
def collecting() -> Iterator[None]:
    """Hold back the "new training" messages of every `assign` inside, then send each person
    one message for all of them (after the commit)."""
    if _collecting.get() is not None:
        yield
        return
    ids: list[int] = []
    token = _collecting.set(ids)
    try:
        yield
    finally:
        _collecting.reset(token)
        if ids:
            transaction.on_commit(lambda: send_assigned(ids))


def assigned(assignments: Iterable[Assignment]) -> None:
    ids = [row.pk for row in assignments]
    if not ids:
        return
    held = _collecting.get()
    if held is not None:
        held.extend(ids)
    else:
        transaction.on_commit(lambda: send_assigned(ids))


def send_assigned(ids: list[int]) -> int:
    rows = (
        Assignment.objects.filter(pk__in=ids, state__in=queries.OPEN)
        .select_related("course", "membership__user", "membership__company")
        .order_by("due_at", "pk")
    )
    by_person: dict[int, list[Assignment]] = defaultdict(list)
    for row in rows:
        by_person[row.membership_id].append(row)
    sent = 0
    for items in by_person.values():
        person = items[0].membership
        company = person.company

        def title(reader, items=items):
            if len(items) == 1:
                return _("New training: %(course)s") % {"course": items[0].course.title}
            return ngettext(
                "New training: %(count)s course", "New training: %(count)s courses", len(items)
            ) % {"count": len(items)}

        def body(reader, items=items, company=company):
            if len(items) == 1:
                row = items[0]
                if row.due_at is None:
                    return _("Open it in the app when you have a moment.")
                return _("Finish it by %(date)s.") % {"date": _day(company, row.due_at)}
            return _course_lines(company, items)

        sent += len(
            inbox.notify(
                [person],
                ASSIGNED,
                title=title,
                body=body,
                app_screen=_screen(items),
                target=items[0],
                dedupe_key=f"learning.assigned:{items[0].pk}",
            )
        )
    return sent


# Deadlines ------------------------------------------------------------------------------


def due_soon(person: Membership, rows: list[Assignment]) -> int:
    company = person.company

    def title(reader):
        if len(rows) == 1:
            return _("Training due %(date)s: %(course)s") % {
                "date": _day(company, rows[0].due_at),
                "course": rows[0].course.title,
            }
        return ngettext(
            "%(count)s training is due soon", "%(count)s trainings are due soon", len(rows)
        ) % {"count": len(rows)}

    def body(reader):
        if len(rows) == 1:
            row = rows[0]
            return _("Done: %(done)s of %(total)s steps.") % {
                "done": row.steps_done,
                "total": row.steps_total,
            }
        return _course_lines(company, rows)

    return len(
        inbox.notify(
            [person],
            DUE_SOON,
            title=title,
            body=body,
            app_screen=_screen(rows),
            target=rows[0],
            dedupe_key=f"learning.due_soon:{'-'.join(str(row.pk) for row in rows)}"[:120],
        )
    )


def overdue(person: Membership, rows: list[Assignment], *, day) -> int:
    company = person.company

    def title(reader):
        if len(rows) == 1:
            return _("Training is late: %(course)s") % {"course": rows[0].course.title}
        return ngettext("%(count)s training is late", "%(count)s trainings are late", len(rows)) % {
            "count": len(rows)
        }

    def body(reader):
        if len(rows) == 1:
            return _("It was due %(date)s. Finish it as soon as you can.") % {
                "date": _day(company, rows[0].due_at)
            }
        return "\n".join(
            _("%(course)s, was due %(date)s")
            % {"course": row.course.title, "date": _day(company, row.due_at)}
            for row in rows[:LIST_LIMIT]
        )

    return len(
        inbox.notify(
            [person],
            OVERDUE,
            title=title,
            body=body,
            app_screen=_screen(rows),
            target=rows[0],
            severity="warning",
            dedupe_key=f"learning.overdue:{person.pk}:{day.isoformat()}",
        )
    )


def escalated(manager: Membership, late: list[tuple[Membership, Assignment, int]], *, day) -> int:
    """`late`: (person, assignment, days late), most days late first."""
    people = {person.pk for person, _row, _days in late}

    def title(reader):
        return ngettext(
            "%(count)s person is late with training",
            "%(count)s people are late with training",
            len(people),
        ) % {"count": len(people)}

    def body(reader):
        return "\n".join(
            ngettext(
                "%(name)s: %(course)s, %(days)s day late",
                "%(name)s: %(course)s, %(days)s days late",
                days,
            )
            % {"name": str(person), "course": row.course.title, "days": days}
            for person, row, days in late[:LIST_LIMIT]
        )

    return len(
        inbox.notify(
            [manager],
            ESCALATED,
            title=title,
            body=body,
            url=f"{_people_url(manager.company_id)}?late=1",
            target=late[0][1],
            severity="warning",
            dedupe_key=f"learning.escalated:{manager.pk}:{day.isoformat()}",
        )
    )


def remind(person: Membership, rows: list[Assignment], *, by: Membership) -> int:
    """A manager's "Remind" on the course's people tab."""
    company = person.company

    def title(reader):
        if len(rows) == 1:
            return _("A reminder about your training: %(course)s") % {
                "course": rows[0].course.title
            }
        return ngettext(
            "A reminder about %(count)s training",
            "A reminder about %(count)s trainings",
            len(rows),
        ) % {"count": len(rows)}

    def body(reader):
        return _course_lines(company, rows)

    kind = OVERDUE if any(row.due_at and row.due_at < _now() for row in rows) else DUE_SOON
    return len(
        inbox.notify(
            [person],
            kind,
            title=title,
            body=body,
            app_screen=_screen(rows),
            target=rows[0],
            actor=by,
        )
    )


def _now():
    from django.utils import timezone

    return timezone.now()


# Certificates ---------------------------------------------------------------------------


def certificate(assignment: Assignment) -> int:
    person = assignment.membership
    course = assignment.course
    return len(
        inbox.notify(
            [person],
            CERTIFICATE,
            title=lambda reader: _("Certificate ready: %(course)s") % {"course": course.title},
            body=lambda reader: (
                _("Well done, you finished the course. Certificate number: %(number)s.")
                % {"number": assignment.certificate_no}
            ),
            app_screen=course_screen(course.pk),
            target=assignment,
            dedupe_key=f"learning.certificate:{assignment.pk}",
        )
    )
