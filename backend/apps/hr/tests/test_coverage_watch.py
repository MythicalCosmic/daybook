"""The coverage alerts (docs/PLAN-OWNER.md §14.9): a live gap alerts once per gap after
`coverage_alert_minutes`, an unqualified cashier opening a till alerts once, planned gaps of the
published roster warn once per gap; the brief section and the setup step. Nothing is sent while
HR or the rule is off."""

from datetime import time, timedelta

import pytest

from apps.attendance.models import AttendanceRecord, WorkShift
from apps.attendance.tests.factories import shift_at
from apps.finance import defaults as finance_defaults
from apps.hr import conf, notify, providers, services, watch
from apps.hr.models import DocumentKind, EmployeeDocument
from apps.hr.tests.conftest import DAY, local
from apps.hr.tests.factories import EmployeeDocumentFactory
from apps.hr.tests.test_coverage import TOMORROW, YESTERDAY, credentials
from apps.inbox.models import Notification
from apps.sales import defaults as sales_defaults
from apps.sales import services as sales
from apps.sales.models import Register

pytestmark = pytest.mark.django_db


def notices(kind: str):
    return Notification.objects.filter(kind=kind).order_by("pk")


def readers(kind: str) -> set[str]:
    return {str(row.recipient) for row in notices(kind)}


@pytest.fixture
def rota(shop, staff, chilonzor, yunusobod, member):
    chilonzor.opens_at, chilonzor.closes_at = time(8), time(22)
    chilonzor.manager = staff.lead
    chilonzor.save()
    yunusobod.open_24h = True
    yunusobod.manager = staff.manager
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


@pytest.fixture
def evening(shop, rota, yunusobod):
    """Sara's day ended at 20:00; Zarina came for the night, but her certificate ended yesterday."""
    EmployeeDocument.objects.filter(
        membership=rota.zarina, kind=DocumentKind.PHARMACIST_CERTIFICATE
    ).update(expires_on=YESTERDAY)
    day = shift_at(rota.sara, DAY, time(8), time(20), branch=yunusobod)
    night = shift_at(rota.zarina, DAY, time(20), time(8), branch=yunusobod)
    for person, shift, status, came, went in (
        (rota.sara, day, "closed", local(DAY, 7, 55), local(DAY, 20)),
        (rota.zarina, night, "open", local(DAY, 19, 58), None),
    ):
        AttendanceRecord.objects.create(
            company=shop,
            membership=person,
            shift=shift,
            date=DAY,
            status=status,
            check_in_at=came,
            check_out_at=went,
            branch=yunusobod,
        )
    return rota


def run(company, freeze, hour, minute=0, day=DAY):
    return watch.coverage_company(company, freeze(local(day, hour, minute)))


# Live gaps ---------------------------------------------------------------------------------


def test_a_live_gap_alerts_the_manager_and_owners_once_after_15_minutes(shop, evening, freeze):
    assert run(shop, freeze, 20, 10) == 0
    assert run(shop, freeze, 20, 15) == 2
    assert readers(notify.COVERAGE_GAP_LIVE) == {"Dilnoza Karimova", "Bekzod Mirzayev"}
    first = notices(notify.COVERAGE_GAP_LIVE).first()
    assert first.severity == "critical"
    assert first.title == "No qualified pharmacist on duty: Yunusobod"
    assert first.body.splitlines()[:2] == [
        "Since 20:00 nobody qualified has checked in.",
        "Checked in: Zarina Azimova",
    ]
    assert first.url == f"/c/{shop.pk}/hr/coverage?branch={first.target_id}"
    assert run(shop, freeze, 20, 20) == 0
    assert run(shop, freeze, 21, 40) == 0


def test_the_wait_is_a_setting(shop, evening, freeze):
    settings = conf.get_settings(shop)
    settings.coverage_alert_minutes = 30
    settings.save()

    assert run(shop, freeze, 20, 25) == 0
    assert run(shop, freeze, 20, 30) == 2


def test_nothing_is_sent_while_hr_or_the_rule_is_off(shop, evening, freeze):
    settings = conf.get_settings(shop)
    settings.coverage_enabled = False
    settings.save()
    assert run(shop, freeze, 20, 30) == 0
    assert watch.planned_company(shop, freeze(local(DAY, 9))) == 0

    settings.coverage_enabled = True
    settings.save()
    shop.features = ["payroll", "attendance"]
    shop.save()
    assert watch.watch_coverage(freeze(local(DAY, 20, 30))) == 0
    assert not Notification.objects.filter(kind__startswith="hr.coverage").exists()


