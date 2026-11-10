"""The registry of decision sources: queue-backed sources keep their queue's rules, a source of
its own brings its items (how hiring plugs in), and registration rules hold."""

import pytest
from django.utils import timezone

from apps.console.registry import QueueAction, QueueItem, RegistryError
from apps.insights import decisions

pytestmark = pytest.mark.django_db


def test_the_built_in_sources_are_registered():
    keys = [source.key for source in decisions.SOURCES]
    assert keys[:9] == [
        "members.join",
        "lifecycle.resignations",
        "lifecycle.job_changes",
        "finance.claims",
        "timeoff.request",
        "attendance.overtime",
        "payroll.advances",
        "payroll.adjustments",
        "inventory.writeoffs_to_approve",
    ]
    # Each is a "Needs you" queue that exists.
    from apps.console import registry

    assert all(registry.QUEUE.get(key) is not None for key in keys)


def test_a_source_of_its_own(shop, owner, isolated_registries):
    asked = timezone.now()

    def items(member, limit):
        return [
            QueueItem(
                kind="insights.hire",
                id=7,
                title="Hire Laylo as a pharmacist",
                subtitle="Chilonzor",
                created_at=asked,
                url="hr/hiring?applicant=7",
                actions=(
                    QueueAction("approve", "Hire", "primary", "POST", "hr/applicants/7/hire/"),
                    QueueAction("reject", "Decline", "danger", "POST", "hr/applicants/7/decline/"),
                ),
            ),
            QueueItem(
                kind="insights.hire",
                id=8,
                title="Read only",
                subtitle="",
                created_at=asked,
                url="",
                actions=(),
            ),
        ]

    decisions.register_source(
        "insights.hire", group="hire", order=15, label="Applicants", count=lambda m: 2, items=items
    )
    data = decisions.collect(owner)
    source = next(s for s in data["sources"] if s["key"] == "insights.hire")
    assert source == {"key": "insights.hire", "group": "hire", "label": "Applicants", "count": 2}
    hires = [item for item in data["items"] if item["source"] == "insights.hire"]
    assert [item["title"] for item in hires] == ["Hire Laylo as a pharmacist"]  # no buttons: out
    assert hires[0]["actions"][0]["endpoint"] == "hr/applicants/7/hire/"


def test_a_source_by_queue_kind_uses_that_queue(shop, owner, isolated_registries):
    from apps.console import registry

    registry.register_queue(
        "insights.queue_test",
        perm=None,
        label="Test queue",
        count=lambda member: 1,
        items=lambda member, limit: [
            QueueItem(
                "insights.queue_test",
                1,
                "Approve the discount",
                "",
                timezone.now(),
                "",
                (QueueAction("approve", "Approve", "primary", "POST", "x/1/approve/"),),
            )
        ],
    )
    decisions.register_source("insights.queue_test", group="discount", order=1)
    data = decisions.collect(owner)
    assert data["sources"][0] == {
        "key": "insights.queue_test",
        "group": "discount",
        "label": "Test queue",
        "count": 1,
    }
    assert data["items"][0]["title"] == "Approve the discount"


def test_a_missing_queue_is_left_out(shop, owner, isolated_registries):
    decisions.register_source("nowhere.queue", group="other")
    assert "nowhere.queue" not in [s["key"] for s in decisions.collect(owner)["sources"]]


def test_a_failing_source_never_breaks_the_cockpit(shop, owner, isolated_registries):
    def broken(member, *args):
        raise RuntimeError("boom")

    decisions.register_source(
        "insights.broken", group="other", label="Broken", count=broken, items=broken
    )
    data = decisions.collect(owner)
    assert next(s for s in data["sources"] if s["key"] == "insights.broken")["count"] == 0


def test_registration_rules(isolated_registries):
    with pytest.raises(RegistryError):
        decisions.register_source("members.join", group="people")  # twice
    with pytest.raises(RegistryError):
        decisions.register_source("insights.x", group="nonsense")
    with pytest.raises(RegistryError):
        decisions.register_source("insights.x", group="hire", items=lambda m, n: [])
    with pytest.raises(RegistryError):
        decisions.register_source(
            "insights.x", group="hire", count=lambda m: 0, items=lambda m, n: []
        )  # its own items need a label
    with pytest.raises(RegistryError):
        decisions.register_source(
            "finance.mine", group="hire", label="x", count=lambda m: 0, items=lambda m, n: []
        )  # its own items: the key starts with the registering app's label
