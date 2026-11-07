"""The pharmacist coverage rule (docs/PLAN-OWNER.md §14.9): who counts as qualified, the
planned gaps (§14.9's golden cases and acceptance list, exactly), live coverage and the
cashiers who aren't qualified.

Chilonzor is open 08:00 to 22:00 every day, Yunusobod around the clock; Ali and Vali work at
Chilonzor, Sara (days) and Zarina (nights) at Yunusobod. Every pharmacist has a verified
pharmacy diploma and specialist certificate unless a test says otherwise. Reference day:
Wednesday 21 October 2026, Asia/Tashkent.
"""

from datetime import date, time, timedelta

import pytest

from apps.attendance.models import AttendanceRecord, WorkShift
from apps.attendance.tests.factories import shift_at
from apps.hr import conf, coverage, queries, services
from apps.hr.models import DocumentKind, EmployeeDocument, RequiredDocument
from apps.hr.tests.conftest import DAY, local
from apps.hr.tests.factories import EmployeeDocumentFactory
from apps.members.models import Membership, Position
from apps.timeoff.models import Holiday

pytestmark = pytest.mark.django_db

YESTERDAY = DAY - timedelta(days=1)
TOMORROW = DAY + timedelta(days=1)


def credentials(member, *, certificate_until=DAY + timedelta(days=365), verified=True, **extra):
    """A verified pharmacy diploma, and a specialist certificate until `certificate_until`."""
    stamp = {"verified_at": local(DAY - timedelta(days=60))} if verified else {}
    diploma = EmployeeDocumentFactory(
        membership=member,
        kind=DocumentKind.PHARMACY_DIPLOMA,
        level=extra.get("level", "higher"),
        issued_on=date(2018, 7, 1),
        verified_at=local(DAY - timedelta(days=60)),
    )
    certificate = EmployeeDocumentFactory(
        membership=member,
        kind=DocumentKind.PHARMACIST_CERTIFICATE,
        issued_on=date(2024, 3, 1),
        expires_on=certificate_until,
        **stamp,
    )
    return diploma, certificate


@pytest.fixture
def rota(shop, staff, chilonzor, yunusobod, member):
    """The two pharmacies set up for the rule: the Pharmacist position counts, with the
    standard documents of a pharmacist."""
    chilonzor.opens_at, chilonzor.closes_at = time(8), time(22)
    chilonzor.open_weekdays = [0, 1, 2, 3, 4, 5, 6]
    chilonzor.save()
    yunusobod.open_24h = True
    yunusobod.save()
    staff.zarina = member.registered(
        shop,
        position=staff.pharmacist,
        home_branch=yunusobod,
        first_name="Zarina",
        last_name="Azimova",
    )
    staff.zarina.branches.add(yunusobod)
    services.set_pharmacists(shop, by=staff.owner, roles={staff.pharmacist: services.PHARMACIST})
    for person in (staff.ali, staff.vali, staff.sara, staff.zarina):
        credentials(person)
    return staff


def gaps(company, start=DAY, end=None, **kwargs):
    kwargs.setdefault("branch_ids", None)
    return [
        (gap.branch_id, gap.start, gap.end, gap.have, gap.need)
        for gap in coverage.planned_gaps(company, start, end or start, **kwargs)
    ]


def at(day, hour, minute=0):
    return local(day, hour, minute)


# The golden cases ---------------------------------------------------------------------------


def test_golden_chilonzor_two_shifts_cover_the_day_and_one_leaves_the_evening(
    shop, rota, chilonzor
):
    shift_at(rota.ali, DAY, time(8), time(17), branch=chilonzor)
    late = shift_at(rota.vali, DAY, time(14), time(22), branch=chilonzor)

    assert gaps(shop, branch_ids=[chilonzor.pk]) == []

    late.delete()
    assert gaps(shop, branch_ids=[chilonzor.pk]) == [(chilonzor.pk, at(DAY, 17), at(DAY, 22), 0, 1)]


