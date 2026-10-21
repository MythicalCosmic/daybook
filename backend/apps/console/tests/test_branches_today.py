"""`branches/today/`: branch cards with status and the fixed facts of each module."""

import zoneinfo
from datetime import date, datetime, time

import pytest

from apps.companies.tests.factories import BranchFactory
from apps.console import queries, registry
from apps.members.permissions import Perm
from apps.timeoff.models import Holiday

# Every registry starts empty: a card carries exactly the facts registered here.
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("empty_registries")]

TASHKENT = zoneinfo.ZoneInfo("Asia/Tashkent")
TUESDAY = date(2026, 10, 20)


def local(hour: int, minute: int = 0, day: date = TUESDAY) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TASHKENT)


def add_facts(key: str, perm, facts, feature=None) -> None:
    """Register a provider as its own app would (fixed keys belong to their apps)."""
    registry.BRANCH_FACTS.add(registry.BranchFactsProvider(key, key, perm, feature, facts))


def sales_facts(opened_at=None):
    return {
        "opened_at": opened_at,
        "opened_by": {"id": 1, "name": "Madina"} if opened_at else None,
        "open_tills": 1 if opened_at else 0,
        "net": "1250000.00",
        "cash_in_branch": "300000.00",
    }


@pytest.fixture
def branch(company):
    return BranchFactory(
        company=company,
        name="Chilonzor",
        code="CHL",
        opens_at=time(9, 0),
        closes_at=time(21, 0),
        open_weekdays=[0, 1, 2, 3, 4, 5],
    )


def status(branch, at, *, holiday=False, card=None, records_openings=True):
    return queries.branch_status(
        branch, at, holiday=holiday, card=card or {}, records_openings=records_openings
    )


def test_open_once_a_till_or_the_first_check_in_opened_it(branch):
    assert (
        status(branch, local(9, 30), card={"sales": sales_facts("2026-10-20T08:55:00+05:00")})
        == "open"
    )
    assert (
        status(
            branch,
            local(9, 30),
            card={"attendance": {"rostered": 3, "checked_in": 1, "first_check_in": "08:50"}},
        )
        == "open"
    )


def test_not_opened_ten_minutes_after_opening_time(branch):
    assert status(branch, local(9, 5)) == "closed"  # still within the grace
    assert status(branch, local(9, 10)) == "not_opened"


def test_closed_after_closing_time_even_if_opened(branch):
    assert (
        status(branch, local(21, 0), card={"sales": sales_facts("2026-10-20T09:00:00+05:00")})
        == "closed"
    )


def test_closed_before_opening(branch):
    assert status(branch, local(7, 0)) == "closed"


def test_day_off_on_a_closed_weekday_or_a_holiday(branch):
    sunday = date(2026, 10, 25)
    assert status(branch, local(12, 0, sunday)) == "day_off"
    assert status(branch, local(12, 0), holiday=True) == "day_off"


def test_opening_on_a_day_off_still_shows_open(branch):
    sunday = date(2026, 10, 25)
    card = {"sales": sales_facts("2026-10-25T10:00:00+05:00")}

    assert status(branch, local(12, 0, sunday), card=card) == "open"


def test_a_branch_open_past_midnight(company):
    bar = BranchFactory(company=company, opens_at=time(18, 0), closes_at=time(2, 0))

    assert status(bar, local(3, 0)) == "closed"  # between closing and opening
    assert status(bar, local(18, 30)) == "not_opened"
    opened = {"sales": sales_facts("2026-10-20T18:01:00+05:00")}
    assert status(bar, local(23, 30), card=opened) == "open"
    # Facts are per company day, so at 01:00 nothing has opened "today" yet.
    assert status(bar, local(1, 0)) == "closed"


def test_a_branch_without_hours_is_never_not_opened(company):
    shop = BranchFactory(company=company)

    assert status(shop, local(15, 0)) == "closed"


