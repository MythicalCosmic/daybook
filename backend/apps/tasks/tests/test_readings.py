"""Storage readings on routines (PLAN-OWNER §14.10): a routine asks for numbers within an
allowed range (a fridge's 2 to 8 °C), its runs are completed by typing them, a value out of
range needs a note and alerts the people who look after storage at once, a recheck brings it
back, "one of us does it" closes the colleagues' copies, the storage preset sets a branch up,
and the month's log is a PDF.

The clock is frozen on Wednesday 23 October 2030, 12:00 in the company's timezone."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import PermissionDenied

from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.inbox.models import Notification
from apps.members.tests.factories import PositionFactory
from apps.reports import kpis
from apps.tasks import generation, journal, presets, readings, services
from apps.tasks.audit_actions import TasksAction
from apps.tasks.conf import get_settings
from apps.tasks.models import Activity, Proof, Task, TaskReading, TaskTemplate
from apps.tasks.tests.factories import TaskFactory, TaskTemplateFactory, make_shop

pytestmark = pytest.mark.django_db

WED = date(2030, 10, 23)
FRIDGE = {"key": "t", "label": "Fridge 1 (vaccines)", "unit": "°C", "min": "2", "max": "8"}
ALERT = "tasks.reading_out_of_range"


@pytest.fixture
def clock(monkeypatch):
    def set_now(moment: datetime) -> datetime:
        monkeypatch.setattr("django.utils.timezone.now", lambda: moment)
        return moment

    return set_now


@pytest.fixture
def tz(company):
    return ZoneInfo(company.timezone)


@pytest.fixture
def at(tz):
    def make(day: date, hour: int, minute: int = 0) -> datetime:
        return datetime.combine(day, time(hour, minute), tzinfo=tz)

    return make


@pytest.fixture
def shop(company, member, clock, at):
    clock(at(WED, 12) - timedelta(days=40))
    made = make_shop(company, member)
    clock(at(WED, 12))
    return made


def fridge_routine(shop, *, specs=None, people=None, branch=None, **fields) -> TaskTemplate:
    """A readings routine at `here` for the worker, made long ago."""
    values = {
        "title": "Fridge temperature",
        "due_time": time(9, 0),
        "proof": Proof.READINGS,
        "readings": [{**FRIDGE, "critical": True}] if specs is None else specs,
        "branch": branch or shop.here,
        "assignees": people if people is not None else [shop.worker],
    } | fields
    template = services.create_template(by=shop.owner, **values)
    TaskTemplate.objects.filter(pk=template.pk).update(
        created_at=template.created_at - timedelta(days=30)
    )
    template.refresh_from_db()
    return template


def run_of(template, person, day=WED, at_=None) -> Task:
    """The routine's task of `day` for `person`, as daily generation makes it."""
    tz = ZoneInfo(template.company.timezone)
    due = generation.deadline(template, day, tz)
    [task] = generation.build_tasks(
        template, day, due, people=[person], created_by=template.created_by, now=due
    )
    task.save()
    return task


# The routine's specs ---------------------------------------------------------------------


def test_a_readings_routine_keeps_clean_specs(shop):
    template = fridge_routine(
        shop,
        specs=[
            {"label": "  Fridge 1   (vaccines) ", "unit": "°C", "min": "2,0", "max": 8},
            {"key": "h", "label": "Humidity", "unit": "%", "max": "60"},
        ],
    )

    assert template.readings == [
        {
            "key": "a",
            "label": "Fridge 1 (vaccines)",
            "unit": "°C",
            "min": "2.0",
            "max": "8.0",
            "critical": False,
        },
        {
            "key": "h",
            "label": "Humidity",
            "unit": "%",
            "min": None,
            "max": "60.0",
            "critical": False,
        },
    ]


@pytest.mark.parametrize(
    "specs, problem",
    [
        ([], "at least one reading"),
        ([{"label": "", "unit": "°C"}], "Name each reading"),
        ([FRIDGE, FRIDGE], "its own key"),
        ([{**FRIDGE, "min": "9"}], "can't be above"),
        ([{**FRIDGE, "max": "500"}], "−50 to 100"),
        ([{**FRIDGE, "key": "tt"}], "one letter"),
        (
            [FRIDGE, {**FRIDGE, "key": "b"}, {**FRIDGE, "key": "c"}, {**FRIDGE, "key": "d"}],
            "at most",
        ),
    ],
)
def test_a_readings_routine_without_proper_specs_is_refused(shop, specs, problem):
    with pytest.raises(DomainError, match=problem):
        fridge_routine(shop, specs=specs)