@pytest.fixture
def nights(rota, yunusobod):
    """Yunusobod around the clock: Sara 08:00 to 20:00, Zarina 20:00 to 08:00, two days running,
    and Vali takes the second night."""
    shift_at(rota.zarina, YESTERDAY, time(20), time(8), branch=yunusobod)
    for day in (DAY, TOMORROW):
        shift_at(rota.sara, day, time(8), time(20), branch=yunusobod)
    shift_at(rota.zarina, DAY, time(20), time(8), branch=yunusobod)
    shift_at(rota.vali, TOMORROW, time(20), time(8), branch=yunusobod)
    return rota


def test_golden_yunusobod_day_and_night_leave_no_gap(shop, nights, yunusobod):
    assert gaps(shop, DAY, TOMORROW, branch_ids=[yunusobod.pk]) == []


def test_golden_a_certificate_expired_yesterday_opens_the_night(shop, nights, yunusobod):
    EmployeeDocument.objects.filter(
        membership=nights.zarina, kind=DocumentKind.PHARMACIST_CERTIFICATE
    ).update(expires_on=YESTERDAY)

    # Last night still counted (the certificate was in force on its date); tonight doesn't,
    # and the night runs on past midnight as one gap.
    assert gaps(shop, DAY, TOMORROW, branch_ids=[yunusobod.pk]) == [
        (yunusobod.pk, at(DAY, 20), at(TOMORROW, 8), 0, 1)
    ]


def test_golden_the_live_alert_comes_at_20_15_when_nobody_qualified_checked_in(
    shop, nights, yunusobod
):
    EmployeeDocument.objects.filter(
        membership=nights.zarina, kind=DocumentKind.PHARMACIST_CERTIFICATE
    ).update(expires_on=YESTERDAY)
    day_shift = WorkShift.objects.get(membership=nights.sara, date=DAY)
    night_shift = WorkShift.objects.get(membership=nights.zarina, date=DAY)
    AttendanceRecord.objects.create(
        company=shop,
        membership=nights.sara,
        shift=day_shift,
        date=DAY,
        status=AttendanceRecord.Status.CLOSED,
        check_in_at=at(DAY, 7, 55),
        check_out_at=at(DAY, 20),
        branch=yunusobod,
    )
    AttendanceRecord.objects.create(
        company=shop,
        membership=nights.zarina,
        shift=night_shift,
        date=DAY,
        status=AttendanceRecord.Status.OPEN,
        check_in_at=at(DAY, 19, 58),
        branch=yunusobod,
    )

    assert coverage.live(shop, at(DAY, 19, 59)) == []  # Sara is still there
    found = coverage.live(shop, at(DAY, 20, 15))
    assert [(gap.branch_id, gap.since, gap.have, gap.need) for gap in found] == [
        (yunusobod.pk, at(DAY, 20), 0, 1)
    ]


# What the rule reads ---------------------------------------------------------------------------


def test_an_unverified_certificate_removes_the_person(shop, rota, chilonzor):
    shift_at(rota.ali, DAY, time(8), time(17), branch=chilonzor)
    shift_at(rota.vali, DAY, time(14), time(22), branch=chilonzor)
    EmployeeDocument.objects.filter(
        membership=rota.vali, kind=DocumentKind.PHARMACIST_CERTIFICATE
    ).update(verified_at=None)

    assert gaps(shop, branch_ids=[chilonzor.pk]) == [(chilonzor.pk, at(DAY, 17), at(DAY, 22), 0, 1)]
    assert queries.qualified(shop, [rota.ali.pk, rota.vali.pk], DAY) == {rota.ali.pk}
    verdict = queries.Qualifier(shop, [rota.vali.pk]).verdict(rota.vali.pk, DAY)
    assert (verdict.counts, verdict.reason, verdict.kinds) == (
        False,
        "unverified",
        ("pharmacist_certificate",),
    )


def test_a_person_on_leave_and_an_open_shift_never_count(shop, rota, chilonzor):
    shift_at(rota.ali, DAY, time(8), time(17), branch=chilonzor)
    shift_at(rota.vali, DAY, time(14), time(22), branch=chilonzor, status=WorkShift.Status.LEAVE)
    shift_at(
        None, DAY, time(17), time(22), company=shop, branch=chilonzor, position=rota.pharmacist
    )

    assert gaps(shop, branch_ids=[chilonzor.pk]) == [(chilonzor.pk, at(DAY, 17), at(DAY, 22), 0, 1)]


