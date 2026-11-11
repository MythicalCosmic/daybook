"""The contracts register export and the AI tool: branch scope, what they leave out."""

from datetime import date
from decimal import Decimal

import pytest

from apps.contracts import providers, services
from apps.contracts.tests.conftest import local

pytestmark = pytest.mark.django_db


@pytest.fixture
def far(shop, owner, yunusobod):
    return services.create_contract(
        shop,
        by=owner,
        kind="lease",
        title="Yunusobod ijarasi",
        branch=yunusobod,
        starts_on=date(2026, 1, 1),
        ends_on=date(2026, 12, 21),
        amount=Decimal(1400),
        currency="USD",
    )


def test_the_register_export_follows_the_branch_scope(shop, owner, manager, lease, far):
    rows = list(providers.register_rows(owner, {}))
    assert [row["title"] for row in rows] == ["Yunusobod ijarasi", "Chilonzor dorixonasi ijarasi"]
    assert rows[1]["counterparty"] == "Rustam Qodirov (ijara)"
    assert rows[1]["per_month"] == Decimal("9000000.00")
    assert rows[1]["kind"] == "Lease" and rows[1]["status"] == "Active"
    keys = {column[0] for column in providers.REGISTER_COLUMNS}
    assert set(rows[0]) == keys
    # The Chilonzor manager exports Chilonzor's only.
    assert [row["title"] for row in providers.register_rows(manager, {})] == [
        "Chilonzor dorixonasi ijarasi"
    ]


def test_the_exporter_is_registered():
    from apps.exports.registry import EXPORTERS

    exporter = EXPORTERS.get("contracts.register")
    assert exporter is not None and exporter.app == "contracts"


def test_the_ai_tool_answers_in_scope_without_files_or_notes(shop, owner, manager, lease, far):
    from apps.ai.tools import registry
    from apps.ai.tools.registry import ToolContext
    from apps.contracts.ai_tools import ContractsOverviewInput, contracts_overview

    def run(member, **args):
        ctx = ToolContext.for_member(member, now=local(date(2026, 11, 7), 10))
        return contracts_overview(ctx, ContractsOverviewInput(**args))

    result = run(owner)
    assert {row["title"] for row in result.rows} == {lease.title, far.title}
    assert result.data["in_force"] == 2
    assert all("notes" not in row and "url" not in row for row in result.rows)
    assert {row["title"] for row in run(manager).rows} == {lease.title}
    assert [row["title"] for row in run(owner, kind="supply").rows] == []
    registry.autodiscover()
    assert registry.get_tool("contracts_overview").perm == "finance.view"


def test_the_briefing_names_what_ends_and_what_to_decide(shop, owner, lease, far):
    assert providers.brief_section(shop, date(2026, 10, 1), None, None) is None
    services.update_contract(lease, by=owner, auto_renews=True)
    section = providers.brief_section(shop, date(2026, 11, 25), None, None)
    assert section["title"] == "Contracts"
    assert section["lines"] == [
        "Chilonzor dorixonasi ijarasi (Chilonzor): notice deadline 01.12.2026",
        "Yunusobod ijarasi (Yunusobod) ends 21.12.2026",
    ]
    # Only what the branch scope allows.
    assert providers.brief_section(shop, date(2026, 11, 25), None, [far.branch_id])["lines"] == [
        "Yunusobod ijarasi (Yunusobod) ends 21.12.2026"
    ]


def test_get_started_is_done_once_a_contract_exists(shop, owner):
    assert not providers.setup_done(shop)
    services.create_contract(
        shop, by=owner, kind="lease", title="Ijara", starts_on=date(2026, 1, 1)
    )
    assert providers.setup_done(shop)