def test_specs_go_only_with_the_readings_proof(shop):
    with pytest.raises(DomainError, match="Readings proof"):
        fridge_routine(shop, proof=Proof.PHOTO)
    template = fridge_routine(shop)

    # Moved to another proof, the routine drops its specs.
    services.update_template(template, by=shop.owner, proof=Proof.PHOTO)

    template.refresh_from_db()
    assert template.proof == Proof.PHOTO and template.readings == []


def test_onboarding_and_personal_templates_take_no_readings(shop):
    with pytest.raises(DomainError, match="not on onboarding or personal"):
        fridge_routine(shop, onboarding=True)
    personal = TaskTemplateFactory(company=shop.company, personal=True, assignees=[shop.worker])
    with pytest.raises(DomainError, match="not on onboarding or personal"):
        services.update_template(personal, by=shop.owner, readings=[FRIDGE])
    with pytest.raises(DomainError, match="Only routines can be shared"):
        services.create_template(
            by=shop.owner,
            title="Welcome",
            due_time=time(10),
            onboarding=True,
            shared=True,
        )


def test_one_off_work_takes_no_readings(shop):
    with pytest.raises(DomainError, match="taken on routines"):
        services.create_task(
            by=shop.owner, title="Check the fridge", assignee=shop.worker, proof=Proof.READINGS
        )


# Its tasks carry a copy -----------------------------------------------------------------


def test_generated_and_given_today_tasks_copy_the_specs(shop, clock, at):
    template = fridge_routine(shop)
    generation.generate_daily_tasks(shop.company, WED)
    made = Task.objects.get(template=template, for_date=WED)

    late = fridge_routine(shop, people=[shop.worker])
    TaskTemplate.objects.filter(pk=late.pk).update(created_at=at(WED, 11))
    given = services.give_routine_today(late, by=shop.owner)

    assert made.proof == Proof.READINGS and made.readings == template.readings
    assert [task.readings for task in given] == [late.readings]


def test_a_later_routine_edit_leaves_the_tasks_specs_alone(shop):
    template = fridge_routine(shop)
    task = run_of(template, shop.worker)

    services.update_template(template, by=shop.owner, readings=[{**FRIDGE, "min": "3", "max": "7"}])

    task.refresh_from_db()
    assert task.readings[0]["min"] == "2.0" and task.readings[0]["max"] == "8.0"
    assert TaskTemplate.objects.get(pk=template.pk).readings[0]["min"] == "3.0"


# Completing with readings ---------------------------------------------------------------


def test_a_value_in_range_completes_the_run(shop):
    task = run_of(fridge_routine(shop), shop.worker)

    services.complete_task(task, by=shop.worker, readings={"t": "5.0"})

    task.refresh_from_db()
    [reading] = task.readings_taken.all()
    assert task.status == Task.Status.DONE
    assert (reading.value, reading.in_range, reading.label, reading.unit) == (
        Decimal("5.00"),
        True,
        "Fridge 1 (vaccines)",
        "°C",
    )
    assert (reading.min, reading.max, reading.branch, reading.template_id) == (
        Decimal("2.00"),
        Decimal("8.00"),
        shop.here,
        task.template_id,
    )
    assert not Notification.objects.filter(kind=ALERT).exists()


@pytest.mark.parametrize("typed", ["5,2", "5.2", " +5,2 °C", "5.20"])
def test_a_decimal_comma_or_point_reads_the_same(shop, typed):
    task = run_of(fridge_routine(shop), shop.worker)

    services.complete_task(task, by=shop.worker, readings={"t": typed})

    assert task.readings_taken.get().value == Decimal("5.2")


def test_a_missing_or_wrong_value_is_refused(shop):
    template = fridge_routine(
        shop, specs=[FRIDGE, {"key": "h", "label": "Humidity", "unit": "%", "max": "60"}]
    )
    task = run_of(template, shop.worker)

    with pytest.raises(DomainError, match="Enter the readings"):
        services.complete_task(task, by=shop.worker)
    with pytest.raises(DomainError, match="missing: Humidity"):
        services.complete_task(task, by=shop.worker, readings={"t": "5"})
    with pytest.raises(DomainError, match="type a number"):
        services.complete_task(task, by=shop.worker, readings={"t": "five", "h": "40"})
    with pytest.raises(DomainError, match="can't be right"):
        services.complete_task(task, by=shop.worker, readings={"t": "150", "h": "40"})
    with pytest.raises(DomainError, match="doesn't ask for"):
        services.complete_task(task, by=shop.worker, readings={"t": "5", "h": "40", "x": "1"})

    task.refresh_from_db()
    assert task.is_open and not task.readings_taken.exists()


