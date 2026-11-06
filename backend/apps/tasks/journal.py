"""The temperature and humidity log (PLAN-OWNER §14.10): readings as journal rows, one
routine's journal (rows and a series per key, for the chart with its allowed band), today's
excursions and missed readings, and the branch's monthly log as a PDF.

`queries.readings_journal` and `queries.readings_pdf` are the contract other apps call (N's
inspection pack); this module holds the work.
"""

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db.models import QuerySet
from django.utils import formats, timezone, translation
from django.utils.translation import gettext as _

from apps.companies.models import Branch
from apps.core import pdf
from apps.tasks import queries
from apps.tasks.models import Proof, Task, TaskReading, TaskTemplate
from apps.tasks.readings import range_text, taken_row, value_text

FINISHED = (Task.Status.DONE, Task.Status.REVIEW)


def readings_in(
    company, start: date, end: date, *, branch_ids: list[int] | None, template_id=None
) -> QuerySet[TaskReading]:
    """Readings recorded on the company's days `start` to `end` (both included), in the
    branch scope (`branch_ids` None: every branch; rows without a branch only then)."""
    first = queries.day_bounds(company, start)[0]
    last = queries.day_bounds(company, end)[1]
    rows = TaskReading.objects.for_company(company).filter(
        recorded_at__gte=first, recorded_at__lt=last
    )
    if branch_ids is not None:
        rows = rows.filter(branch_id__in=branch_ids)
    if template_id is not None:
        rows = rows.filter(template_id=template_id)
    return rows.select_related("recorded_by__user", "branch", "template").order_by(
        "recorded_at", "pk"
    )


def row(reading: TaskReading, tz: ZoneInfo) -> dict:
    """A reading as the journal lists it."""
    local = timezone.localtime(reading.recorded_at, tz)
    branch = reading.branch
    template = reading.template
    return taken_row(reading) | {
        "task_id": reading.task_id,
        "day": local.date(),
        "time": local.strftime("%H:%M"),
        "branch": {"id": branch.pk, "name": branch.name, "code": branch.code} if branch else None,
        "routine": {"id": template.pk, "title": template.title} if template else None,
    }


def journal_rows(
    company, start: date, end: date, *, branch_ids: list[int] | None, template_id=None
) -> list[dict]:
    tz = ZoneInfo(company.timezone)
    return [
        row(reading, tz)
        for reading in readings_in(
            company, start, end, branch_ids=branch_ids, template_id=template_id
        )
    ]


def routine_journal(template: TaskTemplate, start: date, end: date, now: datetime) -> dict:
    """One routine's journal: its readings, a series per key (each day's first measurement,
    rechecks stay in the rows), and the days its readings were missed."""
    company = template.company
    rows = journal_rows(company, start, end, branch_ids=None, template_id=template.pk)
    first_of_day: dict[date, dict[str, str]] = defaultdict(dict)
    for item in rows:
        if not item["is_recheck"]:
            first_of_day[item["day"]].setdefault(item["key"], item["value"])
    keys = [spec["key"] for spec in template.readings] or sorted({item["key"] for item in rows})
    span = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    series = [
        {"date": day, **{key: first_of_day.get(day, {}).get(key) for key in keys}} for day in span
    ]
    missed = missed_days(template, start, end, now)
    excursions = sum(1 for item in rows if not item["in_range"] and not item["is_recheck"])
    return {
        "range": {"from": start, "to": end},
        "specs": template.readings,
        "totals": {
            "taken": sum(1 for item in rows if not item["is_recheck"]),
            "excursions": excursions,
            "rechecks": sum(1 for item in rows if item["is_recheck"]),
            "missed": len(missed),
        },
        "series": series,
        "missed": missed,
        "rows": rows,
    }


def missed_days(template: TaskTemplate, start: date, end: date, now: datetime) -> list[date]:
    """Days the routine's readings were due and nobody took them by the end of the day."""
    runs = (
        Task.objects.filter(template=template, for_date__range=(start, end))
        .exclude(status=Task.Status.CANCELLED)
        .values_list("for_date", "status")
    )
    finished: dict[date, bool] = {}
    for day, status in runs:
        finished[day] = finished.get(day, False) or status in FINISHED
    return sorted(
        day
        for day, done in finished.items()
        if not done and now >= queries.day_bounds(template.company, day)[1]
    )


# Today: the Overview widget and the pulse ----------------------------------------------------