def test_a_branch_where_nobody_checks_in_is_left_alone(shop, rota, freeze):
    # Chilonzor is open, nobody has ever checked in there: its live coverage isn't known.
    assert run(shop, freeze, 12) == 0


# Tills opened by someone not qualified ----------------------------------------------------------


@pytest.fixture
def tills(shop):
    shop.features = [*shop.features, "finance", "sales"]
    shop.save()
    finance_defaults.ensure(shop)
    sales_defaults.ensure(shop)
    return shop


def open_till(person, branch):
    return sales.open_shift(
        by=person, register=Register.objects.get(branch=branch), opening_float="0"
    )


def test_an_unqualified_cashier_opening_a_till_alerts_once(shop, rota, tills, chilonzor, freeze):
    freeze(local(DAY, 8, 2))
    open_till(rota.lead, chilonzor)  # Office, not a pharmacist

    assert run(shop, freeze, 8, 5) == 2  # the owner and Chilonzor's manager
    row = notices(notify.UNQUALIFIED_SELLER).first()
    assert row.severity == "critical"
    assert row.title == "Till opened by someone not qualified: Chilonzor"
    assert row.body == "Opened at 08:02. Cashier: Lola Qodirova (not in a pharmacist position)."
    assert readers(notify.UNQUALIFIED_SELLER) == {"Dilnoza Karimova", "Lola Qodirova"}
    assert run(shop, freeze, 8, 10) == 0


def test_a_qualified_cashier_or_the_setting_off_sends_nothing(shop, rota, tills, chilonzor, freeze):
    freeze(local(DAY, 8, 2))
    open_till(rota.ali, chilonzor)
    assert run(shop, freeze, 8, 5) == 0

    EmployeeDocument.objects.filter(
        membership=rota.ali, kind=DocumentKind.PHARMACIST_CERTIFICATE
    ).update(verified_at=None)
    settings = conf.get_settings(shop)
    settings.unqualified_seller_alert = False
    settings.save()
    assert run(shop, freeze, 8, 10) == 0


def test_a_till_at_a_warehouse_is_no_ones_business(shop, rota, tills, chilonzor, freeze):
    chilonzor.kind = "warehouse"
    chilonzor.save()
    freeze(local(DAY, 8, 2))
    open_till(rota.lead, chilonzor)

    assert run(shop, freeze, 8, 5) == 0


# Planned gaps -------------------------------------------------------------------------------------


def plan_week(rota, chilonzor, *, last_evening=True):
    """Chilonzor tomorrow and the day after: Ali opens, Vali closes; on the second day Vali's
    shift is missing unless `last_evening`."""
    for day in (TOMORROW, TOMORROW + timedelta(days=1)):
        shift_at(rota.ali, day, time(8), time(17), branch=chilonzor)
    shift_at(rota.vali, TOMORROW, time(14), time(22), branch=chilonzor)
    if last_evening:
        shift_at(rota.vali, TOMORROW + timedelta(days=1), time(14), time(22), branch=chilonzor)


def planned(company, freeze, hour=9, day=DAY):
    return watch.planned_company(company, freeze(local(day, hour)))


def test_a_gap_in_the_published_roster_warns_whoever_runs_it_once(shop, rota, chilonzor, freeze):
    plan_week(rota, chilonzor, last_evening=False)
    settings = conf.get_settings(shop)
    settings.coverage_days = 3
    settings.save()

    sent = planned(shop, freeze)
    rows = list(notices(notify.COVERAGE_GAP_PLANNED))
    assert sent == len(rows) and rows
    assert {row.title for row in rows} == {"No qualified pharmacist in the roster: Chilonzor"}
    assert {row.body.splitlines()[0] for row in rows} == {"23.10.2026, 17:00 to 22:00"}
    assert rows[0].severity == "warning"
    assert rows[0].url == f"/c/{shop.pk}/attendance/roster?branch={chilonzor.pk}&week=2026-10-19"
    # attendance.manage holders who see Chilonzor (the owner and the manager); not HR's lead.
    assert readers(notify.COVERAGE_GAP_PLANNED) == {"Dilnoza Karimova", "Bekzod Mirzayev"}
    assert planned(shop, freeze, hour=10) == 0


