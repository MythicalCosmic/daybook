"""Live badges: version counters in the Django cache and per-member counters."""

import pytest
from django.core.cache import cache

from apps.console import pulse, registry
from apps.members.permissions import Perm

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("isolated_registries")]


@pytest.fixture(autouse=True)
def empty_cache():
    cache.clear()


def pulse_url(company) -> str:
    return f"/api/v1/owner/companies/{company.pk}/pulse/"


def test_bump_moves_the_version_on(company):
    registry.register_pulse("console.things", perm=None, count=None)

    assert pulse.versions(company.pk, ["console.things"]) == {"console.things": "0"}
    pulse.bump(company.pk, "console.things")
    pulse.bump(company.pk, "console.things")
    assert pulse.versions(company.pk, ["console.things"]) == {"console.things": "2"}


def test_versions_are_per_company(company, other_company):
    registry.register_pulse("console.things", perm=None, count=None)

    pulse.bump(company.pk, "console.things")

    assert pulse.versions(other_company.pk, ["console.things"]) == {"console.things": "0"}


def test_bumping_an_unregistered_key_warns(company, caplog):
    pulse.bump(company.pk, "console.typo")

    assert "not a registered pulse key" in caplog.text


def test_cache_keys_carry_the_run_prefix(settings):
    assert settings.CACHES["default"]["KEY_PREFIX"].startswith("t:")
    assert pulse.version_key(3, "sales.shifts") == "pulse:3:sales.shifts"


def test_pulse_endpoint_filters_counters_and_versions_by_permission(company, member, owner_api):
    registry.register_pulse("console.reviews", perm=Perm.TASKS_CONFIRM, count=lambda m: 4)
    registry.register_pulse("console.payroll", perm=Perm.PAYROLL_VIEW, count=lambda m: 9)
    registry.register_pulse("console.payroll_runs", perm=Perm.PAYROLL_VIEW, count=None)
    pulse.bump(company.pk, "console.payroll_runs")
    manager = member(company, "Manager")

    response = owner_api(manager).get(pulse_url(company))

    assert response.status_code == 200
    assert response.data["counters"]["console.reviews"] == 4
    assert "console.payroll" not in response.data["counters"]
    assert "console.payroll_runs" not in response.data["versions"]
    assert response.data["versions"]["console.reviews"] == "0"


def test_counters_are_cached_for_ten_seconds_per_member(company, member, owner_api):
    calls = []
    registry.register_pulse(
        "console.slow", perm=None, count=lambda m: calls.append(m.pk) or len(calls)
    )
    owner, manager = member(company, "Owner"), member(company, "Manager")

    first = owner_api(owner).get(pulse_url(company)).data["counters"]["console.slow"]
    again = owner_api(owner).get(pulse_url(company)).data["counters"]["console.slow"]
    other = owner_api(manager).get(pulse_url(company)).data["counters"]["console.slow"]

    assert (first, again, other) == (1, 1, 2)
    assert pulse.COUNTERS_TTL == 10


def test_the_needs_you_badge_counts_every_queue(company, member, owner_api):
    registry.register_queue(
        "console.a", perm=None, label="A", count=lambda m: 2, items=lambda m, limit: []
    )
    registry.register_queue(
        "console.b", perm=Perm.PAYROLL_VIEW, label="B", count=lambda m: 5, items=lambda m, limit: []
    )

    owner_counts = owner_api(member(company, "Owner")).get(pulse_url(company)).data["counters"]
    manager_counts = owner_api(member(company, "Manager")).get(pulse_url(company)).data["counters"]

    assert owner_counts["console.queue"] == 7
    assert manager_counts["console.queue"] == 2


def test_pulse_needs_dashboard_access_in_that_company(company, other_company, member, owner_api):
    employee = member(company)
    owner = member(other_company, "Owner")

    assert owner_api(employee).get(pulse_url(company)).status_code == 403
    assert owner_api(owner).get(pulse_url(company)).status_code == 404
