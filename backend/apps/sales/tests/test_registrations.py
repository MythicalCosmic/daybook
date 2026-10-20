"""What sales registers with the shared registries: branch facts in their fixed shape, brief
section, portfolio facts, search, stream, queues, pulse, offboarding, setup, AI tools, exporters,
notification buttons and file checks."""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.ai.tools.testing import call_tool
from apps.console import contracts, registry
from apps.console.ranges import Range
from apps.core.files import signed_url
from apps.exports.registry import get_exporter
from apps.inbox import services as inbox
from apps.inbox.models import Notification
from apps.members.permissions import Perm
from apps.sales import queries, services
from apps.sales.models import CashShift
from apps.sales.tests.factories import make_member, open_and_close, scoped_role


def test_branch_facts_have_exactly_the_sales_shape(shop):
    open_and_close(shop)
    services.open_shift(by=shop.colleague, register=shop.other_register, opening_float="250000")
    now = timezone.now()
    facts = queries.branch_facts(
        shop.company, now.date(), now, [shop.branch.pk, shop.other_branch.pk]
    )
    for branch_id in (shop.branch.pk, shop.other_branch.pk):
        assert contracts.problems(contracts.SalesFacts, facts[branch_id]) == []
    assert facts[shop.other_branch.pk]["open_tills"] == 1
    assert facts[shop.other_branch.pk]["opened_by"]["id"] == shop.colleague.pk
    assert facts[shop.other_branch.pk]["cash_in_branch"] == "250000.00"
    assert queries.branch_facts(shop.company, now.date(), now, []) == {}


def test_branches_today_shows_sales_facts(shop, owner_api):
    open_and_close(shop)
    cards = (
        owner_api(shop.owner)
        .get(f"/api/v1/owner/companies/{shop.company.pk}/branches/today/")
        .json()
    )
    chilonzor = next(card for card in cards if card["id"] == shop.branch.pk)
    assert chilonzor["sales"]["net"] == "1500000.00"


def test_brief_section_and_company_facts(shop):
    closed = open_and_close(shop, counted="1180000")
    now = timezone.now()
    brief = queries.brief_section(shop.company, closed.business_day, now, None)
    assert brief["net"] == "1500000.00" and brief["closed_shifts"] == 1
    assert brief["differences"][0]["difference"] == "-20000.00"
    assert brief["lines"]
    assert (
        queries.brief_section(shop.company, closed.business_day - timedelta(days=30), now, None)
        is None
    )
    facts = queries.company_facts(
        shop.company, Range(closed.business_day, closed.business_day), shop.owner
    )
    assert contracts.problems(contracts.SalesCompanyFacts, facts) == []
    assert facts == {"net": "1500000.00", "prev_net": "0.00"}


def test_search_and_stream_respect_branch_scope(shop):
    closed = open_and_close(shop)
    hits = queries.search(shop.owner, closed.code, 5)
    assert [hit.id for hit in hits] == [closed.pk]
    assert hits[0].url.endswith(f"sales/shifts?shift={closed.pk}")
    assert queries.search(shop.owner, "Madina", 5)[0].id == closed.pk
    lead = make_member(shop.company, "Owner", branches=(shop.other_branch,))
    lead.role = scoped_role(shop.company, Perm.SALES_VIEW)
    lead.save(update_fields=["role"])
    assert queries.search(lead, closed.code, 5) == []
    assert [item.kind for item in queries.stream(shop.owner, None, 10)] == ["sales.shift_closed"]
    assert queries.stream(lead, None, 10) == []


def test_queues_and_pulse(shop):
    closed = open_and_close(shop)
    services.open_shift(by=shop.cashier, register=shop.register, opening_float="0")
    movement = services.record_movement(
        by=shop.cashier,
        register=shop.register,
        kind="handover",
        amount="100000",
        receiver=shop.owner,
    )
    owner_queue = registry.queue_items(shop.owner)
    kinds = {(item.kind, item.id) for item in owner_queue}
    assert ("sales.verify", closed.pk) in kinds and ("sales.handover", movement.pk) in kinds
    # The cashier's own shift offers no buttons to the cashier (if they could see the queue).
    assert all(
        item.actions == ()
        for item in queries.verify_items(shop.cashier, 10)
        if item.id == closed.pk
    )
    counts = registry.pulse_counts(shop.manager)
    assert counts["sales.open_shifts"] == 1 and counts["sales.to_verify"] == 1


def test_offboard_step_blocks_on_an_open_till_and_pending_handovers(shop):
    services.open_shift(by=shop.cashier, register=shop.register, opening_float="0")
    services.record_movement(
        by=shop.cashier,
        register=shop.register,
        kind="handover",
        amount="100000",
        receiver=shop.manager,
    )
    step = queries.offboard_preview(shop.cashier)
    assert len(step.blockers) == 1 and "CHL-1" in step.blockers[0]
    assert step.lines  # the handover they made, not confirmed yet
    receiver = queries.offboard_preview(shop.manager)
    assert receiver.blockers  # a handover waits for them
    steps = registry.collect_offboard_steps(shop.cashier, by=shop.owner)
    assert "sales" in {step["key"] for step in steps}