def test_out_of_range_needs_a_note_and_then_alerts_once(shop):
    template = fridge_routine(
        shop,
        specs=[
            {**FRIDGE, "critical": True},
            {"key": "h", "label": "Humidity", "unit": "%", "max": "60"},
        ],
    )
    task = run_of(template, shop.worker)

    with pytest.raises(DomainError, match="out of range"):
        services.complete_task(task, by=shop.worker, readings={"t": "8.5", "h": "70"})
    services.complete_task(
        task,
        by=shop.worker,
        readings={"t": "8,5", "h": "70"},
        reading_note="Moved the vaccines to the spare fridge",
    )

    alerts = Notification.objects.filter(kind=ALERT)
    recipients = {alert.recipient_id for alert in alerts}
    # Whoever may confirm tasks at the branch, and the owners; once each for the completion.
    assert shop.owner.pk in recipients and shop.manager.pk in recipients
    assert shop.worker.pk not in recipients
    assert alerts.count() == len(recipients)
    alert = alerts.get(recipient=shop.owner)
    assert alert.severity == "critical"
    assert "8,5 °C" in alert.title or "8.5 °C" in alert.title
    assert "Moved the vaccines" in alert.body
    assert {row["key"] for row in alert.data["readings"]} == {"t", "h"}
    notes = set(task.readings_taken.values_list("note", flat=True))
    assert notes == {"Moved the vaccines to the spare fridge"}


def test_the_escalation_contact_hears_instead_of_the_checkers(shop):
    template = fridge_routine(shop, escalate_to=shop.lead)
    task = run_of(template, shop.worker)

    services.complete_task(task, by=shop.worker, readings={"t": "1"}, reading_note="Door open")

    recipients = set(Notification.objects.filter(kind=ALERT).values_list("recipient", flat=True))
    assert recipients == {shop.lead.pk, shop.owner.pk}


def test_a_non_critical_reading_out_of_range_is_a_warning(shop):
    template = fridge_routine(shop, specs=[{**FRIDGE, "critical": False}])
    task = run_of(template, shop.worker)

    services.complete_task(task, by=shop.worker, readings={"t": "9"}, reading_note="Called")

    assert set(Notification.objects.filter(kind=ALERT).values_list("severity", flat=True)) == {
        "warning"
    }


def test_readings_are_proof_for_the_accept_with_proof_rule(shop):
    template = fridge_routine(shop)
    TaskTemplate.objects.filter(pk=template.pk).update(
        needs_confirmation=True, accept_with_proof=True
    )
    template.refresh_from_db()
    task = run_of(template, shop.worker)

    services.complete_task(task, by=shop.worker, readings={"t": "5"})

    assert Task.objects.get(pk=task.pk).status == Task.Status.DONE


def test_undo_takes_the_readings_back(shop, clock, at):
    task = run_of(fridge_routine(shop), shop.worker)
    services.complete_task(task, by=shop.worker, readings={"t": "85"}, reading_note="Typo")

    clock(at(WED, 12, 0) + timedelta(seconds=30))
    services.reopen_task(task, by=shop.worker)

    assert not TaskReading.objects.filter(task=task).exists()
    assert not Notification.objects.filter(kind=ALERT, acted_at__isnull=True).exists()
    services.complete_task(task, by=shop.worker, readings={"t": "8.5"}, reading_note="Moved")
    assert task.readings_taken.get().value == Decimal("8.5")
    # The second completion alerts again: the first alert was closed by the undo.
    assert Notification.objects.filter(kind=ALERT, acted_at__isnull=True).exists()


# Rechecks --------------------------------------------------------------------------------


