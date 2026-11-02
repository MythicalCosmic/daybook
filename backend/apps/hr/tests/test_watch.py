"""The watch job (documents, contracts and probation reaching a warning step: HR hears once
per item and step), the probation buttons, the celebrations job, the brief section, the
company calendar, the badge and the celebrations endpoints."""

from datetime import date, time, timedelta

import pytest

from apps.hr import providers, queries, services, watch
from apps.hr.models import Celebration, Contract, EmployeeProfile
from apps.hr.tests.conftest import DAY, local
from apps.hr.tests.factories import EmployeeDocumentFactory
from apps.inbox import services as inbox
from apps.inbox.models import Notification
from apps.members import services as members

pytestmark = pytest.mark.django_db

MORNING = local(DAY, 9, 30)


def notices(kind: str):
    return Notification.objects.filter(kind=kind).order_by("pk")


def readers(kind: str) -> set[str]:
    return {str(row.recipient) for row in notices(kind)}


@pytest.fixture
def go(shop, freeze):
    """`go(day, hour)`: the watch job at that moment."""

    def run(day=DAY, hour=9, minute=30):
        return watch.watch_company(shop, freeze(local(day, hour, minute)))

    return run


# The warning steps -------------------------------------------------------------------------


def test_the_steps_are_the_warning_days_a_week_and_the_day():
    assert watch.steps(30) == [30, 7, 0]
    assert watch.steps(7) == [7, 0]
    assert watch.steps(3) == [3, 0]
    assert watch.due(25, 30, []) == (30, [30])
    assert watch.due(5, 30, []) == (7, [30, 7])  # first seen at 5 days: one notice
    assert watch.due(5, 30, [30, 7]) == (None, [30, 7])
    assert watch.due(0, 30, [30, 7]) == (0, [30, 7, 0])
    assert watch.due(-3, 30, [30, 7]) == (0, [30, 7, 0])
    assert watch.due(-40, 30, []) == (None, [30, 7, 0])  # long expired when first seen
    assert watch.due(45, 30, []) == (None, [])


# Documents -------------------------------------------------------------------------------------


def test_a_document_warns_hr_and_the_person_once_per_step(shop, staff, go):
    document = EmployeeDocumentFactory(
        membership=staff.ali, kind="medical_book", expires_on=DAY + timedelta(days=20)
    )

    assert go() == 4  # owner, accountant, lead (Chilonzor), and Ali himself
    assert readers("hr.document_expiring") == {
        "Dilnoza Karimova",
        "Aziza Rasulova",
        "Lola Qodirova",
    }
    first = notices("hr.document_expiring").first()
    assert first.title == "Document expires on 10.11.2026"
    assert first.body == "Ali Valiyev · Medical book"
    assert first.url == f"/c/{shop.pk}/hr/documents?document={document.pk}"
    mine = notices("hr.my_document").get()
    assert mine.recipient == staff.ali and mine.app_screen == "hr.documents"
    assert go(hour=15) == 0  # later the same day
    assert go(day=DAY + timedelta(days=1)) == 0  # nothing new until the next step

    assert go(day=DAY + timedelta(days=13)) == 4  # 7 days left
    assert go(day=DAY + timedelta(days=20)) == 4  # the day itself
    last = notices("hr.document_expiring").last()
    assert last.severity == "warning" and last.title == "Document expires today"
    document.refresh_from_db()
    assert document.expiry_notified == [30, 7, 0]
    assert go(day=DAY + timedelta(days=25)) == 0


def test_nothing_goes_out_before_the_morning_report(shop, staff, go):
    EmployeeDocumentFactory(membership=staff.ali, expires_on=DAY + timedelta(days=3))

    assert go(hour=6) == 0
    assert not Notification.objects.exists()
    assert go(hour=9, minute=5) == 4


def test_a_long_expired_document_is_marked_quietly(shop, staff, go):
    document = EmployeeDocumentFactory(membership=staff.ali, expires_on=DAY - timedelta(days=60))

    assert go() == 0
    document.refresh_from_db()
    assert document.expiry_notified == [30, 7, 0]


def test_a_hidden_document_warns_hr_only_and_a_renewed_one_nobody(shop, staff, go):
    EmployeeDocumentFactory(
        membership=staff.vali, expires_on=DAY + timedelta(days=2), visible_to_employee=False
    )
    EmployeeDocumentFactory(membership=staff.ali, expires_on=DAY + timedelta(days=2))
    EmployeeDocumentFactory(membership=staff.ali, expires_on=DAY + timedelta(days=700))

    assert go() == 3
    assert not notices("hr.my_document").exists()
    assert {row.body for row in notices("hr.document_expiring")} == {"Vali Aliyev · Medical book"}


def test_people_who_left_raise_nothing(shop, staff, go):
    EmployeeDocumentFactory(membership=staff.ali, expires_on=DAY + timedelta(days=2))
    members.offboard(staff.ali, by=staff.owner.user)

    assert go() == 0