def test_leaving_someone_out_shows_the_gap_their_leave_would_open(shop, rota, chilonzor):
    shift_at(rota.ali, DAY, time(8), time(17), branch=chilonzor)
    shift_at(rota.vali, DAY, time(14), time(22), branch=chilonzor)

    here = [chilonzor.pk]
    assert gaps(shop, branch_ids=here, exclude_member_ids={rota.ali.pk}) == [
        (chilonzor.pk, at(DAY, 8), at(DAY, 14), 0, 1)
    ]
    assert gaps(shop, branch_ids=here, exclude_member_ids={rota.ali.pk, rota.vali.pk}) == [
        (chilonzor.pk, at(DAY, 8), at(DAY, 22), 0, 1)
    ]


def test_a_warehouse_and_a_switched_off_rule_show_no_gap(shop, rota, chilonzor, yunusobod):
    # Nobody planned anywhere: both pharmacies are one long gap.
    assert {gap[0] for gap in gaps(shop)} == {chilonzor.pk, yunusobod.pk}

    chilonzor.kind = "warehouse"
    chilonzor.save()
    assert {gap[0] for gap in gaps(shop)} == {yunusobod.pk}

    settings = conf.get_settings(shop)
    settings.coverage_enabled = False
    settings.save()
    assert gaps(shop) == []
    assert coverage.state(shop) == coverage.OFF


def test_nothing_runs_until_the_pharmacists_are_chosen_or_while_hr_is_off(shop, staff, yunusobod):
    yunusobod.open_24h = True
    yunusobod.save()
    assert coverage.state(shop) == coverage.SETUP
    assert gaps(shop) == [] and coverage.live(shop, at(DAY, 12)) == []

    services.set_pharmacists(shop, by=staff.owner, roles={staff.pharmacist: services.PHARMACIST})
    assert coverage.state(shop) == coverage.OK and gaps(shop)

    shop.features = ["payroll", "attendance"]
    shop.save()
    assert coverage.state(shop) == coverage.OFF and gaps(shop) == []


def test_without_the_roster_nothing_is_planned(shop, rota):
    shop.features = ["hr", "payroll"]
    shop.save()

    assert coverage.state(shop) == coverage.NO_ROSTER
    assert gaps(shop) == []


def test_branch_scope(shop, rota, chilonzor, yunusobod):
    assert {gap[0] for gap in gaps(shop, branch_ids=[yunusobod.pk])} == {yunusobod.pk}
    assert gaps(shop, branch_ids=[]) == []


def test_drafts_count_only_for_the_roster(shop, rota, chilonzor):
    shift_at(rota.ali, DAY, time(8), time(22), branch=chilonzor, published=False)

    assert gaps(shop, branch_ids=[chilonzor.pk]) == [(chilonzor.pk, at(DAY, 8), at(DAY, 22), 0, 1)]
    assert gaps(shop, branch_ids=[chilonzor.pk], drafts=True) == []


def test_a_suspended_pharmacist_and_an_office_shift_never_count(shop, rota, chilonzor):
    shift_at(rota.ali, DAY, time(8), time(15), branch=chilonzor)
    shift_at(rota.lead, DAY, time(15), time(22), branch=chilonzor)  # Office
    Membership.objects.filter(pk=rota.ali.pk).update(status=Membership.Status.SUSPENDED)

    assert gaps(shop, branch_ids=[chilonzor.pk]) == [(chilonzor.pk, at(DAY, 8), at(DAY, 22), 0, 1)]
    verdict = queries.Qualifier(shop, [rota.lead.pk]).verdict(rota.lead.pk, DAY)
    assert verdict.reason == "not_pharmacist"


def test_two_needed_shows_where_only_one_is_there(shop, rota, chilonzor):
    shift_at(rota.ali, DAY, time(8), time(17), branch=chilonzor)
    shift_at(rota.vali, DAY, time(14), time(22), branch=chilonzor)
    settings = conf.get_settings(shop)
    settings.coverage_min = 2
    settings.save()

    assert gaps(shop, branch_ids=[chilonzor.pk]) == [
        (chilonzor.pk, at(DAY, 8), at(DAY, 14), 1, 2),
        (chilonzor.pk, at(DAY, 17), at(DAY, 22), 1, 2),
    ]