def reading_routines(company_id: int, branch_ids: list[int] | None) -> QuerySet[TaskTemplate]:
    routines = TaskTemplate.objects.for_company(company_id).filter(
        proof=Proof.READINGS, personal=False, onboarding=False
    )
    if branch_ids is not None:
        routines = routines.filter(branch_id__in=branch_ids)
    return routines


def today(company, now: datetime, *, branch_ids: list[int] | None) -> dict:
    """Today's excursions (first measurements out of range, and whether a recheck brought them
    back) and missed readings (routine runs past their time with nothing taken), in the branch
    scope. `set_up` is False while the company has no readings routine."""
    tz = ZoneInfo(company.timezone)
    day = queries.company_today(company, now)
    set_up = reading_routines(company.pk, branch_ids).filter(is_active=True).exists()
    readings = list(readings_in(company, day, day, branch_ids=branch_ids))
    by_task: dict[int, list[TaskReading]] = defaultdict(list)
    for reading in readings:
        by_task[reading.task_id].append(reading)
    excursions = []
    for reading in readings:
        if reading.in_range or reading.is_recheck:
            continue
        back = next(
            (
                later
                for later in by_task[reading.task_id]
                if later.is_recheck and later.key == reading.key and later.in_range
            ),
            None,
        )
        excursions.append(
            row(reading, tz) | {"back_in_range_at": back.recorded_at if back is not None else None}
        )
    runs = (
        Task.objects.for_company(company)
        .filter(
            queries.ROUTINE_WORK,
            proof=Proof.READINGS,
            for_date=day,
            due_at__lt=now,
            status__in=Task.OPEN_STATUSES,
        )
        .select_related("template__branch", "branch")
        .order_by("due_at", "pk")
    )
    if branch_ids is not None:
        runs = runs.filter(branch_id__in=branch_ids)
    # A shared routine's copies are one run: missed when none of them was taken.
    finished = set(
        Task.objects.for_company(company)
        .filter(queries.ROUTINE_WORK, proof=Proof.READINGS, for_date=day, status__in=FINISHED)
        .values_list("template_id", "branch_id")
    )
    missed, seen = [], set()
    for task in runs:
        key = (task.template_id, task.branch_id)
        if key in seen or (task.template.shared and key in finished):
            continue
        seen.add(key)
        branch = task.branch
        missed.append(
            {
                "task_id": task.pk,
                "routine": {"id": task.template_id, "title": task.template.title},
                "branch": (
                    {"id": branch.pk, "name": branch.name, "code": branch.code} if branch else None
                ),
                "due_at": task.due_at,
                "assignee": None if task.template.shared else str(task.assignee),
            }
        )
    return {
        "day": day,
        "set_up": set_up,
        "taken": sum(1 for reading in readings if not reading.is_recheck),
        "excursions": excursions,
        "missed": missed,
    }


def open_excursions(company, now: datetime, *, branch_ids: list[int] | None) -> int:
    """Today's values still out of range (the latest measurement of a task's key is): the
    sidebar badge, in one query."""
    day = queries.company_today(company, now)
    first, last = queries.day_bounds(company, day)
    rows = TaskReading.objects.for_company(company).filter(
        recorded_at__gte=first, recorded_at__lt=last
    )
    if branch_ids is not None:
        rows = rows.filter(branch_id__in=branch_ids)
    latest: dict[tuple[int, str], bool] = {}
    for task_id, key, in_range in rows.order_by("recorded_at", "pk").values_list(
        "task_id", "key", "in_range"
    ):
        latest[(task_id, key)] = in_range
    return sum(1 for in_range in latest.values() if not in_range)


# The month's log as a PDF ---------------------------------------------------------------------


def month_days(month: date, today_: date) -> list[date]:
    """The month's days, up to today for the current month (a log has no future rows)."""
    last = calendar.monthrange(month.year, month.month)[1]
    days = [month.replace(day=number) for number in range(1, last + 1)]
    return [day for day in days if day <= today_]


