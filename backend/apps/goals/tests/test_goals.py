"""Business goals (v11): every metric from the data of its module, progress and the forecast
to the period's end in each state, the services' rules, the weekly beat with its note to the
owners, and the endpoints' permissions and scope."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.attendance.models import AttendanceRecord
from apps.audit.models import AuditLog
from apps.companies.models import Branch
from apps.core.exceptions import DomainError
from apps.finance import defaults
from apps.finance import services as finance
from apps.finance.tests.factories import MoneyAccountFactory
from apps.goals import metrics, progress, services
from apps.goals.models import Goal, GoalPoint, Metric
from apps.hr.tests.factories import EmployeeProfileFactory
from apps.inbox.models import Notification
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.sales.models import DailySales

pytestmark = pytest.mark.django_db
D = Decimal
URL = "/api/v1/owner/companies/{}/goals/"


@pytest.fixture
def shop(company):
    company.features = ["finance", "sales", "attendance", "learning"]
    company.save(update_fields=["features"])
    defaults.ensure(company)
    return company


@pytest.fixture
def boss(shop, member):
    return member(shop, "Owner", first_name="Dilnoza", last_name="Karimova")


@pytest.fixture
def today(shop):
    return services.local_today(shop)


@pytest.fixture
def chilonzor(shop):
    return Branch.objects.filter(company=shop).order_by("pk").first() or Branch.objects.create(
        company=shop, name="Chilonzor"
    )


@pytest.fixture
def bank(shop):
    return MoneyAccountFactory(company=shop, name="Bank", kind="bank")


def earn(company, by, account, amount, day, branch=None, category="sales"):
    return finance.record_transaction(
        company,
        by=by,
        kind="income",
        amount=D(amount),
        occurred_on=day,
        account=account,
        category=category,
        branch=branch,
    )


def spend(company, by, account, amount, day, category="rent", branch=None):
    return finance.record_transaction(
        company,
        by=by,
        kind="expense",
        amount=D(amount),
        occurred_on=day,
        account=account,
        category=category,
        branch=branch,
    )


def goal(company, by, metric, target, start, end, **fields):
    return services.create_goal(
        company,
        by=by,
        title=fields.pop("title", f"{metric} goal"),
        metric=metric,
        target=target,
        starts_on=start,
        ends_on=end,
        **fields,
    )


# Metrics from data ---------------------------------------------------------------------------


def test_money_metrics_equal_the_profit_and_loss(shop, boss, bank, today):
    start = today - timedelta(days=9)
    finance.record_transaction(
        shop, by=boss, kind="opening", amount=D("100000000"), occurred_on=start, account=bank
    )
    earn(shop, boss, bank, "50000000", start)
    spend(shop, boss, bank, "20000000", start, category="goods")
    spend(shop, boss, bank, "10000000", start + timedelta(days=1))

    assert metrics.revenue(shop, start, today, None) == D("50000000.00")
    assert metrics.gross_profit(shop, start, today, None) == D("30000000.00")
    assert metrics.net_profit(shop, start, today, None) == D("20000000.00")
    assert metrics.margin(shop, start, today, None) == D("40.00")
    assert metrics.margin(shop, today + timedelta(days=1), today + timedelta(days=2), None) is None


def test_branch_metrics_follow_the_branch(shop, boss, bank, today, chilonzor):
    yunusobod = Branch.objects.create(company=shop, name="Yunusobod")
    earn(shop, boss, bank, "7000000", today, branch=chilonzor)
    earn(shop, boss, bank, "3000000", today, branch=yunusobod)

    assert metrics.revenue(shop, today, today, [chilonzor.pk]) == D("7000000.00")
    assert metrics.revenue(shop, today, today, None) == D("10000000.00")


def test_branches_open_leave_out_offices_and_closed_ones(shop, chilonzor, today):
    Branch.objects.create(company=shop, name="Yunusobod")
    Branch.objects.create(company=shop, name="Ofis", kind="office")
    Branch.objects.create(company=shop, name="Eski", is_active=False)

    assert metrics.branches(shop, today, today, None) == D(2)
    assert metrics.branches(shop, today, today - timedelta(days=30), None) == D(0)


def test_headcount_and_turnover_as_hr_counts_them(shop, member, today):
    start = today - timedelta(days=60)
    for index in range(9):
        person = member(shop, "Employee", first_name=f"Xodim {index}")
        EmployeeProfileFactory(membership=person, hire_date=start - timedelta(days=100))
    gone = member(shop, "Employee", first_name="Nodira", status=Membership.Status.LEFT)
    EmployeeProfileFactory(
        membership=gone,
        hire_date=start - timedelta(days=100),
        terminated_on=today - timedelta(days=10),
    )

    assert metrics.headcount(shop, start, start, None) == D(10)
    assert metrics.headcount(shop, start, today, None) == D(9)
    # One leaver per (10 + 9) / 2 people.
    assert metrics.turnover(shop, start, today, None) == D("10.53")


def test_average_check_from_the_sales_days(shop, chilonzor, today):
    DailySales.objects.create(
        company=shop,
        branch=chilonzor,
        day=today,
        sales=D("5800000"),
        refunds=D("300000"),
        net=D("5500000"),
        receipts=100,
        computed_at=timezone.now(),
    )

    assert metrics.average_check(shop, today, today, None) == D("55000.00")
    assert (
        metrics.average_check(shop, today - timedelta(days=3), today - timedelta(1), None) is None
    )


def test_late_arrivals_per_day_someone_came(shop, member, chilonzor, today):
    people = [member(shop, "Employee", home_branch=chilonzor) for _ in range(2)]
    for person in people:
        person.branches.add(chilonzor)
    for offset in range(5):
        for index, person in enumerate(people):
            AttendanceRecord.objects.create(
                company=shop,
                membership=person,
                branch=chilonzor,
                date=today - timedelta(days=offset),
                status=AttendanceRecord.Status.CLOSED,
                is_late=index == 0 and offset < 2,
                late_minutes=12 if index == 0 and offset < 2 else 0,
            )

    assert metrics.late_arrivals(shop, today - timedelta(days=4), today, [chilonzor.pk]) == D(
        "20.00"
    )


def test_training_from_the_mandatory_courses(shop, monkeypatch, today):
    from apps.learning import queries as learning

    monkeypatch.setattr(
        learning,
        "compliance",
        lambda company, *, branch_ids, now: type("Report", (), {"people": 8, "completed": 6})(),
    )

    assert metrics.training(shop, today, today, None) == D("75.00")


def test_only_metrics_whose_module_is_on_and_numbers_are_seen(shop, member):
    manager = member(shop, "Manager")
    keys = {spec.key for spec in metrics.for_member(manager)}
    # Managers see sales, people, attendance and training, never the profit.
    assert keys == {
        Metric.BRANCHES,
        Metric.HEADCOUNT,
        Metric.TURNOVER,
        Metric.AVERAGE_CHECK,
        Metric.LATE_ARRIVALS,
        Metric.TRAINING,
    }
    shop.features = ["finance"]
    shop.save(update_fields=["features"])
    owner = member(shop, "Owner")
    assert {spec.key for spec in metrics.for_member(owner)} == {
        Metric.REVENUE,
        Metric.GROSS_PROFIT,
        Metric.NET_PROFIT,
        Metric.MARGIN,
        Metric.BRANCHES,
        Metric.HEADCOUNT,
        Metric.TURNOVER,
    }


# Progress and the states -----------------------------------------------------------------------


def revenue_goal(shop, boss, bank, target, *, days=30, elapsed=10, earned="0"):
    """A 30-day revenue goal `elapsed` days old that earned `earned` so far."""
    today = services.local_today(shop)
    start = today - timedelta(days=elapsed - 1)
    if D(earned):
        earn(shop, boss, bank, earned, start)
    return goal(shop, boss, Metric.REVENUE, target, start, start + timedelta(days=days - 1))


def test_a_sum_forecasts_the_pace_to_the_end(shop, boss, bank, today):
    made = revenue_goal(shop, boss, bank, "90000000", earned="40000000")

    now = progress.evaluate(made, today)

    assert now.value == D("40000000.00")
    assert now.forecast == D("120000000.00")  # 40 mln in 10 of 30 days
    assert now.state == Goal.State.ON_TRACK
    assert now.progress == D("44.4")
    assert now.days_left == 20


@pytest.mark.parametrize(
    ("target", "state"),
    [("120000000", "on_track"), ("130000000", "at_risk"), ("140000000", "off_track")],
)
def test_on_track_at_risk_off_track(shop, boss, bank, today, target, state):
    made = revenue_goal(shop, boss, bank, target, earned="40000000")

    assert progress.evaluate(made, today).state == state


def test_the_first_week_is_never_off_track(shop, boss, bank, today):
    made = revenue_goal(shop, boss, bank, "500000000", elapsed=3, earned="1000000")

    assert progress.evaluate(made, today).state == Goal.State.AT_RISK


def test_a_ceiling_metric_is_on_track_under_it(shop, boss, member, chilonzor, today):
    people = [member(shop, "Employee") for _ in range(10)]
    for person in people:
        AttendanceRecord.objects.create(
            company=shop,
            membership=person,
            branch=chilonzor,
            date=today,
            status=AttendanceRecord.Status.CLOSED,
            is_late=person == people[0],
        )
    start = today - timedelta(days=9)
    under = goal(shop, boss, Metric.LATE_ARRIVALS, "12", start, start + timedelta(days=29))
    close = goal(shop, boss, Metric.LATE_ARRIVALS, "9.5", start, start + timedelta(days=29))
    over = goal(shop, boss, Metric.LATE_ARRIVALS, "5", start, start + timedelta(days=29))

    assert [progress.evaluate(row, today).state for row in (under, close, over)] == [
        "on_track",
        "at_risk",  # 10 % against 9.5 %: within the point of tolerance
        "off_track",
    ]
    assert progress.evaluate(under, today).progress == D("100.0")
    assert progress.evaluate(over, today).progress == D("50.0")


def test_a_level_goal_compares_the_way_with_the_time(shop, boss, chilonzor, today):
    def branch_goal(elapsed: int) -> Goal:
        start = today - timedelta(days=elapsed - 1)
        made = goal(shop, boss, Metric.BRANCHES, "3", start, start + timedelta(days=99))
        Goal.objects.filter(pk=made.pk).update(baseline=D(1))
        made.refresh_from_db()
        return made

    # No new branch yet: fine for the first quarter of the time, at risk to its half.
    assert progress.evaluate(branch_goal(20), today).state == "on_track"
    assert progress.evaluate(branch_goal(40), today).state == "at_risk"
    assert progress.evaluate(branch_goal(80), today).state == "off_track"
    assert progress.evaluate(branch_goal(80), today).progress == D("0.0")
    # One of the two to open is there: half the way.
    Branch.objects.create(company=shop, name="Yunusobod")
    assert progress.evaluate(branch_goal(70), today).state == "on_track"  # 50 >= 70 - 25
    assert progress.evaluate(branch_goal(90), today).state == "at_risk"  # 50 >= 90 - 50
    assert progress.evaluate(branch_goal(70), today).progress == D("50.0")
    Branch.objects.create(company=shop, name="Sergeli")
    assert progress.evaluate(branch_goal(95), today).state == "on_track"  # reached


def test_before_after_and_without_data(shop, boss, bank, today):
    later = goal(
        shop, boss, Metric.REVENUE, "1000", today + timedelta(days=3), today + timedelta(days=9)
    )
    assert progress.evaluate(later, today).state == Goal.State.NOT_STARTED
    past = today - timedelta(days=40)
    earn(shop, boss, bank, "5000000", past)
    won = goal(shop, boss, Metric.REVENUE, "4000000", past, past + timedelta(days=29))
    lost = goal(shop, boss, Metric.REVENUE, "6000000", past, past + timedelta(days=29))
    assert won.status == Goal.Status.ACHIEVED  # judged as soon as it was set
    assert lost.status == Goal.Status.MISSED
    check = goal(shop, boss, Metric.AVERAGE_CHECK, "50000", today - timedelta(days=5), today)
    assert progress.evaluate(check, today).state == Goal.State.NO_DATA
    shop.features = []
    shop.save(update_fields=["features"])
    assert progress.evaluate(won, today).state == Goal.State.NO_DATA


# The services ----------------------------------------------------------------------------------


def test_goal_rules(shop, boss, chilonzor, today):
    week = (today, today + timedelta(days=6))
    for metric, target, extra in (
        ("unknown", "1", {}),
        (Metric.REVENUE, "0", {}),  # more is better: a target above zero
        (Metric.MARGIN, "120", {}),  # a percent is at most 100
        (Metric.BRANCHES, "3", {"branch": chilonzor}),  # the whole company's
    ):
        with pytest.raises(DomainError):
            goal(shop, boss, metric, target, *week, **extra)
    with pytest.raises(DomainError):
        goal(shop, boss, Metric.REVENUE, "1", today, today - timedelta(days=1))
    with pytest.raises(DomainError):
        goal(shop, boss, Metric.REVENUE, "1", today, today + timedelta(days=800))
    with pytest.raises(DomainError):
        goal(shop, boss, Metric.REVENUE, "1", *week, title=" ")
    # A ceiling may be zero: no late arrivals at all.
    assert goal(shop, boss, Metric.LATE_ARRIVALS, "0", *week).target == 0
    shop.features = ["finance"]
    shop.save(update_fields=["features"])
    with pytest.raises(DomainError):  # sales is off
        goal(shop, boss, Metric.AVERAGE_CHECK, "50000", *week)


def test_update_archive_restore_and_delete_are_audited(shop, boss, bank, today):
    made = goal(shop, boss, Metric.REVENUE, "1000000", today, today + timedelta(days=29))
    GoalPoint.objects.create(goal=made, on=today, value=D(0), state="on_track")

    services.update_goal(made, by=boss, target="2000000", title="Ko‘proq")
    made.refresh_from_db()
    assert (made.title, made.target) == ("Ko‘proq", D("2000000.00"))
    services.update_goal(made, by=boss, starts_on=today - timedelta(days=1))
    assert not GoalPoint.objects.filter(goal=made).exists()  # measured again from the new start
    services.archive_goal(made, by=boss)
    made.refresh_from_db()
    assert made.status == Goal.Status.ARCHIVED
    with pytest.raises(DomainError):
        services.update_goal(made, by=boss, target="5")
    services.restore_goal(made, by=boss)
    made.refresh_from_db()
    assert made.status == Goal.Status.ACTIVE
    services.delete_goal(made, by=boss)
    assert not Goal.objects.filter(pk=made.pk).exists()
    actions = list(
        AuditLog.objects.filter(company_id=shop.pk, target_type="goal")
        .order_by("pk")
        .values_list("action", flat=True)
    )
    assert actions == [
        "goals.goal_created",
        "goals.goal_updated",
        "goals.goal_updated",
        "goals.goal_archived",
        "goals.goal_restored",
        "goals.goal_deleted",
    ]
    # A profit goal's history needs finance.view.
    assert set(
        AuditLog.objects.filter(company_id=shop.pk, target_type="goal").values_list(
            "required_perm", flat=True
        )
    ) == {Perm.FINANCE_VIEW}


# The weekly beat ---------------------------------------------------------------------------------


def test_the_beat_adds_a_point_and_tells_the_owners_once_per_turn(
    shop, boss, bank, member, today, django_capture_on_commit_callbacks
):
    manager = member(shop, "Manager")
    for person in (boss, manager):
        person.user.language = "en"
        person.user.save(update_fields=["language"])
    made = revenue_goal(shop, boss, bank, "120000000", earned="40000000")
    services.update_goal(made, by=boss, owner=manager)  # a manager can't see revenue: not told

    with django_capture_on_commit_callbacks(execute=True):
        assert services.weekly() == 1
    assert GoalPoint.objects.get(goal=made, on=today).state == "on_track"
    assert not Notification.objects.filter(kind=services.NOTIFY_KIND).exists()

    services.update_goal(made, by=boss, target="130000000")  # now at risk
    with django_capture_on_commit_callbacks(execute=True):
        services.weekly()
        services.weekly()  # the same state again: no second note
    notes = Notification.objects.filter(kind=services.NOTIFY_KIND)
    assert [note.recipient_id for note in notes] == [boss.pk]
    assert notes[0].title.startswith("Goal at risk")
    assert "Revenue now" in notes[0].body

    services.update_goal(made, by=boss, target="150000000")  # worse: off track
    with django_capture_on_commit_callbacks(execute=True):
        services.weekly()
    assert notes.all().count() == 2
    assert notes.all().order_by("-pk").first().title.startswith("Goal off track")

    services.update_goal(made, by=boss, target="100000000")  # back on track
    with django_capture_on_commit_callbacks(execute=True):
        services.weekly()
    made.refresh_from_db()
    assert made.notified_state == ""
    assert notes.all().count() == 2


# The endpoints ---------------------------------------------------------------------------------


def test_list_and_detail(shop, boss, bank, owner_api, today):
    made = revenue_goal(shop, boss, bank, "120000000", earned="40000000")
    GoalPoint.objects.create(
        goal=made, on=today - timedelta(days=7), value=D("10000000"), state="on_track"
    )

    response = owner_api(boss).get(URL.format(shop.pk))

    assert response.status_code == 200
    data = response.json()
    assert data["can_manage"] is True
    assert data["counts"] == {"active": 1, "done": 0, "archived": 0}
    row = data["goals"][0]
    assert row["value"] == "40000000.00"
    assert row["forecast"] == "120000000.00"
    assert row["state"] == "on_track"
    assert row["unit"] == "money"
    assert [point["on"] for point in row["series"]] == [
        (today - timedelta(days=7)).isoformat(),
        today.isoformat(),
    ]
    detail = owner_api(boss).get(f"{URL.format(shop.pk)}{made.pk}/").json()
    assert detail["id"] == made.pk
    assert detail["can_edit"] is True


def test_create_patch_archive_and_delete_through_the_api(shop, boss, owner_api, today):
    client = owner_api(boss)
    body = {
        "title": "IV chorak tushumi",
        "metric": "revenue",
        "target": "1500000000",
        "starts_on": today.isoformat(),
        "ends_on": (today + timedelta(days=60)).isoformat(),
        "owner": boss.pk,
    }

    made = client.post(URL.format(shop.pk), body, format="json")

    assert made.status_code == 201
    pk = made.json()["id"]
    assert made.json()["owner"] == {"id": boss.pk, "name": "Dilnoza Karimova"}
    patched = client.patch(f"{URL.format(shop.pk)}{pk}/", {"target": "1600000000"}, format="json")
    assert patched.json()["target"] == "1600000000.00"
    archived = client.post(f"{URL.format(shop.pk)}{pk}/archive/")
    assert archived.json()["status"] == "archived"
    assert client.get(URL.format(shop.pk), {"status": "archived"}).json()["counts"]["archived"] == 1
    assert client.post(f"{URL.format(shop.pk)}{pk}/restore/").json()["status"] == "active"
    assert client.delete(f"{URL.format(shop.pk)}{pk}/").status_code == 204


def test_metrics_and_preview(shop, boss, bank, owner_api, today, chilonzor):
    earn(shop, boss, bank, "30000000", today)
    client = owner_api(boss)

    listed = client.get(f"{URL.format(shop.pk)}metrics/").json()
    assert {row["key"] for row in listed["metrics"]} >= {"revenue", "branches", "late_arrivals"}
    assert listed["company_wide"] is True
    assert {"id": chilonzor.pk, "name": chilonzor.name} in listed["branches"]
    preview = client.get(
        f"{URL.format(shop.pk)}preview/",
        {
            "metric": "revenue",
            "starts_on": today.isoformat(),
            "ends_on": (today + timedelta(days=9)).isoformat(),
            "target": "200000000",
        },
    ).json()
    assert preview["value"] == "30000000.00"
    assert preview["forecast"] == "300000000.00"
    assert preview["state"] == "on_track"
    bad = client.get(f"{URL.format(shop.pk)}preview/", {"metric": "nope"})
    assert bad.status_code == 400


def test_who_sees_and_who_sets_goals(shop, boss, bank, member, owner_api, today, chilonzor):
    yunusobod = Branch.objects.create(company=shop, name="Yunusobod")
    revenue = revenue_goal(shop, boss, bank, "1000000")
    late_here = goal(
        shop, boss, Metric.LATE_ARRIVALS, "5", today, today + timedelta(days=9), branch=chilonzor
    )
    late_there = goal(
        shop, boss, Metric.LATE_ARRIVALS, "5", today, today + timedelta(days=9), branch=yunusobod
    )
    manager = member(shop, "Manager")  # sees every branch, not the profit
    ids = {row["id"] for row in owner_api(manager).get(URL.format(shop.pk)).json()["goals"]}
    assert ids == {late_here.pk, late_there.pk}
    assert owner_api(manager).get(f"{URL.format(shop.pk)}{revenue.pk}/").status_code == 404
    # Setting goals is the owners'.
    body = {
        "title": "Kechikishlar",
        "metric": "late_arrivals",
        "target": "5",
        "starts_on": today.isoformat(),
        "ends_on": today.isoformat(),
    }
    assert owner_api(manager).post(URL.format(shop.pk), body, format="json").status_code == 403
    assert owner_api(manager).get(URL.format(shop.pk)).json()["can_manage"] is False
    # Someone who sees one branch sees its goals only, and nothing company-wide.
    local = member(shop, "Manager")
    local.role.permissions = [p for p in local.role.permissions if p != Perm.BRANCHES_ALL]
    local.role.save(update_fields=["permissions"])
    local.branches.set([chilonzor])
    ids = {row["id"] for row in owner_api(local).get(URL.format(shop.pk)).json()["goals"]}
    assert ids == {late_here.pk}
    # Without reports.view nothing at all.
    worker = member(shop, "Pharmacist")
    worker.role.permissions = [*worker.role.permissions, Perm.DASHBOARD_ACCESS]
    worker.role.save(update_fields=["permissions"])
    assert owner_api(worker).get(URL.format(shop.pk)).status_code == 403


def test_another_companys_goal_is_not_found(shop, boss, owner_api, other_company, member, today):
    made = goal(shop, boss, Metric.BRANCHES, "3", today, today + timedelta(days=9))
    stranger = member(other_company, "Owner")

    response = owner_api(stranger).get(f"{URL.format(other_company.pk)}{made.pk}/")
    assert response.status_code == 404
    assert owner_api(stranger).get(f"{URL.format(shop.pk)}{made.pk}/").status_code == 404


def test_the_bot_note_reads_plainly(shop):
    from apps.goals import bot_messages

    spec = metrics.METRICS[Metric.TURNOVER]
    text = bot_messages.worse_body(
        spec,
        value=D("6.25"),
        forecast=D("12.5"),
        target=D("10"),
        ends_on=date(2026, 12, 31),
        currency="UZS",
        language="uz",
    )
    assert "6,2\u00a0%" in text or "6,3\u00a0%" in text
    assert "12,5\u00a0%" in text
    money = metrics.METRICS[Metric.REVENUE]
    assert (
        bot_messages.amount(money, D("1500000000"), "UZS", "uz")
        == "1\u00a0500\u00a0000\u00a0000\u00a0so‘m"
    )
    assert bot_messages.amount(metrics.METRICS[Metric.BRANCHES], D("3"), "UZS", "uz") == "3"