def test_without_documents_asked_the_position_is_enough(shop, rota, chilonzor):
    EmployeeDocument.objects.filter(membership=rota.ali).delete()
    shift_at(rota.ali, DAY, time(8), time(22), branch=chilonzor)
    assert gaps(shop, branch_ids=[chilonzor.pk]) != []

    settings = conf.get_settings(shop)
    settings.coverage_needs_documents = False
    settings.save()
    assert gaps(shop, branch_ids=[chilonzor.pk]) == []


def test_holidays_close_a_pharmacy_but_never_a_24_hour_one(shop, rota, chilonzor, yunusobod):
    Holiday.objects.create(company=shop, date=DAY, name="Bayram")

    assert {gap[0] for gap in gaps(shop)} == {yunusobod.pk}
    plan = coverage.plan(shop, DAY, DAY, branch_ids=[chilonzor.pk])
    assert plan.branches[0].days[0].closed == "holiday"


def test_an_evening_past_midnight_belongs_to_the_day_it_opened(shop, rota, chilonzor):
    chilonzor.opens_at, chilonzor.closes_at = time(18), time(2)
    chilonzor.save()
    shift_at(rota.ali, DAY, time(18), time(1), branch=chilonzor)

    assert gaps(shop, branch_ids=[chilonzor.pk]) == [
        (chilonzor.pk, at(TOMORROW, 1), at(TOMORROW, 2), 0, 1)
    ]


def test_a_branch_without_hours_or_closed_that_weekday_has_nothing_to_check(shop, rota, chilonzor):
    chilonzor.open_weekdays = [0, 1, 3, 4, 5, 6]  # not Wednesdays
    chilonzor.save()
    assert gaps(shop, branch_ids=[chilonzor.pk]) == []

    chilonzor.open_weekdays = [0, 1, 2, 3, 4, 5, 6]
    chilonzor.opens_at = None
    chilonzor.save()
    plan = coverage.plan(shop, DAY, DAY, branch_ids=[chilonzor.pk])
    assert plan.gaps == [] and plan.branches[0].days[0].closed == "no_hours"


def test_the_plan_lists_the_pharmacists_and_why_one_doesnt_count(shop, rota, chilonzor):
    shift_at(rota.ali, DAY, time(8), time(17), branch=chilonzor)
    shift_at(rota.vali, DAY, time(14), time(22), branch=chilonzor)
    shift_at(rota.lead, DAY, time(9), time(18), branch=chilonzor)  # not a pharmacist: not listed
    EmployeeDocument.objects.filter(
        membership=rota.vali, kind=DocumentKind.PHARMACIST_CERTIFICATE
    ).update(expires_on=YESTERDAY)

    day = coverage.plan(shop, DAY, DAY, branch_ids=[chilonzor.pk]).branches[0].days[0]
    assert (day.opens, day.closes, day.closed) == (at(DAY, 8), at(DAY, 22), None)
    assert [(c.member.pk, c.verdict.counts, c.verdict.reason) for c in day.covers] == [
        (rota.ali.pk, True, None),
        (rota.vali.pk, False, "expired"),
    ]


# Who counts as qualified ---------------------------------------------------------------------


def test_the_head_of_pharmacy_may_have_a_medical_diploma_instead(shop, staff, member, chilonzor):
    head = Position.objects.create(company=shop, name="Head of pharmacy", order=0)
    services.set_pharmacists(shop, by=staff.owner, roles={head: services.HEAD})
    boss = member.registered(shop, position=head, home_branch=chilonzor, first_name="Bobur")
    stamp = local(DAY - timedelta(days=30))
    EmployeeDocumentFactory(
        membership=boss,
        kind="medical_diploma",
        level="higher",
        issued_on=date(2010, 7, 1),
        verified_at=stamp,
    )
    EmployeeDocumentFactory(
        membership=boss,
        kind="pharmacist_certificate",
        issued_on=date(2025, 1, 1),
        verified_at=stamp,
    )
    assert queries.qualified(shop, [boss.pk], DAY) == {boss.pk}

    EmployeeDocument.objects.filter(membership=boss, kind="medical_diploma").update(level="college")
    verdict = queries.Qualifier(shop, [boss.pk]).verdict(boss.pk, DAY)
    assert (verdict.counts, verdict.reason, verdict.kinds) == (
        False,
        "missing",
        ("pharmacy_diploma",),
    )