def test_a_recheck_in_range_closes_the_alert(shop, clock, at):
    task = run_of(fridge_routine(shop), shop.worker)
    clock(at(WED, 10, 0))
    services.complete_task(task, by=shop.worker, readings={"t": "9"}, reading_note="Moved")
    clock(at(WED, 10, 42))

    services.recheck(task, by=shop.worker, readings={"t": "5,4"})

    rows = list(task.readings_taken.order_by("recorded_at"))
    assert [(row.value, row.in_range, row.is_recheck) for row in rows] == [
        (Decimal("9"), False, False),
        (Decimal("5.4"), True, True),
    ]
    alerts = Notification.objects.filter(kind=ALERT)
    assert alerts.exists() and not alerts.filter(acted_at__isnull=True).exists()
    assert AuditLog.objects.filter(action=TasksAction.RECHECKED, target_id=task.pk).exists()


def test_a_recheck_still_out_of_range_needs_a_note_and_keeps_the_alert(shop, clock, at):
    task = run_of(fridge_routine(shop), shop.worker)
    clock(at(WED, 10))
    services.complete_task(task, by=shop.worker, readings={"t": "9"}, reading_note="Moved")

    with pytest.raises(DomainError, match="out of range"):
        services.recheck(task, by=shop.worker, readings={"t": "8.6"})
    services.recheck(task, by=shop.worker, readings={"t": "8.6"}, note="Called the technician")

    assert Notification.objects.filter(kind=ALERT, acted_at__isnull=True).exists()


def test_a_recheck_comes_within_two_hours_of_a_finished_run(shop, clock, at, member):
    task = run_of(fridge_routine(shop), shop.worker)
    with pytest.raises(DomainError, match="isn't finished"):
        services.recheck(task, by=shop.worker, readings={"t": "5"})
    clock(at(WED, 9))
    services.complete_task(task, by=shop.worker, readings={"t": "9"}, reading_note="Moved")
    stranger = member.registered(shop.company, home_branch=shop.there)
    with pytest.raises(PermissionDenied):
        services.recheck(task, by=stranger, readings={"t": "5"})
    clock(at(WED, 11, 1))
    with pytest.raises(DomainError, match="Too late"):
        services.recheck(task, by=shop.worker, readings={"t": "5"})


# One of us does it -----------------------------------------------------------------------


def test_a_shared_routines_first_completion_closes_the_others_copies(shop, member, clock, at):
    other = member.registered(shop.company, home_branch=shop.here)
    template = fridge_routine(shop, people=[shop.worker, other, shop.colleague], shared=True)
    generation.generate_daily_tasks(shop.company, WED)
    mine = Task.objects.get(template=template, assignee=shop.worker)
    theirs = Task.objects.get(template=template, assignee=other)
    elsewhere = Task.objects.filter(template=template, assignee=shop.colleague).first()

    clock(at(WED, 8, 50))
    services.complete_task(mine, by=shop.worker, readings={"t": "5"})

    theirs.refresh_from_db()
    assert theirs.status == Task.Status.CANCELLED and theirs.next_reminder_at is None
    entry = Activity.objects.get(task=theirs, kind=Activity.Kind.COVERED)
    assert entry.actor == shop.worker and str(shop.worker) in entry.text
    # Another branch's copy (if the routine reaches it) is that branch's to do.
    if elsewhere is not None:
        assert Task.objects.get(pk=elsewhere.pk).is_open
    # Nobody is scored for the copy a colleague closed.
    report = kpis.team(shop.company, WED, WED + timedelta(days=1), at(WED, 23), branch_ids=None)
    scores = {person.pk: score for person, score in report.rows}
    assert scores[other.pk].missed == 0 and scores[other.pk].late == 0
    assert scores[shop.worker.pk].on_time == 1


def test_undoing_a_shared_run_opens_the_others_copies_again(shop, member):
    other = member.registered(shop.company, home_branch=shop.here)
    template = fridge_routine(shop, people=[shop.worker, other], shared=True)
    generation.generate_daily_tasks(shop.company, WED)
    mine = Task.objects.get(template=template, assignee=shop.worker)
    services.complete_task(mine, by=shop.worker, readings={"t": "5"})

    services.reopen_task(mine, by=shop.worker)

    theirs = Task.objects.get(template=template, assignee=other)
    assert theirs.is_open
    assert not Activity.objects.filter(task=theirs, kind=Activity.Kind.COVERED).exists()


# The storage preset ----------------------------------------------------------------------