def test_cards_carry_the_facts_the_member_may_see(company, member, branch, owner_api):
    company.features = ["sales"]
    company.save()
    add_facts(
        "sales", Perm.SALES_VIEW, lambda c, d, n, ids: {i: sales_facts() for i in ids}, "sales"
    )
    add_facts(
        "finance",
        Perm.FINANCE_VIEW,
        lambda c, d, n, ids: {i: {"cash": "5000000.00"} for i in ids},
        "finance",  # switched off for this company
    )
    add_facts(
        "tasks",
        Perm.TASKS_VIEW_ALL,
        lambda c, d, n, ids: {i: {"done": 4, "total": 6, "late": 1} for i in ids},
    )
    manager = member(company, "Manager")

    response = owner_api(manager).get(f"/api/v1/owner/companies/{company.pk}/branches/today/")

    assert response.status_code == 200
    card = next(card for card in response.data if card["id"] == branch.pk)
    assert card["name"] == "Chilonzor" and card["code"] == "CHL"
    assert (card["opens_at"], card["closes_at"]) == ("09:00", "21:00")
    assert card["sales"] == sales_facts()
    assert card["tasks"] == {"done": 4, "total": 6, "late": 1}
    assert "finance" not in card
    assert card["status"] in ("open", "not_opened", "closed", "day_off")


def test_cards_follow_the_branch_scope(company, member, branch, owner_api):
    other = BranchFactory(company=company, name="Yunusobod")
    BranchFactory(company=company, name="Old shop", is_active=False)
    accountant = member(company, "Accountant")
    accountant.role.permissions.remove(Perm.BRANCHES_ALL)
    accountant.role.save()
    accountant.branches.add(branch)
    seen = []
    add_facts("tasks", None, lambda c, d, n, ids: seen.extend(ids) or {})

    response = owner_api(accountant).get(f"/api/v1/owner/companies/{company.pk}/branches/today/")

    assert [card["id"] for card in response.data] == [branch.pk]
    assert seen == [branch.pk]
    assert other.pk not in seen


def test_providers_get_the_company_day(company, member, branch):
    days = []
    add_facts("tasks", None, lambda c, d, n, ids: days.append(d) or {})
    owner = member(company, "Owner")

    # 20:30 UTC is already the 21st in Tashkent.
    queries.branches_today(owner, datetime(2026, 10, 20, 20, 30, tzinfo=zoneinfo.ZoneInfo("UTC")))

    assert days == [date(2026, 10, 21)]


def test_a_holiday_makes_every_branch_a_day_off(company, member, branch):
    Holiday.objects.create(company=company, date=TUESDAY, name="Teachers' Day")
    owner = member(company, "Owner")

    cards = queries.branches_today(owner, local(12, 0))

    assert next(c for c in cards if c["id"] == branch.pk)["status"] == "day_off"


def test_without_sales_or_attendance_a_branch_goes_by_its_hours(branch, company):
    """Nothing but a till or a check-in records an opening: a company with neither (a
    distributor's warehouse) sees its branch open in its hours, never "not opened"."""
    untracked = {"records_openings": False}

    assert status(branch, local(12, 0), **untracked) == "open"
    assert status(branch, local(8, 0), **untracked) == "closed"
    assert status(branch, local(21, 30), **untracked) == "closed"
    assert status(branch, local(12, 0, date(2026, 10, 25)), **untracked) == "day_off"
    bar = BranchFactory(company=company, opens_at=time(18, 0), closes_at=time(2, 0))
    assert status(bar, local(1, 0), **untracked) == "open"
    assert status(bar, local(3, 0), **untracked) == "closed"
    assert status(BranchFactory(company=company), local(12, 0), **untracked) == "closed"


def test_cards_follow_the_hours_only_when_no_module_records_openings(company, member, branch):
    owner = member(company, "Owner")

    company.features = ["finance", "hr"]
    company.save(update_fields=["features"])
    [card] = [c for c in queries.branches_today(owner, local(12, 0)) if c["id"] == branch.pk]
    assert card["status"] == "open"

    for feature in ("sales", "attendance"):
        company.features = ["finance", feature]
        company.save(update_fields=["features"])
        cards = queries.branches_today(owner, local(12, 0))
        assert next(c for c in cards if c["id"] == branch.pk)["status"] == "not_opened"
