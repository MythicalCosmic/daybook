"""The registries modules plug into: rules at registration, and how the console runs them."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.apps import apps as django_apps
from django.utils import timezone

from apps.console import registry
from apps.console.perms import AllOf, AnyOf
from apps.console.ranges import Range
from apps.console.registry import (
    BadKey,
    CalendarItem,
    DuplicateKey,
    FieldSpec,
    OffboardStep,
    QueueAction,
    QueueItem,
    SearchHit,
    StreamItem,
)
from apps.members.permissions import Perm

pytestmark = pytest.mark.usefixtures("isolated_registries")

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


def at(minutes: int) -> datetime:
    return NOW + timedelta(minutes=minutes)


# Every registry, every app: the rule-14 test ---------------------------------------------


def test_every_registered_key_carries_its_apps_label():
    labels = {config.label for config in django_apps.get_app_configs()}
    for each in registry.REGISTRIES:
        for entry in each:
            assert entry.app in labels, f"{each.name}: {entry.key!r} has no app"
            assert registry.key_belongs_to(entry.key, entry.app), (
                f"{each.name}: {entry.key!r} doesn't start with {entry.app!r}"
            )


def test_every_registry_is_listed():
    names = {each.name for each in registry.REGISTRIES}

    assert {
        "search",
        "queue",
        "pulse",
        "stream",
        "branch facts",
        "brief sections",
        "person fields",
        "offboard steps",
        "setup steps",
        "company facts",
        "copy parts",
        "calendar sources",
        "inbox kinds",
        "inbox actions",
        "exporters",
    } <= names


def noop(*args):
    return []


REGISTRATIONS = {
    "search": lambda key: registry.register_search(key, perm=None, search=noop),
    "queue": lambda key: registry.register_queue(
        key, perm=None, label="Q", count=lambda m: 0, items=noop
    ),
    "pulse": lambda key: registry.register_pulse(key, perm=None, count=None),
    "stream": lambda key: registry.register_stream(key, perm=None, fetch=noop),
    "brief": lambda key: registry.register_brief_section(key, perm=None, order=1, build=noop),
    "person": lambda key: registry.register_person_fields(key, perm=None, fetch=noop),
    "offboard": lambda key: registry.register_offboard_step(
        key, perm=None, order=1, label="L", preview=noop
    ),
    "setup": lambda key: registry.register_setup_step(
        key, perm=None, order=1, label="L", description="D", url="/", done=noop
    ),
    "copy": lambda key: registry.register_copy_part(key, label="L", perm=None, copy=noop),
    "calendar": lambda key: registry.register_calendar_source(
        key, label="L", perm=None, events=noop
    ),
}


@pytest.mark.parametrize("name", REGISTRATIONS)
def test_registering_a_key_twice_raises(name):
    register = REGISTRATIONS[name]
    register(f"console.test_{name}")

    with pytest.raises(DuplicateKey, match=r"already registered by apps\.console"):
        register(f"console.test_{name}")


@pytest.mark.parametrize("name", REGISTRATIONS)
def test_a_key_must_start_with_the_registering_apps_label(name):
    with pytest.raises(BadKey, match="must start with its app's label 'console'"):
        REGISTRATIONS[name](f"sales.test_{name}")


@pytest.mark.parametrize("key", ["", "Console.x", "console x", "console..x", "console.x-y", 7])
def test_a_key_must_be_lowercase_and_dotted(key):
    with pytest.raises(BadKey):
        registry.register_pulse(key, perm=None, count=None)


def test_the_bare_label_is_a_valid_key():
    registry.register_brief_section("console", perm=None, order=1, build=noop)

    assert "console" in registry.BRIEF_SECTIONS


def test_branch_and_company_facts_take_only_the_fixed_keys():
    with pytest.raises(BadKey, match="fixed keys"):
        registry.register_branch_facts("console", perm=None, facts=noop)
    with pytest.raises(BadKey, match="fixed keys"):
        registry.register_company_facts("console", perm=None, facts=noop)


def test_fixed_keys_still_need_their_own_app():
    with pytest.raises(BadKey, match="must start with its app's label"):
        registry.register_branch_facts("sales", perm=None, facts=noop)


# Permissions and module switches ------------------------------------------------------


def entry(registry_obj, key, *, perm=None, feature=None, app="console", **fields):
    """Add an entry as if `apps.<app>` registered it (fixed keys need their own app)."""
    kinds = {
        registry.SEARCH: registry.SearchProvider,
        registry.QUEUE: registry.QueueSource,
        registry.STREAM: registry.StreamSource,
        registry.BRANCH_FACTS: registry.BranchFactsProvider,
        registry.BRIEF_SECTIONS: registry.BriefSection,
        registry.PERSON_FIELDS: registry.PersonFieldsProvider,
        registry.OFFBOARD_STEPS: registry.OffboardStepProvider,
        registry.SETUP_STEPS: registry.SetupStep,
        registry.COMPANY_FACTS: registry.CompanyFactsProvider,
        registry.COPY_PARTS: registry.CopyPart,
        registry.CALENDAR_SOURCES: registry.CalendarSource,
        registry.PULSE: registry.PulseCounter,
    }
    return registry_obj.add(kinds[registry_obj](key, app, perm, feature, **fields))


@pytest.mark.django_db
def test_entries_need_their_permission(company, member):
    manager = member(company, "Manager")
    entry(registry.PULSE, "console.salaries", perm=Perm.PAYROLL_VIEW, count=lambda m: 1)
    entry(registry.PULSE, "console.team", perm=Perm.MEMBERS_VIEW, count=lambda m: 2)

    counts = registry.pulse_counts(manager)

    assert counts["console.team"] == 2
    assert "console.salaries" not in counts


@pytest.mark.django_db
def test_any_of_and_all_of(company, member):
    manager = member(company, "Manager")  # sales.view, stock.manage; no finance.view
    entry(
        registry.PULSE,
        "console.stock",
        perm=AnyOf(Perm.FINANCE_VIEW, Perm.STOCK_MANAGE),
        count=None,
    )
    entry(
        registry.PULSE, "console.both", perm=AllOf(Perm.SALES_VIEW, Perm.FINANCE_VIEW), count=None
    )
    entry(registry.PULSE, "console.pair", perm=(Perm.SALES_VIEW, Perm.STOCK_MANAGE), count=None)

    visible = {item.key for item in registry.PULSE.visible_to(manager)}

    assert {"console.stock", "console.pair"} <= visible
    assert "console.both" not in visible


@pytest.mark.django_db
def test_entries_of_a_switched_off_module_are_hidden(company, member):
    owner = member(company, "Owner")
    entry(registry.PULSE, "console.sales", feature="sales", count=lambda m: 5)

    assert "console.sales" not in registry.pulse_counts(owner)
    company.features = ["sales"]
    company.save()
    owner.company.refresh_from_db()
    assert registry.pulse_counts(owner)["console.sales"] == 5


@pytest.mark.django_db
def test_a_failing_provider_is_left_out_and_logged(company, member, caplog):
    owner = member(company, "Owner")

    def broken(member):
        raise RuntimeError("boom")

    entry(registry.PULSE, "console.broken", count=broken)
    entry(registry.PULSE, "console.fine", count=lambda m: 3)

    counts = registry.pulse_counts(owner)

    assert counts["console.broken"] == 0
    assert counts["console.fine"] == 3
    assert "pulse provider 'console.broken' failed" in caplog.text


# Shapes ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint",
    ["/api/v1/x/", "https://evil.example/approve/", "time-off/../../x/", "", "time-off/42/approve"],
)
def test_queue_action_endpoints_are_relative_to_the_company(endpoint):
    with pytest.raises(ValueError, match="relative"):
        QueueAction("approve", "Approve", "primary", "POST", endpoint)


def test_queue_action_method_and_style_are_checked():
    with pytest.raises(ValueError):
        QueueAction("approve", "Approve", "primary", "GET", "time-off/42/approve/")
    with pytest.raises(ValueError):
        QueueAction("approve", "Approve", "loud", "POST", "time-off/42/approve/")


def test_shapes_turn_into_json():
    item = QueueItem(
        "console.things",
        42,
        "Title",
        "Sub",
        NOW,
        "/c/1/things/42",
        [QueueAction("approve", "Approve", "primary", "POST", "things/42/approve/")],
    )

    assert registry.to_json(item) == {
        "kind": "console.things",
        "id": 42,
        "title": "Title",
        "subtitle": "Sub",
        "created_at": "2026-10-20T09:00:00+00:00",
        "url": "/c/1/things/42",
        "actions": [
            {
                "key": "approve",
                "label": "Approve",
                "style": "primary",
                "method": "POST",
                "endpoint": "things/42/approve/",
                "body": {},
                "needs_reason": False,
            }
        ],
    }


def test_money_in_shapes_stays_a_string():
    action = QueueAction(
        "pay", "Pay", "primary", "POST", "things/1/pay/", body={"amount": Decimal("450000.00")}
    )

    assert registry.to_json(action)["body"] == {"amount": "450000.00"}


def test_field_spec_kinds_are_checked():
    with pytest.raises(ValueError):
        FieldSpec("note", "Note", kind="html")


# Running each registry ------------------------------------------------------------------


@pytest.mark.django_db
def test_search_caps_each_type_and_filters_types(company, member):
    owner = member(company, "Owner")

    def many(member, q, limit):
        return [SearchHit("console.a", n, f"{q} {n}", "", f"/a/{n}") for n in range(10)]

    entry(registry.SEARCH, "console.a", search=many)
    entry(
        registry.SEARCH,
        "console.b",
        search=lambda m, q, limit: [SearchHit("console.b", 1, q, "", "")],
    )

    assert len(registry.run_search(owner, "milk", limit=5)) == 6
    assert {hit.type for hit in registry.run_search(owner, "milk", types=["console.b"])} == {
        "console.b"
    }


@pytest.mark.django_db
def test_queue_items_come_oldest_first(company, member):
    owner = member(company, "Owner")
    entry(
        registry.QUEUE,
        "console.a",
        label="A",
        count=lambda m: 2,
        items=lambda m, limit: [
            QueueItem("console.a", 1, "late", "", at(30), "", []),
            QueueItem("console.a", 2, "undated", "", None, "", []),
        ],
    )
    entry(
        registry.QUEUE,
        "console.b",
        label="B",
        count=lambda m: 1,
        items=lambda m, limit: [QueueItem("console.b", 3, "early", "", at(0), "", [])],
    )

    assert [item.title for item in registry.queue_items(owner)] == ["early", "late", "undated"]
    assert [item.id for item in registry.queue_items(owner, kind="console.b")] == [3]
    assert registry.queue_total(owner) == 3


@pytest.mark.django_db
def test_stream_merges_sources_newest_first_and_honours_since(company, member):
    owner = member(company, "Owner")
    entry(
        registry.STREAM,
        "console.a",
        fetch=lambda m, since, limit: [StreamItem(at(1), "console.a", None, "one", "")],
    )
    entry(
        registry.STREAM,
        "console.b",
        fetch=lambda m, since, limit: [
            StreamItem(at(3), "console.b", {"id": 1, "name": "Ali"}, "three", ""),
            StreamItem(at(2), "console.b", None, "two", ""),
        ],
    )

    assert [i.title for i in registry.run_stream(owner)] == ["three", "two", "one"]
    assert [i.title for i in registry.run_stream(owner, since=at(1))] == ["three", "two"]
    assert [i.title for i in registry.run_stream(owner, limit=1)] == ["three"]


@pytest.mark.django_db
def test_branch_facts_that_dont_fit_their_shape_are_dropped(company, member, caplog):
    owner = member(company, "Owner")
    registry.BRANCH_FACTS._entries.pop("tasks", None)  # apps.tasks' real provider
    entry(
        registry.BRANCH_FACTS,
        "tasks",
        app="tasks",
        facts=lambda c, day, now, ids: {i: {"done": 1, "total": 2, "late": 0} for i in ids},
    )
    entry(
        registry.BRANCH_FACTS,
        "finance",
        app="finance",
        facts=lambda c, day, now, ids: {i: {"cash": 100} for i in ids},  # money must be a string
    )

    facts = registry.collect_branch_facts(owner, date(2026, 10, 20), NOW, [7])

    assert facts == {"tasks": {7: {"done": 1, "total": 2, "late": 0}}}
    assert "don't fit FinanceFacts" in caplog.text


@pytest.mark.django_db
def test_brief_sections_run_in_order_and_silent_ones_drop_out(company, member):
    manager = member(company, "Manager")
    entry(registry.BRIEF_SECTIONS, "console.b", order=2, build=lambda c, d, n, b: {"b": 1})
    entry(registry.BRIEF_SECTIONS, "console.a", order=1, build=lambda c, d, n, b: {"a": b})
    entry(registry.BRIEF_SECTIONS, "console.quiet", order=0, build=lambda c, d, n, b: None)
    entry(
        registry.BRIEF_SECTIONS,
        "console.secret",
        order=0,
        perm=Perm.PAYROLL_VIEW,
        build=lambda c, d, n, b: {"x": 1},
    )

    sections = registry.collect_brief_sections(manager, date(2026, 10, 20), NOW, branch_ids=[3])

    assert sections == [("console.a", {"a": [3]}), ("console.b", {"b": 1})]


@pytest.mark.django_db
def test_person_fields_merge_and_hide_what_the_viewer_may_not_see(company, member):
    owner, manager, worker = (member(company, r) for r in ("Owner", "Manager", "Employee"))
    salary = {"amount": "5200000.00", "currency": "UZS", "pay_type": "monthly"}
    entry(
        registry.PERSON_FIELDS,
        "payroll",
        app="payroll",
        perm=Perm.PAYROLL_VIEW,
        fetch=lambda c, ids, now: {i: {"salary": salary} for i in ids},
    )
    entry(
        registry.PERSON_FIELDS,
        "attendance",
        app="attendance",
        perm=Perm.ATTENDANCE_VIEW,
        fetch=lambda c, ids, now: {
            i: {"attendance_today": "in", "attendance_30d": "93.5"} for i in ids
        },
    )

    as_owner = registry.collect_person_fields(owner, [worker.pk], NOW)
    as_manager = registry.collect_person_fields(manager, [worker.pk], NOW)

    assert as_owner == {
        worker.pk: {"salary": salary, "attendance_today": "in", "attendance_30d": "93.5"}
    }
    assert as_manager == {worker.pk: {"attendance_today": "in", "attendance_30d": "93.5"}}


@pytest.mark.django_db
def test_person_fields_with_the_wrong_shape_are_dropped(company, member):
    owner, worker = member(company, "Owner"), member(company)
    entry(
        registry.PERSON_FIELDS,
        "payroll",
        app="payroll",
        fetch=lambda c, ids, now: {i: {"salary": 5200000} for i in ids},
    )

    assert registry.collect_person_fields(owner, [worker.pk], NOW) == {worker.pk: {}}


@pytest.mark.django_db
def test_offboard_steps_preview_in_order(company, member):
    owner, worker = member(company, "Owner"), member(company)
    entry(
        registry.OFFBOARD_STEPS,
        "console.money",
        order=2,
        label="Money",
        preview=lambda m: OffboardStep(["Holds 50 000"], ["Close the till"], [], {}),
    )
    entry(
        registry.OFFBOARD_STEPS,
        "console.contract",
        order=1,
        label="Contract",
        preview=lambda m: OffboardStep([], [], [FieldSpec("reason", "Reason", "textarea")], {}),
    )

    steps = registry.collect_offboard_steps(worker, by=owner)

    assert [step["key"] for step in steps] == ["console.contract", "console.money"]
    assert steps[1]["blockers"] == ["Close the till"]
    assert steps[0]["fields"][0] == {
        "name": "reason",
        "label": "Reason",
        "kind": "textarea",
        "required": False,
        "choices": [],
        "help": "",
    }


@pytest.mark.django_db
def test_setup_steps_report_done(company, member):
    owner = member(company, "Owner")
    entry(
        registry.SETUP_STEPS,
        "console.branches",
        order=1,
        label="Add branches",
        description="Where you work",
        url="/settings/branches",
        done=lambda c: True,
    )
    entry(
        registry.SETUP_STEPS,
        "console.sales",
        order=2,
        label="Registers",
        description="",
        url="/sales",
        done=lambda c: False,
        feature="sales",
    )

    assert registry.collect_setup_steps(owner) == [
        {
            "key": "console.branches",
            "label": "Add branches",
            "description": "Where you work",
            "url": "/settings/branches",
            "order": 1,
            "done": True,
        }
    ]


@pytest.mark.django_db
def test_company_facts_check_their_shape(company, member):
    owner = member(company, "Owner")
    registry.COMPANY_FACTS._entries.pop("tasks", None)  # apps.tasks' real provider
    entry(
        registry.COMPANY_FACTS,
        "tasks",
        app="tasks",
        facts=lambda c, r, m: {"done": 3, "total": 4, "late": 1},
    )
    entry(registry.COMPANY_FACTS, "sales", app="sales", facts=lambda c, r, m: {"net": "1.00"})
    span = Range(date(2026, 10, 1), date(2026, 10, 20))

    facts = registry.collect_company_facts(owner, span)

    assert facts["tasks"] == {"done": 3, "total": 4, "late": 1}
    assert "sales" not in facts  # prev_net missing
    assert facts["inbox"] == {"waiting": 0}  # registered by apps.inbox


@pytest.fixture
def copied(isolated_registries):
    calls = []
    entry(
        registry.COPY_PARTS,
        "console.roles",
        label="Roles",
        perm=Perm.ROLES_MANAGE,
        copy=lambda source, target, by: calls.append((source, target)) or 3,
    )
    return calls


@pytest.mark.django_db
def test_copy_parts_run_only_with_permission(company, other_company, member, copied):
    owner, manager = member(company, "Owner"), member(company, "Manager")
    member(other_company, "Owner", user=owner.user)
    member(other_company, "Manager", user=manager.user)

    assert registry.run_copy(other_company, company, ["console.roles"], by=owner) == {
        "console.roles": 3
    }
    assert copied == [(other_company, company)]
    with pytest.raises(registry.RegistryError):
        registry.run_copy(other_company, company, ["console.roles"], by=manager)
    with pytest.raises(registry.RegistryError):
        registry.run_copy(other_company, company, ["console.nothing"], by=owner)


@pytest.mark.django_db
def test_nobody_copies_from_a_company_they_cant_see(company, other_company, member, copied):
    owner = member(company, "Owner")

    with pytest.raises(registry.RegistryError):
        registry.run_copy(other_company, company, ["console.roles"], by=owner)
    # A member there, but not one who may open its dashboard or manage its roles:
    member(other_company, "Employee", user=owner.user)
    with pytest.raises(registry.RegistryError):
        registry.run_copy(other_company, company, ["console.roles"], by=owner)
    assert copied == []


@pytest.mark.django_db
def test_copying_needs_the_permission_in_the_source_too(company, other_company, member, copied):
    owner = member(company, "Owner")
    member(other_company, "Manager", user=owner.user)  # dashboard access, no roles.manage

    with pytest.raises(registry.RegistryError):
        registry.run_copy(other_company, company, ["console.roles"], by=owner)
    assert copied == []


@pytest.mark.django_db
def test_copying_goes_into_the_members_own_company(company, other_company, member, copied):
    owner = member(company, "Owner")
    member(other_company, "Owner", user=owner.user)

    with pytest.raises(registry.RegistryError):
        registry.run_copy(company, other_company, ["console.roles"], by=owner)
    with pytest.raises(registry.RegistryError):
        registry.run_copy(company, company, ["console.roles"], by=owner)
    assert copied == []


@pytest.mark.django_db
def test_calendar_items_from_every_source_in_date_order(company, member):
    owner = member(company, "Owner")
    entry(
        registry.CALENDAR_SOURCES,
        "console.holidays",
        label="Holidays",
        events=lambda c, s, e, m: [
            CalendarItem("h1", "holiday", "Independence Day", date(2026, 9, 1), None, True, "", "")
        ],
    )
    entry(
        registry.CALENDAR_SOURCES,
        "console.meetings",
        label="Meetings",
        events=lambda c, s, e, m: [
            CalendarItem(
                1,
                "event",
                "Stock take",
                timezone.make_aware(datetime(2026, 8, 31, 18)),
                None,
                False,
                "blue",
                "/agenda/1",
            )
        ],
    )

    items = registry.collect_calendar(owner, date(2026, 8, 1), date(2026, 9, 30))

    assert [item.title for item in items] == ["Stock take", "Independence Day"]
    assert (
        registry.collect_calendar(
            owner, date(2026, 8, 1), date(2026, 9, 30), sources=["console.holidays"]
        )[0].kind
        == "holiday"
    )