# Contracts and probation -----------------------------------------------------------------------


def test_a_contract_ending_warns_hr_once_per_step(shop, staff, go):
    contract = services.activate_contract(
        services.create_contract(
            staff.sara,
            by=staff.owner,
            kind="fixed_term",
            starts_on=DAY - timedelta(days=300),
            ends_on=DAY + timedelta(days=21),
        ),
        by=staff.owner,
    )

    assert go() == 2  # owner and accountant: the Chilonzor lead doesn't see Yunusobod
    notice = notices("hr.contract_ending").get(recipient=staff.owner)
    assert notice.title == "Contract ends on 11.11.2026"
    assert notice.body == f"Sara Tosheva · {contract.number}\nRenew it or end it."
    assert go(day=DAY + timedelta(days=2)) == 0
    assert go(day=DAY + timedelta(days=14)) == 2
    contract.refresh_from_db()
    assert contract.end_notified == [30, 7]


def test_probation_ending_offers_keep_and_extend(shop, staff, go):
    contract = services.activate_contract(
        services.create_contract(
            staff.ali,
            by=staff.owner,
            starts_on=DAY - timedelta(days=85),
            probation_until=DAY + timedelta(days=5),
        ),
        by=staff.owner,
    )

    assert go() == 3
    notice = notices("hr.probation_ending").get(recipient=staff.owner)
    assert notice.title == "Probation ends on 26.10.2026"
    assert [action["key"] for action in notice.actions] == ["keep", "extend"]

    message = inbox.run_action(notice.pk, "extend", by=staff.owner)

    contract.refresh_from_db()
    assert contract.probation_until == date(2026, 11, 26)
    assert message == "Probation extended: until 26.11.2026"
    assert contract.probation_notified == []  # the new end gets its own warnings
    assert go(day=DAY + timedelta(days=29)) == 3  # 7 days before the new end
    again = notices("hr.probation_ending").filter(recipient=staff.accountant).last()
    assert inbox.run_action(again.pk, "keep", by=staff.accountant) == "Probation passed"
    contract.refresh_from_db()
    assert contract.probation_passed_at is not None
    assert go(day=DAY + timedelta(days=36)) == 0


def test_extending_by_a_month_stops_at_the_contracts_end(shop, staff, go):
    services.activate_contract(
        services.create_contract(
            staff.ali,
            by=staff.owner,
            kind="fixed_term",
            starts_on=DAY - timedelta(days=60),
            ends_on=DAY + timedelta(days=10),
            probation_until=DAY + timedelta(days=3),
        ),
        by=staff.owner,
    )
    go()
    notice = notices("hr.probation_ending").get(recipient=staff.owner)

    inbox.run_action(notice.pk, "extend", by=staff.owner)

    assert Contract.objects.get().probation_until == DAY + timedelta(days=10)


# Celebrations ---------------------------------------------------------------------------------


@pytest.fixture
def posts(monkeypatch):
    sent = []

    def record(company_id, event, text, *, position_ids=(), branch_id=None, **kwargs):
        sent.append({"event": str(event), "text": text, "branch_id": branch_id})
        return 1

    monkeypatch.setattr("apps.hr.watch.broadcast", record)
    return sent


def born(member, birth_date=None, hired=None, **fields) -> EmployeeProfile:
    profile = services.ensure_profile(member)
    profile.birth_date = birth_date
    if hired:
        profile.hire_date = hired
    for name, value in fields.items():
        setattr(profile, name, value)
    profile.save()
    return profile


def test_birthdays_and_anniversaries_are_posted_once_in_the_morning(shop, staff, freeze, posts):
    born(staff.ali, date(1998, 10, 21), hired=date(2024, 3, 1))
    born(staff.vali, date(1995, 10, 21), show_birthday=False, hired=date(2023, 10, 21))
    born(staff.sara, date(1990, 5, 5), hired=date(2025, 1, 1))
    shop.morning_report_at = time(9, 0)
    shop.save()

    assert watch.celebrate_company(shop, freeze(local(DAY, 8, 50))) == 0
    assert watch.celebrate_company(shop, freeze(local(DAY, 9, 0))) == 2
    assert watch.celebrate_company(shop, freeze(local(DAY, 9, 15))) == 0

    assert [post["text"] for post in posts] == [
        "Birthday today: <b>Ali Valiyev</b>. Happy birthday!",
        "Work anniversary: <b>Vali Aliyev</b>, 3 years with the team. Thank you!",
    ]
    assert {post["event"] for post in posts} == {"celebrations"}
    rows = Celebration.objects.order_by("kind")
    assert [(row.membership, row.kind, row.years) for row in rows] == [
        (staff.vali, "anniversary", 3),
        (staff.ali, "birthday", None),
    ]
    greetings = notices("hr.celebration")
    assert {row.recipient for row in greetings} == {staff.ali, staff.vali}
    assert greetings.get(recipient=staff.ali).title == "Happy birthday!"
    assert greetings.get(recipient=staff.vali).title == "3 years with the team"