def test_a_runs_new_gaps_come_in_one_message_and_each_gap_once(shop, rota, chilonzor, freeze):
    for day in (TOMORROW, TOMORROW + timedelta(days=1)):
        shift_at(rota.ali, day, time(8), time(17), branch=chilonzor)  # nobody for the evenings

    assert planned(shop, freeze) == 2  # one message each for the owner and the manager
    first = notices(notify.COVERAGE_GAP_PLANNED).first()
    assert first.body.splitlines() == [
        "22.10.2026, 17:00 to 22:00",
        "23.10.2026, 17:00 to 22:00",
        "Add a qualified pharmacist to the roster.",
    ]
    shift_at(rota.vali, TOMORROW + timedelta(days=2), time(14), time(17), branch=chilonzor)
    assert planned(shop, freeze, hour=10) == 2  # only the new day's gaps
    newest = notices(notify.COVERAGE_GAP_PLANNED).last()
    assert newest.body.splitlines()[:-1] == [
        "24.10.2026, 08:00 to 14:00",
        "24.10.2026, 17:00 to 22:00",
    ]
    assert planned(shop, freeze, hour=11) == 0


def test_drafts_days_past_the_roster_and_gaps_under_way_stay_quiet(shop, rota, chilonzor, freeze):
    plan_week(rota, chilonzor)
    shift_at(
        rota.ali, TOMORROW + timedelta(days=2), time(8), time(12), branch=chilonzor, published=False
    )

    # Today nobody is planned (the gap is under way at 09:00); the two planned days are covered;
    # the draft isn't published, and the days after aren't planned yet.
    assert planned(shop, freeze) == 0
    assert not notices(notify.COVERAGE_GAP_PLANNED).exists()


# Documents, the brief, the setup step -----------------------------------------------------------


def test_a_pharmacist_certificate_reaches_hr_30_7_and_0_days_ahead(shop, rota, freeze):
    EmployeeDocument.objects.filter(
        membership=rota.ali, kind=DocumentKind.PHARMACIST_CERTIFICATE
    ).update(expires_on=DAY + timedelta(days=20))

    assert watch.watch_company(shop, freeze(local(DAY, 9, 30))) >= 1
    assert (
        notices("hr.document_expiring").filter(body="Ali Valiyev · Specialist certificate").exists()
    )


def test_the_brief_tells_the_gaps_the_live_gap_and_the_certificates(
    shop, evening, chilonzor, freeze
):
    EmployeeDocument.objects.filter(
        membership=evening.ali, kind=DocumentKind.PHARMACIST_CERTIFICATE
    ).update(expires_on=DAY + timedelta(days=20))
    shift_at(evening.ali, TOMORROW, time(8), time(17), branch=chilonzor)
    now = freeze(local(DAY, 20, 30))

    section = providers.coverage_brief(shop, DAY, now, None)

    assert section["title"] == "Pharmacist coverage"
    assert section["lines"][0] == "No qualified pharmacist now: Yunusobod, since 20:00"
    assert "Roster gaps without a qualified pharmacist, next 7 days: 3" in section["lines"]
    assert "Chilonzor: 22.10.2026, 17:00 to 22:00" in section["lines"]
    assert section["lines"][-1] == "Pharmacist certificates to renew within 30 days: 2"
    assert providers.coverage_brief(shop, DAY, now, []) is None


def test_the_setup_step_is_done_once_a_pharmacist_is_qualified(shop, staff, member, yunusobod):
    assert providers.pharmacists_done(shop) is False
    services.set_pharmacists(shop, by=staff.owner, roles={staff.pharmacist: services.PHARMACIST})
    assert providers.pharmacists_done(shop) is False  # nobody's documents are in yet
    credentials(staff.ali)
    assert providers.pharmacists_done(shop) is True

    settings = conf.get_settings(shop)
    settings.coverage_enabled = False
    settings.save()
    services.set_pharmacists(shop, by=staff.owner, roles={staff.pharmacist: None})
    assert providers.pharmacists_done(shop) is True  # the company doesn't use the rule


def test_a_company_with_only_warehouses_has_nothing_to_set_up(shop, staff):
    shop.branches.update(kind="warehouse")
    assert providers.pharmacists_done(shop) is True


def test_an_unrelated_document_never_counts(shop, rota, chilonzor):
    EmployeeDocument.objects.filter(
        membership=rota.ali, kind=DocumentKind.PHARMACY_DIPLOMA
    ).delete()
    EmployeeDocumentFactory(membership=rota.ali, kind=DocumentKind.DIPLOMA, level="higher")
    from apps.hr import queries

    assert queries.qualified(shop, [rota.ali.pk], DAY) == set()
    assert WorkShift.objects.count() == 0
