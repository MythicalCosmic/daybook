"""Automatic bonuses and fines: the arithmetic of a rule, the sales bonus golden case (§14.11),
idempotent evaluation, daily rules, the preview, the shipped examples and the API."""

from datetime import date
from decimal import Decimal

import pytest

from apps.attendance.models import AttendanceRecord
from apps.payroll import defaults, rules, services
from apps.payroll.models import Adjustment, AdjustmentRule, PayslipLine
from apps.payroll.tests.conftest import OCTOBER, local

pytestmark = pytest.mark.django_db

D = Decimal
Rule = AdjustmentRule


def url(company, path=""):
    return f"/api/v1/owner/companies/{company.pk}/payroll/{path}"


def rule(company, **fields) -> AdjustmentRule:
    fields.setdefault("name", "Rule")
    fields.setdefault("kind", Rule.Kind.BONUS)
    fields.setdefault("is_active", True)
    positions = fields.pop("positions", None)
    row = services.save_rule(company, by=None, **fields)
    if positions:
        row.positions.set(positions)
    return row


@pytest.fixture
def team(staff, freeze, monkeypatch):
    freeze(local(date(2026, 11, 3), 10))
    monkeypatch.setattr(
        "apps.hr.queries.employment_dates",
        lambda company, member_ids: {pk: (date(2025, 6, 1), None) for pk in member_ids},
    )
    services.set_pay(staff.ali, by=None, effective_from=date(2026, 1, 1), amount="5200000")
    services.set_pay(staff.vali, by=None, effective_from=date(2026, 1, 1), amount="5200000")
    return staff


@pytest.fixture
def sales(shop, team, monkeypatch):
    """Ali sold 48 000 000 net in October (the cashier scorecard of package E)."""
    shop.features = [*shop.features, "sales"]
    shop.save(update_fields=["features"])
    table = {team.ali.pk: D("48000000")}

    def cashier_scorecard(company, start, end, *, branch_ids):
        return [
            {"member": {"id": pk, "name": "x"}, "net": net, "shifts": 20}
            for pk, net in table.items()
        ]

    monkeypatch.setattr("apps.sales.queries.cashier_scorecard", cashier_scorecard)
    return table


class TestOutcome:
    def make(self, **fields):
        base = {
            "name": "x",
            "kind": "bonus",
            "metric": Rule.Metric.TASKS_DONE,
            "mode": Rule.Mode.ONCE,
            "op": Rule.Op.GTE,
            "free_units": D(0),
            "amount_type": Rule.AmountType.FIXED,
        }
        return AdjustmentRule(**{**base, **fields})

    def test_once(self):
        row = self.make(threshold=D(100), amount=D(50000))
        assert rules.outcome(row, D(100), None).amount == D("50000.00")
        assert rules.outcome(row, D(99), None) is None
        assert rules.outcome(row, None, None) is None

    def test_per_unit_with_free_units_and_a_cap(self):
        row = self.make(
            mode=Rule.Mode.PER_UNIT, free_units=D(2), amount=D(20000), cap=D(50000), kind="fine"
        )
        assert rules.outcome(row, D(2), None) is None
        assert rules.outcome(row, D(4), None).amount == D("40000.00")
        assert rules.outcome(row, D(9), None).amount == D("50000")

    def test_tiered_picks_the_best_tier_reached(self):
        row = self.make(
            mode=Rule.Mode.TIERED,
            tiers=[
                {"threshold": "90", "amount": "100000"},
                {"threshold": "95", "amount": "300000"},
            ],
        )
        assert rules.outcome(row, D("89.9"), None) is None
        assert rules.outcome(row, D("93"), None).amount == D("100000.00")
        assert rules.outcome(row, D("97.5"), None).tier == D("95")
        lower = self.make(
            mode=Rule.Mode.TIERED,
            op=Rule.Op.LTE,
            tiers=[{"threshold": "5", "amount": "10"}, {"threshold": "2", "amount": "30"}],
        )
        assert rules.outcome(lower, D(1), None).amount == D("30.00")

    def test_percent_of_the_base(self):
        row = self.make(
            metric=Rule.Metric.SALES_NET,
            threshold=D(0),
            op=Rule.Op.GT,
            amount_type=Rule.AmountType.PERCENT,
            amount=D("1.00"),
        )
        assert rules.outcome(row, D(48000000), D(48000000)).amount == D("480000.00")