def test_setup_step(shop):
    [step] = [s for s in registry.collect_setup_steps(shop.owner) if s["key"] == "sales.registers"]
    assert step["done"] is False
    open_and_close(shop)
    [step] = [s for s in registry.collect_setup_steps(shop.owner) if s["key"] == "sales.registers"]
    assert step["done"] is True


def test_ai_tools_follow_permission_switch_and_scope(shop):
    closed = open_and_close(shop)
    day = closed.business_day.isoformat()
    result = call_tool("sales_summary", shop.owner, start=day, end=day, group_by="branch")
    assert result["data"]["totals"]["net"] == "1500000.00"
    assert all("id" in row for row in result["rows"])
    scorecard = call_tool("sales_cashier_scorecard", shop.owner, start=day, end=day)
    assert scorecard["rows"][0]["id"] == shop.cashier.pk
    assert call_tool("sales_summary", shop.owner, _switches=frozenset(), start=day, end=day)[
        "error"
    ] in {
        "not_allowed",
        "unknown_tool",
    }
    lead = make_member(shop.company, "Owner", branches=(shop.other_branch,))
    lead.role = scoped_role(shop.company, Perm.SALES_VIEW)
    lead.save(update_fields=["role"])
    assert call_tool("sales_summary", lead, start=day, end=day)["data"]["totals"]["net"] == "0.00"
    assert call_tool("sales_summary", lead, start=day, end=day, branch_id=shop.branch.pk) == {
        "error": "not_found"
    }
    worker = make_member(shop.company, "Employee")
    assert call_tool("sales_summary", worker, start=day, end=day)["error"] == "not_allowed"


def test_exporters_yield_their_columns_in_scope(shop):
    closed = open_and_close(shop)
    open_and_close(shop, cashier=shop.colleague, register=shop.other_register)
    daily = get_exporter("sales.daily")
    columns = {column.key for column in daily.columns}
    rows = list(daily.rows(shop.owner, {}))
    assert len(rows) == 2 and set(rows[0]) == columns
    lead = make_member(shop.company, "Owner", branches=(shop.other_branch,))
    lead.role = scoped_role(shop.company, Perm.SALES_VIEW, Perm.DATA_EXPORT)
    lead.save(update_fields=["role"])
    assert [row["branch"] for row in daily.rows(lead, {})] == ["Yunusobod"]
    shifts = get_exporter("sales.shifts")
    exported = list(shifts.rows(shop.owner, {}))
    assert {row["code"] for row in exported} == {closed.code, "YNS-2"}
    assert set(exported[0]) == {column.key for column in shifts.columns}


def test_handover_buttons_work_through_run_action(shop, django_capture_on_commit_callbacks):
    services.open_shift(by=shop.cashier, register=shop.register, opening_float="0")
    with django_capture_on_commit_callbacks(execute=True):
        movement = services.record_movement(
            by=shop.cashier,
            register=shop.register,
            kind="handover",
            amount="100000",
            receiver=shop.owner,
        )
    note = Notification.objects.get(kind="sales.handover", recipient=shop.owner)
    message = inbox.run_action(note.pk, "received", by=shop.owner)
    assert "received" in message.lower()
    movement.refresh_from_db()
    assert movement.status == "done"


def test_verify_button_checks_permission_and_scope(shop, django_capture_on_commit_callbacks):
    from apps.inbox.models import NotificationPreference

    # Closed shifts live in Needs you; a manager who asked for them in Telegram gets a button.
    for person in (shop.manager, shop.owner):
        NotificationPreference.objects.create(
            membership=person, kind="sales.shift_closed", in_app=False, telegram=True
        )
    with django_capture_on_commit_callbacks(execute=True):
        closed = open_and_close(shop)
    note = Notification.objects.get(kind="sales.shift_closed", recipient=shop.manager)
    assert note.in_app is False and [a["key"] for a in note.actions] == ["verify"]
    inbox.run_action(note.pk, "verify", by=shop.manager)
    assert CashShift.objects.get(pk=closed.pk).status == "verified"
    # The owner's copy was settled with it.
    assert Notification.objects.get(kind="sales.shift_closed", recipient=shop.owner).acted_at


def test_shift_photos_open_for_the_cashier_and_sales_viewers_only(shop, client):
    closed = open_and_close(shop)
    for person, allowed in ((shop.cashier, True), (shop.manager, True), (shop.colleague, False)):
        link = signed_url(
            closed.z_photo,
            user=person.user,
            company_id=shop.company.pk,
            check=f"sales.shift_photo:{closed.pk}",
        )
        assert (client.get(link).status_code == 200) is allowed, person


def test_money_in_branch_facts_is_a_string(shop):
    open_and_close(shop)
    now = timezone.now()
    facts = queries.branch_facts(shop.company, now.date(), now, [shop.branch.pk])
    assert isinstance(facts[shop.branch.pk]["net"], str)
    assert Decimal(facts[shop.branch.pk]["net"]) == Decimal("1500000.00")