def test_the_preset_makes_the_branch_routines_from_the_settings(shop, member):
    pharmacist = PositionFactory(company=shop.company, name="Farmatsevt")
    member.registered(shop.company, position=pharmacist, home_branch=shop.here)
    settings = get_settings(shop.company)
    settings.storage_fridge_min, settings.storage_fridge_max = Decimal("2.5"), Decimal("7.5")
    settings.storage_humidity_max = Decimal("55")
    settings.save()

    result = presets.apply_storage_preset(shop.here, by=shop.owner, fridges=2)

    made = {template.title: template for template in result.created}
    morning = made["Fridge 2: temperature, 09:00"]
    room = made["Room: temperature and humidity, 20:00"]
    assert morning.readings == [
        {
            "key": "t",
            "label": "Fridge 2 temperature",
            "unit": "°C",
            "min": "2.5",
            "max": "7.5",
            "critical": True,
        }
    ]
    assert [spec["key"] for spec in room.readings] == ["t", "h"]
    assert room.readings[1]["max"] == "55.0" and room.readings[1]["min"] is None
    assert len([t for t in made if t.startswith("Fridge")]) == 4  # 2 fridges, at 09:00 and 20:00
    assert {"Wet cleaning", "Weekly disinfection"} <= set(made)
    assert "Dispensing camera: records and keeps 30 days" in made
    for template in result.created:
        assert template.shared and template.branch == shop.here
        assert list(template.positions.all()) == [pharmacist]
    assert made["Weekly disinfection"].weekdays == [0]
    assert AuditLog.objects.filter(action=TasksAction.STORAGE_PRESET).count() == 1


def test_the_preset_takes_the_dialogs_times_and_positions_once(shop):
    head = PositionFactory(company=shop.company, name="Mudir")

    first = presets.apply_storage_preset(
        shop.there, by=shop.owner, fridges=1, positions=[head], times=[time(8, 30)]
    )
    again = presets.apply_storage_preset(
        shop.there, by=shop.owner, fridges=1, positions=[head], times=[time(8, 30)]
    )

    titles = sorted(template.title for template in first.created)
    assert titles == [
        "Dispensing camera: records and keeps 30 days",
        "Fridge 1: temperature, 08:30",
        "Room: temperature and humidity, 08:30",
        "Weekly disinfection",
        "Wet cleaning",
    ]
    assert {template.due_time for template in first.created} == {time(8, 30)}
    assert all(list(t.positions.all()) == [head] for t in first.created)
    assert again.created == [] and sorted(again.existing) == titles


def test_the_preset_needs_routine_rights_in_the_branch(shop):
    with pytest.raises(PermissionDenied):
        presets.apply_storage_preset(shop.here, by=shop.worker)
    with pytest.raises(PermissionDenied):
        presets.apply_storage_preset(shop.there, by=shop.lead)  # the lead runs `here` only
    with pytest.raises(DomainError, match="Nobody works"):
        presets.apply_storage_preset(shop.there, by=shop.owner)  # no positions held there


# The journal ------------------------------------------------------------------------------


def _readings_month(shop, clock, at):
    """Two routines of one fridge (morning and evening) over three days, with an excursion
    and its note, and a recheck."""
    morning = fridge_routine(shop, specs=[{**FRIDGE, "critical": True}], shared=True)
    evening = fridge_routine(
        shop, specs=[{**FRIDGE, "critical": True}], shared=True, due_time=time(20, 0)
    )
    for offset in (2, 1, 0):
        day = WED - timedelta(days=offset)
        for template, hour in ((morning, 9), (evening, 20)):
            if day == WED and hour == 20:
                continue
            task = run_of(template, shop.worker, day)
            clock(at(day, hour, 5))
            value, note = ("9.1", "Door was left open") if (offset, hour) == (1, 20) else ("5", "")
            services.complete_task(task, by=shop.worker, readings={"t": value}, reading_note=note)
            if note:
                clock(at(day, hour, 40))
                services.recheck(task, by=shop.worker, readings={"t": "6"})
    clock(at(WED, 12))
    return morning, evening


def test_the_journal_lists_every_reading_in_scope(shop, clock, at):
    _morning, evening = _readings_month(shop, clock, at)

    rows = journal.journal_rows(shop.company, WED - timedelta(days=2), WED, branch_ids=None)
    theirs = journal.journal_rows(
        shop.company, WED - timedelta(days=2), WED, branch_ids=[shop.there.pk]
    )

    assert len(rows) == 6 and theirs == []
    excursion = next(row for row in rows if not row["in_range"])
    assert (excursion["value"], excursion["note"], excursion["time"]) == (
        "9.1",
        "Door was left open",
        "20:05",
    )
    assert [row["is_recheck"] for row in rows].count(True) == 1
    data = journal.routine_journal(evening, WED - timedelta(days=2), WED, at(WED, 12))
    assert data["totals"] == {"taken": 2, "excursions": 1, "rechecks": 1, "missed": 0}
    assert [entry["t"] for entry in data["series"]] == ["5.0", "9.1", None]