def test_the_celebration_settings_are_respected(shop, staff, freeze, posts):
    born(staff.ali, date(1998, 10, 21), hired=date(2024, 10, 21))
    settings = services.conf.get_settings(shop)
    settings.celebrate_anniversaries = False
    settings.save()

    assert watch.celebrate_company(shop, freeze(local(DAY, 9, 30))) == 1
    assert [post["text"] for post in posts] == [
        "Birthday today: <b>Ali Valiyev</b>. Happy birthday!"
    ]
    settings.celebrations_enabled = False
    settings.save()
    Celebration.objects.all().delete()
    assert watch.celebrate_company(shop, freeze(local(DAY, 9, 30))) == 0


def test_the_jobs_skip_companies_without_hr(shop, staff, freeze, posts):
    born(staff.ali, date(1998, 10, 21))
    EmployeeDocumentFactory(membership=staff.ali, expires_on=DAY + timedelta(days=1))
    shop.features = ["payroll"]
    shop.save()
    freeze(MORNING)

    assert watch.watch_expiries() == 0
    assert watch.post_celebrations() == 0


# What the brief, the calendar and the badge say -------------------------------------------------


def test_the_brief_section_and_the_badge(shop, staff):
    born(staff.ali, date(1998, 10, 21))
    EmployeeDocumentFactory(membership=staff.ali, expires_on=DAY + timedelta(days=3))
    EmployeeDocumentFactory(membership=staff.sara, expires_on=DAY - timedelta(days=3))
    services.activate_contract(
        services.create_contract(
            staff.vali,
            by=staff.owner,
            kind="fixed_term",
            starts_on=DAY - timedelta(days=100),
            ends_on=DAY + timedelta(days=9),
            probation_until=DAY + timedelta(days=2),
        ),
        by=staff.owner,
    )

    section = providers.brief_section(shop, DAY, MORNING, None)

    assert section == {
        "title": "HR",
        "lines": [
            "Birthday: Ali Valiyev",
            "Documents to renew: 2",
            "Contracts ending: 1",
            "Probations ending: 1",
        ],
    }
    assert providers.brief_section(shop, DAY + timedelta(days=200), MORNING, [999]) is None
    assert queries.expiring_count(staff.owner) == 4
    assert queries.expiring_count(staff.lead) == 3  # Sara's document is Yunusobod's


def test_the_calendar_shows_celebrations_and_contract_dates(shop, staff):
    born(staff.ali, date(1998, 11, 2), hired=date(2024, 11, 5))
    services.activate_contract(
        services.create_contract(
            staff.vali,
            by=staff.owner,
            kind="fixed_term",
            starts_on=DAY - timedelta(days=100),
            ends_on=date(2026, 11, 20),
        ),
        by=staff.owner,
    )

    celebrations = providers.calendar_celebrations(
        shop, date(2026, 11, 1), date(2026, 11, 30), staff.owner
    )
    contracts = providers.calendar_contracts(
        shop, date(2026, 11, 1), date(2026, 11, 30), staff.owner
    )

    assert [(item.title, item.start) for item in celebrations] == [
        ("Birthday: Ali Valiyev", date(2026, 11, 2)),
        ("Work anniversary: Ali Valiyev, 2 years", date(2026, 11, 5)),
    ]
    assert [(item.title, item.start, item.color) for item in contracts] == [
        ("Contract ends: Vali Aliyev", date(2026, 11, 20), "warning")
    ]


def test_the_celebrations_endpoints(shop, staff, owner_api, api_as):
    born(staff.ali, date(1998, 10, 24))
    born(staff.vali, date(1995, 11, 15), show_birthday=False)
    born(staff.sara, date(1999, 10, 30))

    month = owner_api(staff.manager).get(f"/api/v1/owner/companies/{shop.pk}/hr/celebrations/")
    week = api_as(staff.vali).get(f"/api/v1/companies/{shop.pk}/hr/celebrations/")
    lead = owner_api(staff.lead).get(f"/api/v1/owner/companies/{shop.pk}/hr/celebrations/")

    assert [(row["member"]["name"], row["date"]) for row in month.json()] == [
        ("Ali Valiyev", "2026-10-24"),
        ("Sara Tosheva", "2026-10-30"),
    ]
    assert [row["member"]["name"] for row in week.json()] == ["Ali Valiyev"]
    assert [row["member"]["name"] for row in lead.json()] == ["Ali Valiyev"]
    too_long = owner_api(staff.manager).get(
        f"/api/v1/owner/companies/{shop.pk}/hr/celebrations/?from=2026-01-01&to=2027-06-01"
    )
    assert too_long.status_code == 400