def test_sales_bonus_golden_and_the_preview_equals_the_run_line(shop, team, sales):
    bonus = rule(
        shop,
        name="Sales bonus",
        metric=Rule.Metric.SALES_NET,
        mode=Rule.Mode.ONCE,
        op=Rule.Op.GT,
        threshold=D(0),
        amount_type=Rule.AmountType.PERCENT,
        amount=D("1.00"),
        auto_approve=True,
    )
    preview = rules.preview(bonus, OCTOBER)
    rows = {row["member"].pk: row for row in preview["rows"]}
    assert rows[team.ali.pk]["amount"] == D("480000.00")
    assert rows[team.vali.pk]["amount"] is None
    assert preview["total"] == D("480000.00")
    run = services.create_run(shop, by=team.owner, period="2026-10")
    line = PayslipLine.objects.get(payslip__run=run, kind="bonus")
    assert line.amount == preview["total"]
    assert line.payslip.membership == team.ali
    assert line.payslip.net == D("5680000.00")


def test_evaluation_never_doubles_and_follows_the_metric(shop, team, sales):
    bonus = rule(
        shop,
        metric=Rule.Metric.SALES_NET,
        mode=Rule.Mode.ONCE,
        op=Rule.Op.GT,
        threshold=D(0),
        amount_type=Rule.AmountType.PERCENT,
        amount=D("1.00"),
    )
    assert rules.evaluate_monthly(shop, OCTOBER) == 1
    assert rules.evaluate_monthly(shop, OCTOBER) == 0
    row = Adjustment.objects.get(rule=bonus)
    assert row.status == "proposed" and row.source == "rule" and row.rule_key.endswith("2026-10")
    assert row.amount == D("480000.00")
    sales[team.ali.pk] = D("50000000")
    assert rules.evaluate_monthly(shop, OCTOBER) == 1
    row.refresh_from_db()
    assert row.amount == D("500000.00")
    # Once someone decided it, it stays as decided.
    services.approve(row, by=team.owner)
    sales[team.ali.pk] = D("0")
    assert rules.evaluate_monthly(shop, OCTOBER) == 0
    row.refresh_from_db()
    assert row.status == "approved" and row.amount == D("500000.00")


def test_a_proposal_the_metric_no_longer_earns_is_voided(shop, team, sales):
    rule(
        shop,
        metric=Rule.Metric.SALES_NET,
        mode=Rule.Mode.ONCE,
        op=Rule.Op.GTE,
        threshold=D(40000000),
        amount=D(100000),
    )
    rules.evaluate_monthly(shop, OCTOBER)
    sales[team.ali.pk] = D("1000")
    rules.evaluate_monthly(shop, OCTOBER)
    assert Adjustment.objects.get().status == "void"


def test_min_tasks_and_positions(shop, team, chilonzor):
    on_time = rule(
        shop,
        metric=Rule.Metric.TASKS_ON_TIME_PERCENT,
        mode=Rule.Mode.ONCE,
        op=Rule.Op.GTE,
        threshold=D(0),
        amount=D(1000),
        min_tasks=10,
    )
    assert rules.evaluate_monthly(shop, OCTOBER) == 0  # nobody has 10 tasks
    absences = rule(
        shop,
        kind="fine",
        metric=Rule.Metric.ABSENCES,
        mode=Rule.Mode.PER_UNIT,
        amount=D(50000),
        positions=[team.pharmacist],
    )
    AttendanceRecord.objects.create(
        company=shop, membership=team.ali, date=date(2026, 10, 5), status="absent"
    )
    assert rules.evaluate_monthly(shop, OCTOBER) == 1
    fine = Adjustment.objects.get(rule=absences)
    assert fine.membership == team.ali and fine.amount == D("50000.00")
    assert not Adjustment.objects.filter(rule=on_time).exists()


