"""The hourly job: reminders at the company's morning hour, once per step; the notice
deadline of auto-renewing contracts with its two buttons; renewals by themselves; and what the
contracts give the cockpit (a lease-ending insight, renewal decisions) and the agenda."""

from datetime import date, time

import pytest

from apps.contracts import notify, providers, queries, services, watch
from apps.contracts.models import BusinessContract
from apps.contracts.tests.conftest import local
from apps.inbox import services as inbox
from apps.inbox.models import Notification

pytestmark = pytest.mark.django_db
KIND = notify.KIND


def sent(contract=None):
    rows = Notification.objects.filter(kind__in=(KIND, notify.NOTICE_KIND))
    if contract is not None:
        rows = rows.filter(target_id=contract.pk)
    return rows


def run(shop, freeze, day: date, hour: int, minute: int = 30) -> int:
    moment = freeze(local(day, hour, minute))
    return watch.watch_company(shop, moment)


def test_reminders_wait_for_the_morning_and_go_once_per_step(shop, owner, lease, freeze):
    # 30 days before its end (31 December), at 08:30: too early, nothing yet.
    assert run(shop, freeze, date(2026, 12, 1), 8) == 0
    assert not sent().exists()
    # From the morning report time (09:00): the warning, to the owner.
    assert run(shop, freeze, date(2026, 12, 1), 9, 5) == 1
    row = sent().get()
    assert row.recipient_id == owner.pk
    assert row.title == "Contract ends 31.12.2026: Chilonzor dorixonasi ijarasi (Chilonzor)"
    assert "30 days left" in row.body
    assert row.url == f"/c/{shop.pk}/contracts/{lease.pk}"
    # The next hours and days: nothing new.
    assert run(shop, freeze, date(2026, 12, 1), 15) == 0
    assert run(shop, freeze, date(2026, 12, 15), 10) == 0
    # On its last day, once more.
    assert run(shop, freeze, date(2026, 12, 31), 9, 30) == 1
    last = sent().order_by("-pk").first()
    assert last.title == "Contract ends today: Chilonzor dorixonasi ijarasi (Chilonzor)"
    assert last.severity == "warning"
    assert run(shop, freeze, date(2026, 12, 31), 18) == 0
    lease.refresh_from_db()
    assert lease.status == BusinessContract.Status.ENDING
    # The day after: ended, and no reminder about the past.
    assert run(shop, freeze, date(2027, 1, 1), 10) == 0
    lease.refresh_from_db()
    assert lease.status == BusinessContract.Status.ENDED


def test_the_morning_hour_is_the_companys(shop, owner, lease, freeze):
    shop.morning_report_at = time(7, 0)
    shop.save(update_fields=["morning_report_at"])
    assert run(shop, freeze, date(2026, 12, 1), 7, 10) == 1


def test_the_warning_days_come_from_the_settings(shop, owner, lease, freeze):
    services.update_settings(shop, by=owner, remind_days=60)
    assert run(shop, freeze, date(2026, 11, 7), 10) == 1  # 54 days left: inside 60
    lease.refresh_from_db()
    assert lease.status == BusinessContract.Status.ENDING


def test_found_late_it_says_the_tightest_step_only(shop, owner, lease, freeze):
    # The job was down for weeks and comes back on the last day: one reminder, "today".
    assert run(shop, freeze, date(2026, 12, 31), 11) == 1
    assert sent().get().title.startswith("Contract ends today")
    lease.refresh_from_db()
    assert {"end:2026-12-31:soon", "end:2026-12-31:today"} <= set(lease.reminders_sent)


def test_who_hears(shop, owner, manager, reader, ali, lease, yunusobod, freeze):
    # A company-wide contract: the owner only (the manager sees Chilonzor only; the reader
    # can't change contracts; Ali has no money permissions).
    services.update_contract(lease, by=owner, branch=None)
    assert run(shop, freeze, date(2026, 12, 1), 10) == 1
    assert set(sent().values_list("recipient_id", flat=True)) == {owner.pk}
    # On Chilonzor, the Chilonzor manager too; and the person looking after it.
    other = services.create_contract(
        shop,
        by=owner,
        kind="service",
        title="Tozalash",
        branch=lease.branch,
        starts_on=date(2026, 1, 1),
        ends_on=date(2026, 12, 20),
        responsible=ali,
    )
    assert run(shop, freeze, date(2026, 12, 2), 10) == 3  # one notice per person
    assert set(sent(other).values_list("recipient_id", flat=True)) == {owner.pk, manager.pk, ali.pk}
    assert "Renew it or find a new one" in sent(other).first().body
    # On Yunusobod: not the Chilonzor manager.
    far = services.create_contract(
        shop,
        by=owner,
        kind="lease",
        title="Yunusobod ijarasi",
        branch=yunusobod,
        starts_on=date(2026, 1, 1),
        ends_on=date(2026, 12, 25),
    )
    run(shop, freeze, date(2026, 12, 3), 10)
    assert set(sent(far).values_list("recipient_id", flat=True)) == {owner.pk}