def test_a_certificate_counts_from_its_issue_day_to_its_expiry(shop, rota):
    EmployeeDocument.objects.filter(
        membership=rota.ali, kind=DocumentKind.PHARMACIST_CERTIFICATE
    ).update(issued_on=TOMORROW, expires_on=DAY + timedelta(days=30))

    assert queries.qualified(shop, [rota.ali.pk], DAY) == set()
    assert queries.qualified(shop, [rota.ali.pk], TOMORROW) == {rota.ali.pk}
    assert queries.qualified(shop, [rota.ali.pk], DAY + timedelta(days=30)) == {rota.ali.pk}
    assert queries.qualified(shop, [rota.ali.pk], DAY + timedelta(days=31)) == set()


def test_the_qualified_staff_list(shop, rota):
    rows = queries.qualified_staff(shop, branch_ids=[rota.ali.home_branch_id], day=DAY)

    assert [row["member"].pk for row in rows] == [rota.ali.pk, rota.vali.pk]
    first = rows[0]
    assert first["qualified"] and first["position"] == "Pharmacist"
    assert [(d["kind"], d["status"], d["verified"]) for d in first["documents"]] == [
        ("pharmacist_certificate", "ok", True),
        ("pharmacy_diploma", "ok", True),
    ]
    assert first["documents"][0]["expires_on"] == DAY + timedelta(days=365)


# Setting the rule up -----------------------------------------------------------------------------


def test_choosing_the_pharmacists_asks_for_their_documents_once(shop, staff):
    senior = Position.objects.create(company=shop, name="Senior pharmacist", order=0)
    services.set_pharmacists(
        shop, by=staff.owner, roles={staff.pharmacist: services.PHARMACIST, senior: services.SENIOR}
    )

    assert conf.pharmacist_position_ids(conf.get_settings(shop)) == {staff.pharmacist.pk, senior.pk}
    asked = {
        (row.position.name, row.kind, row.level, tuple(row.alternatives))
        for row in RequiredDocument.objects.filter(company=shop)
    }
    assert asked == {
        ("Pharmacist", "pharmacy_diploma", "", ()),
        ("Pharmacist", "pharmacist_certificate", "", ()),
        ("Senior pharmacist", "pharmacy_diploma", "higher", ()),
        ("Senior pharmacist", "pharmacist_certificate", "", ()),
    }

    # A standard set follows a new role; one changed by hand is kept; dropping keeps them.
    RequiredDocument.objects.filter(position=senior, kind="pharmacy_diploma").update(level="")
    services.set_pharmacists(
        shop, by=staff.owner, roles={staff.pharmacist: services.HEAD, senior: services.PHARMACIST}
    )
    assert RequiredDocument.objects.get(
        position=staff.pharmacist, kind="pharmacy_diploma"
    ).alternatives == ["medical_diploma"]
    assert RequiredDocument.objects.get(position=senior, kind="pharmacy_diploma").level == ""
    services.set_pharmacists(shop, by=staff.owner, roles={senior: None})
    assert conf.pharmacist_position_ids(conf.get_settings(shop)) == {staff.pharmacist.pk}
    assert RequiredDocument.objects.filter(position=senior).count() == 2


def test_only_hr_managers_choose_the_pharmacists(shop, staff, other_company):
    from django.core.exceptions import PermissionDenied

    from apps.core.exceptions import DomainError

    with pytest.raises(PermissionDenied):
        services.set_pharmacists(shop, by=staff.manager, roles={staff.pharmacist: "pharmacist"})
    foreign = Position.objects.create(company=other_company, name="Pharmacist")
    with pytest.raises(DomainError):
        services.set_pharmacists(shop, by=staff.owner, roles={foreign: "pharmacist"})
    with pytest.raises(DomainError):
        services.set_pharmacists(shop, by=staff.owner, roles={staff.pharmacist: "doctor"})