def test_daily_rule_proposes_what_each_day_adds(shop, team):
    rule(
        shop,
        kind="fine",
        metric=Rule.Metric.LATE_ARRIVALS,
        mode=Rule.Mode.PER_UNIT,
        free_units=D(2),
        amount=D(20000),
        evaluate=Rule.Evaluate.DAILY,
    )

    def late(day):
        AttendanceRecord.objects.create(
            company=shop,
            membership=team.ali,
            date=day,
            status="closed",
            is_late=True,
            late_minutes=15,
            worked_minutes=480,
        )

    for day in (5, 6, 7):
        late(date(2026, 10, day))
    assert rules.evaluate_daily(shop, date(2026, 10, 8)) == 1
    assert rules.evaluate_daily(shop, date(2026, 10, 8)) == 0  # once a day
    late(date(2026, 10, 8))
    assert rules.evaluate_daily(shop, date(2026, 10, 9)) == 1
    amounts = sorted(Adjustment.objects.values_list("amount", flat=True))
    assert amounts == [D("20000.00"), D("20000.00")]
    assert rules.evaluate_daily(shop, date(2026, 10, 10)) == 0  # nothing new


def test_shipped_examples_are_off_and_made_once(shop):
    defaults.ensure(shop)
    defaults.ensure(shop)
    examples = AdjustmentRule.objects.filter(company=shop).exclude(example_key="")
    assert {row.example_key for row in examples} == {"on_time", "late_arrivals", "sales_bonus"}
    assert not any(row.is_active for row in examples)


class TestApi:
    def test_crud_and_preview(self, shop, team, sales, owner_api):
        client = owner_api(team.accountant)
        created = client.post(
            url(shop, "rules/"),
            {
                "name": "Sales bonus",
                "kind": "bonus",
                "metric": "sales.net",
                "mode": "once",
                "op": "gt",
                "threshold": "0",
                "amount_type": "percent",
                "amount": "1.00",
                "is_active": True,
            },
            format="json",
        )
        assert created.status_code == 201, created.data
        assert created.data["amount"] == "1.00" and created.data["is_active"]
        rule_id = created.data["id"]
        preview = client.post(url(shop, f"rules/{rule_id}/preview/"), {"period": "2026-10"})
        assert preview.status_code == 200, preview.data
        assert preview.data["total"] == "480000.00"
        mine = next(row for row in preview.data["rows"] if row["member"]["id"] == team.ali.pk)
        assert mine["amount"] == "480000.00" and mine["value"] == "48000000.00"
        changed = client.patch(
            url(shop, f"rules/{rule_id}/"), {"positions": [team.pharmacist.pk]}, format="json"
        )
        assert changed.data["positions"] == [{"id": team.pharmacist.pk, "name": "Pharmacist"}]
        assert client.delete(url(shop, f"rules/{rule_id}/")).status_code == 204

    def test_validation_and_permissions(self, shop, team, owner_api):
        client = owner_api(team.owner)
        bad = client.post(
            url(shop, "rules/"),
            {"name": "Tiers", "kind": "bonus", "metric": "tasks.done", "mode": "tiered"},
            format="json",
        )
        assert bad.status_code == 400
        too_much = client.post(
            url(shop, "rules/"),
            {
                "name": "x",
                "kind": "bonus",
                "metric": "sales.net",
                "mode": "once",
                "threshold": "1",
                "amount_type": "percent",
                "amount": "150",
            },
            format="json",
        )
        assert too_much.status_code == 400
        assert owner_api(team.manager).get(url(shop, "rules/")).status_code == 403