def test_the_notice_deadline_of_an_auto_renewing_contract(shop, owner, lease, freeze):
    # Renews by itself; 60 days' notice: the deadline is 1 November... too late this year,
    # so 30 days: the deadline is 1 December, warned 14 days before (17 November).
    lease = services.update_contract(lease, by=owner, auto_renews=True, notice_days=30)
    assert lease.notice_deadline == date(2026, 12, 1)
    assert run(shop, freeze, date(2026, 11, 16), 10) == 0
    assert run(shop, freeze, date(2026, 11, 17), 10) == 1
    row = sent().get()
    assert row.title == "Notice deadline 01.12.2026: Chilonzor dorixonasi ijarasi (Chilonzor)"
    assert "tell Rustam Qodirov (ijara) in writing by 01.12.2026" in row.body
    assert [action["key"] for action in row.actions] == ["keep", "stop"]
    assert run(shop, freeze, date(2026, 11, 20), 10) == 0
    assert run(shop, freeze, date(2026, 12, 1), 10) == 1  # the deadline itself
    assert sent().order_by("-pk").first().title.startswith("Notice deadline today")
    # No "ends" reminders for a contract that renews.
    assert not sent().filter(title__startswith="Contract ends").exists()


def test_a_confirmed_renewal_stops_the_notice_reminders(shop, owner, lease, freeze):
    lease = services.update_contract(lease, by=owner, auto_renews=True)
    services.confirm_renewal(lease, by=owner)
    assert run(shop, freeze, date(2026, 11, 20), 10) == 0
    assert run(shop, freeze, date(2026, 12, 1), 10) == 0


def test_the_buttons_keep_or_stop_the_renewal(shop, owner, manager, lease, freeze):
    lease = services.update_contract(lease, by=owner, auto_renews=True)
    run(shop, freeze, date(2026, 11, 20), 10)
    mine = sent().get(recipient=owner)
    reply = inbox.run_action(mine.pk, "keep", by=owner)
    assert "keeps renewing" in reply
    lease.refresh_from_db()
    assert lease.renewal_confirmed_for == date(2026, 12, 31)
    # A new term asks again; this time the manager gives notice from the bot.
    lease = services.update_contract(lease, by=owner, ends_on=date(2027, 6, 30))
    run(shop, freeze, date(2027, 5, 25), 10)
    theirs = sent().filter(recipient=manager).latest("pk")
    reply = inbox.run_action(theirs.pk, "stop", by=manager)
    assert "ends on 30.06.2027" in reply
    lease.refresh_from_db()
    assert not lease.auto_renews


def test_it_renews_by_itself_and_says_so_the_next_morning(shop, owner, lease, freeze):
    services.update_contract(lease, by=owner, auto_renews=True, renewal_months=12)
    services.confirm_renewal(lease, by=owner)
    # Just after midnight: moved on, but nobody is woken.
    assert run(shop, freeze, date(2027, 1, 1), 0, 30) == 0
    lease.refresh_from_db()
    assert lease.ends_on == date(2027, 12, 31)
    assert lease.status == BusinessContract.Status.ACTIVE
    assert not sent().exists()
    # In the morning: one notice.
    assert run(shop, freeze, date(2027, 1, 1), 9, 30) == 1
    assert sent().get().title == "Renewed by itself: Chilonzor dorixonasi ijarasi (Chilonzor)"
    assert run(shop, freeze, date(2027, 1, 2), 9, 30) == 0


def test_one_companys_trouble_never_stops_the_others(shop, owner, lease, freeze, monkeypatch):
    calls = []

    def broken(company, now):
        calls.append(company.pk)
        raise RuntimeError("boom")

    monkeypatch.setattr(watch, "watch_company", broken)
    assert watch.watch_all(local(date(2026, 12, 1), 10)) == 0
    assert calls == [shop.pk]


# The cockpit and the agenda ---------------------------------------------------------------------


class Ctx:
    def __init__(self, company, today):
        self.company, self.today = company, today