def pdf_context(branch: Branch, month: date) -> dict:
    """The log of `branch` for `month`, in the active language: one section per instrument
    (the spec's label and unit, so a morning and an evening routine share a page), each day
    of the month with its readings (time, value, range, who, note, rechecks) and a signature
    line."""
    company = branch.company
    tz = ZoneInfo(company.timezone)
    month = month.replace(day=1)
    end = month.replace(day=calendar.monthrange(month.year, month.month)[1])
    language = translation.get_language()
    readings = list(readings_in(company, month, end, branch_ids=[branch.pk]))
    groups: dict[tuple[str, str], list[TaskReading]] = defaultdict(list)
    for reading in readings:
        groups[(reading.label, reading.unit)].append(reading)
    # Every readings routine of the branch has its page, even in a month nobody took one.
    for template in reading_routines(company.pk, [branch.pk]).filter(is_active=True):
        for spec in template.readings:
            groups.setdefault((spec["label"], spec.get("unit", "")), [])
    days = month_days(month, queries.company_today(company))
    sections = []
    for (label, unit), rows in sorted(groups.items(), key=lambda item: item[0][0].lower()):
        by_day: dict[date, list[TaskReading]] = defaultdict(list)
        for reading in rows:
            by_day[timezone.localtime(reading.recorded_at, tz).date()].append(reading)
        ranges = sorted(
            {range_text(reading.min, reading.max, reading.unit, language) for reading in rows}
        )
        section_days = []
        for day in days:
            entries = [
                {
                    "time": timezone.localtime(reading.recorded_at, tz).strftime("%H:%M"),
                    "value": value_text(reading.value, reading.unit, language),
                    "range": range_text(reading.min, reading.max, reading.unit, language),
                    "in_range": reading.in_range,
                    "recheck": reading.is_recheck,
                    "who": str(reading.recorded_by) if reading.recorded_by_id else "",
                    "note": reading.note,
                }
                for reading in by_day.get(day, [])
            ]
            section_days.append(
                {
                    "date": formats.date_format(day, "d.m.Y"),
                    "entries": entries,
                    "rows": max(1, len(entries)),
                }
            )
        sections.append(
            {
                "label": label,
                "unit": unit,
                "ranges": ", ".join(ranges),
                "days": section_days,
                "excursions": sum(1 for r in rows if not r.in_range and not r.is_recheck),
            }
        )
    title = _("Temperature and humidity log")
    return {
        "company": company,
        "title": title,
        "branch": branch.name,
        "month": formats.date_format(month, "F Y"),
        "printed_on": formats.date_format(queries.company_today(company), "d.m.Y"),
        "sections": sections,
        "empty": not sections,
    }


def render(branch: Branch, month: date, *, language: str) -> bytes:
    branch = Branch.objects.select_related("company").get(pk=branch.pk)
    with translation.override(language):
        data = pdf_context(branch, month)
    return pdf.render_pdf("tasks/readings_journal.html", data, language=language)


def file_name(branch: Branch, month: date) -> str:
    code = (branch.code or str(branch.pk)).lower()
    return f"readings-{code}-{month:%Y-%m}.pdf"


def pdf_link(branch: Branch, month: date, request) -> dict:
    """Render the month's log in the reader's language, keep it in private storage (one file
    per branch, month and language, replaced on each render) and hand out a short-lived link."""
    from django.core.files.base import ContentFile

    from apps.core.files import DEFAULT_TTL, signed_url
    from apps.core.storage import private_storage

    language = (translation.get_language() or branch.company.default_language)[:2]
    data = render(branch, month, language=language)
    name = f"tasks/readings/{branch.company_id}/{branch.pk}-{month:%Y-%m}-{language}.pdf"
    if private_storage.exists(name):
        private_storage.delete(name)
    stored = private_storage.save(name, ContentFile(data))
    filename = file_name(branch, month)
    url = signed_url(
        stored,
        user=request.user,
        company_id=branch.company_id,
        check=f"tasks.readings_pdf:{branch.pk}",
        filename=filename,
    )
    return {"url": url, "name": filename, "expires_in": DEFAULT_TTL}


def pdf_check(user, company_id: int, branch_id: int) -> bool:
    """A log PDF opens for whoever sees everyone's work or plans routines at that branch."""
    from apps.members.models import Membership
    from apps.members.permissions import Perm
    from apps.members.scope import branch_ids

    viewer = (
        Membership.objects.select_related("role", "company")
        .filter(company_id=company_id, user=user, status=Membership.Status.APPROVED)
        .first()
    )
    if viewer is None or not (
        viewer.has_perm(Perm.TASKS_VIEW_ALL) or viewer.has_perm(Perm.TASKS_TEMPLATES)
    ):
        return False
    if not Branch.objects.filter(company_id=company_id, pk=branch_id).exists():
        return False
    scope = branch_ids(viewer)
    return scope is None or branch_id in scope


def plain_value(value) -> str | None:
    from apps.tasks.readings import plain

    return plain(value)
