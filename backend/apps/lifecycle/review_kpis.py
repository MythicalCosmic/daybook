"""A person's numbers for a review's period (docs/PLAN-OWNER.md §13.4 `Review.kpis`), read from
the apps that own them, and only from those switched on for the company:

- shared tasks (`apps.reports.kpis.team`): on time, late, missed;
- attendance (`apps.attendance.queries.period_summary`): days scheduled and worked, late
  arrivals, absences;
- disciplinary records given in the period (`apps.lifecycle.queries`);
- the till, when they ran one (`apps.sales.queries.cashier_scorecard`): shifts, sales, average
  receipt, how often the cash matched, shortages;
- training (`apps.learning.queries.person_learning`): courses done, open and late;
- the goals of their earlier reviews: reached, not reached, open.

`snapshot(review)` is taken once, when the reviewer first opens the review, and stored on it,
so the numbers never change later. A block is None while its module is off (or, for the till,
when they never ran one). Money is a string; percentages are strings with one decimal.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.hr import queries as hr_queries
from apps.lifecycle.models import DisciplinaryRecord, Review, ReviewGoal

BLOCKS = ("tasks", "attendance", "discipline", "sales", "learning", "goals")


def snapshot(review: Review, now: datetime | None = None) -> dict:
    """Every block for the review's period (up to today when the period hasn't ended)."""
    now = now or timezone.now()
    person = review.membership
    company = person.company
    cycle = review.cycle
    start = cycle.period_start
    end = min(cycle.period_end, hr_queries.today(company, now))
    if end < start:
        end = start
    return {
        "taken_at": now.isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "tasks": tasks(person, start, end, now),
        "attendance": attendance(person, start, end),
        "discipline": discipline(person, start, end),
        "sales": sales(person, start, end),
        "learning": learning(person, now),
        "goals": goals(review),
    }


def tasks(person, start: date, end: date, now: datetime) -> dict:
    """Shared work due in the period (personal tasks never count)."""
    from apps.reports import kpis

    report = kpis.team(person.company, start, end + timedelta(days=1), now, branch_ids=None)
    score = next((score for member, score in report.rows if member.pk == person.pk), None)
    score = score or kpis.Score()
    return {
        "total": score.total,
        "on_time": score.on_time,
        "late": score.late,
        "missed": score.missed,
        "on_time_percent": _one_decimal(score.on_time_exact),
    }


def attendance(person, start: date, end: date) -> dict | None:
    company = person.company
    if not company.has_feature("attendance"):
        return None
    from apps.attendance import queries

    found = queries.period_summary(company, start, end, branch_ids=None, member_ids=[person.pk])
    row = found.get(person.pk)
    if row is None:
        return {
            "scheduled_days": 0,
            "attended_days": 0,
            "absent_days": 0,
            "late_arrivals": 0,
            "late_minutes": 0,
            "leave_days": 0,
            "worked_hours": "0.0",
        }
    hours = (Decimal(row.worked_minutes) / Decimal(60)).quantize(Decimal("0.1"))
    return {
        "scheduled_days": row.scheduled_days,
        "attended_days": row.attended_days,
        "absent_days": row.absent_days,
        "late_arrivals": row.late_arrivals,
        "late_minutes": row.late_minutes,
        "leave_days": row.leave_days,
        "worked_hours": str(hours),
    }


def discipline(person, start: date, end: date) -> dict:
    """Records given in the period (withdrawn ones aside), by kind."""
    rows = DisciplinaryRecord.objects.filter(
        membership=person, issued_on__range=(start, end)
    ).exclude(status=DisciplinaryRecord.Status.WITHDRAWN)
    kinds: dict[str, int] = {}
    for kind in rows.values_list("kind", flat=True):
        kinds[kind] = kinds.get(kind, 0) + 1
    return {"records": sum(kinds.values()), "by_kind": kinds}


def sales(person, start: date, end: date) -> dict | None:
    """Their tills in the period; None when sales is off or they ran none."""
    company = person.company
    if not company.has_feature("sales"):
        return None
    from apps.sales import queries

    rows = queries.cashier_scorecard(company, start, end, branch_ids=None)
    row = next((row for row in rows if (row.get("member") or {}).get("id") == person.pk), None)
    if row is None:
        return None
    return {
        "shifts": row["shifts"],
        "net": row["net"],
        "receipts": row["receipts"],
        "avg_check": row["avg_check"],
        "accuracy": row["accuracy"],
        "shortages": row["shortages"],
        "shortage_total": row["shortage_total"],
        "currency": company.base_currency,
    }


def learning(person, now: datetime) -> dict | None:
    """Their training as it stands: courses done, still open, late."""
    from apps.learning import conf

    if not conf.is_on(person.company):
        return None
    from apps.learning import queries

    summary = queries.person_learning(person, now=now)["summary"]
    return {
        "completed": summary["completed"],
        "open": summary["open"],
        "late": summary["late"],
    }


def goals(review: Review) -> dict | None:
    """The goals their earlier published reviews set, by how they went; None without any."""
    rows = ReviewGoal.objects.filter(
        membership_id=review.membership_id, review__published_at__isnull=False
    ).exclude(review=review)
    found = {status: 0 for status in ReviewGoal.Status.values}
    for status in rows.values_list("status", flat=True):
        found[status] += 1
    return found if any(found.values()) else None


def _one_decimal(value) -> str | None:
    if value is None:
        return None
    return str(Decimal(str(value)).quantize(Decimal("0.1")))