def test_a_lease_ending_within_60_days_is_an_insight(shop, owner, lease, yunusobod):
    services.create_contract(
        shop,
        by=owner,
        kind="supply",
        title="Ko‘kterak",
        starts_on=date(2026, 1, 1),
        ends_on=date(2026, 11, 20),
    )  # not a lease: no insight
    assert providers.lease_ending(Ctx(shop, date(2026, 10, 31))) == []  # 61 days ahead
    assert len(providers.lease_ending(Ctx(shop, date(2026, 11, 1)))) == 1  # 60: within
    found = providers.lease_ending(Ctx(shop, date(2026, 11, 7)))
    assert len(found) == 1
    finding = found[0]
    assert finding.key == f"contracts_lease_ending:{lease.pk}:2026-12-31"
    assert finding.severity == "info"
    assert finding.branch_id == lease.branch_id
    assert finding.metrics["days"] == 54
    words = providers.lease_ending_texts(finding.metrics, "Chilonzor", lease.title)
    assert words.title == "Lease ends in 54 days: Chilonzor dorixonasi ijarasi (Chilonzor)"
    assert "Rustam Qodirov (ijara)" in words.explanation
    assert "a month" in words.explanation
    found = providers.lease_ending(Ctx(shop, date(2026, 12, 15)))
    assert found[0].severity == "warning"


def test_the_insight_engine_stores_it(shop, owner, lease):
    from apps.insights import engine
    from apps.insights.models import Insight

    engine.run(shop, local(date(2026, 12, 10), 7), notify=False)
    insight = Insight.objects.get(company=shop, kind=providers.LEASE_KIND)
    assert insight.title.startswith("Lease ends in 21 days")
    assert insight.domain == "finance"
    assert insight.severity == "warning"


def test_an_auto_renewing_lease_is_an_insight_about_its_decision(shop, owner, lease):
    lease = services.update_contract(lease, by=owner, auto_renews=True, notice_days=30)
    found = providers.lease_ending(Ctx(shop, date(2026, 11, 7)))
    assert found[0].metrics["auto_renews"] is True
    assert found[0].metrics["days"] == 24  # to the notice deadline, 1 December
    words = providers.lease_ending_texts(found[0].metrics, "", lease.title)
    assert words.title == "Lease renewal to decide in 24 days: Chilonzor dorixonasi ijarasi"
    services.confirm_renewal(lease, by=owner)
    assert providers.lease_ending(Ctx(shop, date(2026, 11, 7))) == []


def test_renewals_wait_for_a_decision_on_the_cockpit(shop, owner, manager, lease, freeze):
    lease = services.update_contract(lease, by=owner, auto_renews=True)
    freeze(local(date(2026, 11, 7), 10))
    assert providers.decision_count(owner) == 0  # deadline 1 December, 24 days ahead
    freeze(local(date(2026, 11, 20), 10))
    assert providers.decision_count(owner) == 1
    item = providers.decision_items(owner, 10)[0]
    assert [action.endpoint for action in item.actions] == [
        f"contracts/{lease.pk}/keep-renewing/",
        f"contracts/{lease.pk}/stop-renewing/",
    ]
    assert providers.decision_count(manager) == 1  # Chilonzor is theirs
    # The badge counts it too.
    assert queries.attention_count(owner) == 1


def test_the_agenda_shows_ends_and_notice_deadlines(shop, owner, manager, lease, yunusobod):
    services.create_contract(
        shop,
        by=owner,
        kind="lease",
        title="Yunusobod ijarasi",
        branch=yunusobod,
        starts_on=date(2026, 1, 1),
        ends_on=date(2026, 12, 20),
        auto_renews=True,
        notice_days=30,
    )
    items = providers.calendar_events(shop, date(2026, 11, 1), date(2026, 12, 31), owner)
    assert sorted((item.kind, item.start) for item in items) == [
        ("contracts.end", date(2026, 12, 31)),
        ("contracts.notice", date(2026, 11, 20)),
        ("contracts.renews", date(2026, 12, 20)),
    ]
    # The Chilonzor manager sees only Chilonzor's.
    theirs = providers.calendar_events(shop, date(2026, 11, 1), date(2026, 12, 31), manager)
    assert [item.kind for item in theirs] == ["contracts.end"]


def test_a_renewal_to_decide_is_in_needs_you_and_its_notice_only_in_telegram(
    shop, owner, lease, freeze
):
    from apps.console import registry

    lease = services.update_contract(lease, by=owner, auto_renews=True)
    run(shop, freeze, date(2026, 11, 20), 10)
    row = sent().get(recipient=owner)
    assert row.kind == notify.NOTICE_KIND
    assert row.in_app is False  # the queue item is its in-app form
    items = registry.queue_items(owner, kind="contracts.renewals")
    assert [item.id for item in items] == [lease.pk]
    assert [action.key for action in items[0].actions] == ["keep", "stop"]
    assert (
        dict((source.key, count) for source, count in registry.queue_counts(owner))[
            "contracts.renewals"
        ]
        == 1
    )