def test_the_month_log_is_a_pdf_with_both_times_and_the_excursion(shop, clock, at):
    _readings_month(shop, clock, at)

    from django.utils import translation

    with translation.override("en"):
        context = journal.pdf_context(shop.here, WED.replace(day=1))
    data = journal.render(shop.here, WED.replace(day=1), language="en")

    assert data.startswith(b"%PDF")
    [section] = context["sections"]  # morning and evening share the fridge's page
    assert section["label"] == "Fridge 1 (vaccines)" and section["excursions"] == 1
    tuesday = next(day for day in section["days"] if day["date"] == "22.10.2030")
    assert [entry["time"] for entry in tuesday["entries"]] == ["09:05", "20:05", "20:40"]
    excursion = tuesday["entries"][1]
    assert excursion["note"] == "Door was left open" and not excursion["in_range"]
    assert tuesday["entries"][2]["recheck"]
    first = next(day for day in section["days"] if day["date"] == "01.10.2030")
    assert first["entries"] == []  # no reading that day: the log says so
    assert len(section["days"]) == 23  # the month so far


def test_today_lists_excursions_and_missed_readings(shop, clock, at):
    template = fridge_routine(shop)
    task = run_of(template, shop.worker)
    late = run_of(fridge_routine(shop, due_time=time(10)), shop.worker)
    services.complete_task(task, by=shop.worker, readings={"t": "9"}, reading_note="Moved")

    data = journal.today(shop.company, at(WED, 12), branch_ids=None)

    assert data["set_up"] and data["taken"] == 1
    assert [item["value"] for item in data["excursions"]] == ["9.0"]
    assert [item["task_id"] for item in data["missed"]] == [late.pk]
    assert journal.open_excursions(shop.company, at(WED, 12), branch_ids=None) == 1
    assert journal.open_excursions(shop.company, at(WED, 12), branch_ids=[shop.there.pk]) == 0


def test_the_setup_step_is_done_once_a_readings_routine_runs(shop):
    from apps.tasks import feeds

    assert not feeds.storage_set_up(shop.company)
    fridge_routine(shop)
    assert feeds.storage_set_up(shop.company)


# Parsing ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "typed, value",
    [
        ("5,2", "5.2"),
        ("5.2", "5.2"),
        ("−3,5", "-3.5"),
        ("+4", "4"),
        ("58 %", "58"),
        ("5,2°C", "5.2"),
        (7, "7"),
        ("abc", None),
        ("5,2,1", None),
        ("", None),
    ],
)
def test_parse(typed, value):
    parsed = readings.parse(typed)
    assert (str(parsed.normalize()) if parsed is not None else None) == value


def test_numbers_read_in_the_reader_language():
    assert readings.number(Decimal("5.20"), "uz") == "5,2"
    assert readings.number(Decimal("8.00"), "en") == "8"
    assert readings.range_text(Decimal("2"), Decimal("8"), "°C", "ru") == "2–8 °C"
    assert readings.range_text(None, Decimal("60"), "%", "en") == "≤ 60 %"


def test_existing_routines_without_readings_behave_as_before(shop):
    template = TaskTemplateFactory(
        company=shop.company, branch=shop.here, assignees=[shop.worker], proof=Proof.TEXT
    )
    TaskTemplate.objects.filter(pk=template.pk).update(
        created_at=template.created_at - timedelta(days=3)
    )
    generation.generate_daily_tasks(shop.company, WED + timedelta(days=1))
    task = Task.objects.get(template=template)

    services.complete_task(task, by=shop.worker, proof_text="Done")

    task.refresh_from_db()
    assert task.readings == [] and not task.readings_taken.exists()
    assert task.status == Task.Status.DONE and not template.shared


def test_a_plain_task_never_reads_its_readings(shop, django_assert_num_queries):
    from apps.tasks.api import readings_taken

    task = TaskFactory(assignee=shop.worker)
    with django_assert_num_queries(0):
        assert readings_taken(task) == []
