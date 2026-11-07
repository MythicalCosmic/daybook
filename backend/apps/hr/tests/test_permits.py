"""Licences and permits as HR reads them (docs/PLAN-OWNER.md §14.9, Should): `hr.queries.permits`,
a thin read of `apps.assets.Permit` for the inspection pack, and the cross-check of a branch
licensed for controlled substances against the licence on file (in the brief, the coverage
page and the AI tool). Nothing in apps.assets is written by HR."""

from datetime import timedelta

import pytest

from apps.ai.tools.testing import call_tool
from apps.assets.models import Permit
from apps.hr import providers, queries
from apps.hr.tests.conftest import DAY, local

pytestmark = pytest.mark.django_db


@pytest.fixture
def licensed(shop, staff, yunusobod):
    shop.features = [*shop.features, "assets"]
    shop.save()
    yunusobod.controlled_licence = True
    yunusobod.save()
    return staff


def permit(company, branch, kind="controlled_licence", until=None, **extra):
    return Permit.objects.create(
        company=company,
        branch=branch,
        kind=kind,
        name=extra.pop("name", kind),
        valid_until=until,
        **extra,
    )


def test_the_permits_in_force_in_scope(shop, licensed, chilonzor, yunusobod):
    licence = permit(shop, None, "pharmacy_licence", DAY + timedelta(days=400))
    lease = permit(shop, chilonzor, "lease", DAY + timedelta(days=30))
    permit(shop, chilonzor, "fire_safety", DAY - timedelta(days=1))  # ended yesterday
    controlled = permit(shop, yunusobod, "controlled_licence", None)

    assert list(queries.permits(shop, branch_ids=None)) == [lease, licence, controlled]
    assert list(queries.permits(shop, branch_ids=[chilonzor.pk])) == [lease]
    assert list(queries.permits(shop, branch_ids=None, kinds=["controlled_licence"])) == [
        controlled
    ]
    assert queries.permits(shop, branch_ids=[chilonzor.pk], active=False).count() == 2
    assert list(queries.permits(shop, branch_ids=[])) == []


def test_a_branch_licensed_for_controlled_substances_needs_the_licence_on_file(
    shop, licensed, yunusobod
):
    warnings = queries.permit_warnings(shop, branch_ids=None, day=DAY)
    assert [(row["branch"].name, row["problem"], row["valid_until"]) for row in warnings] == [
        ("Yunusobod", "missing", None)
    ]

    old = permit(shop, yunusobod, until=DAY - timedelta(days=3))
    warnings = queries.permit_warnings(shop, branch_ids=None, day=DAY)
    assert [(row["problem"], row["valid_until"]) for row in warnings] == [
        ("expired", DAY - timedelta(days=3))
    ]

    old.valid_until = DAY + timedelta(days=300)
    old.save()
    assert queries.permit_warnings(shop, branch_ids=None, day=DAY) == []


def test_a_licence_of_the_whole_company_counts_and_scope_applies(
    shop, licensed, chilonzor, yunusobod
):
    assert queries.permit_warnings(shop, branch_ids=[chilonzor.pk], day=DAY) == []
    permit(shop, None, until=None)
    assert queries.permit_warnings(shop, branch_ids=None, day=DAY) == []


def test_nothing_without_the_assets_module_or_the_flag(shop, staff, yunusobod):
    yunusobod.controlled_licence = True
    yunusobod.save()
    assert queries.permit_warnings(shop, branch_ids=None, day=DAY) == []  # assets is off
    shop.features = [*shop.features, "assets"]
    shop.save()
    yunusobod.controlled_licence = False
    yunusobod.save()
    assert queries.permit_warnings(shop, branch_ids=None, day=DAY) == []


def test_the_brief_says_so_even_before_coverage_is_set_up(shop, licensed, yunusobod):
    section = providers.coverage_brief(shop, DAY, local(DAY, 9), None)
    assert section == {
        "title": "Pharmacist coverage",
        "lines": ["Controlled substances licence not on file: Yunusobod"],
    }
    permit(shop, yunusobod, until=DAY - timedelta(days=3))
    assert providers.coverage_brief(shop, DAY, local(DAY, 9), None)["lines"] == [
        "Controlled substances licence ended on 18.10.2026: Yunusobod"
    ]


def test_the_coverage_page_and_the_ai_tool_show_it(shop, licensed, owner_api, yunusobod):
    body = owner_api(licensed.owner).get(f"/api/v1/owner/companies/{shop.pk}/hr/coverage/").json()
    assert [(row["branch"]["name"], row["problem"]) for row in body["permits"]] == [
        ("Yunusobod", "missing")
    ]
    lead = owner_api(licensed.lead).get(f"/api/v1/owner/companies/{shop.pk}/hr/coverage/").json()
    assert lead["permits"] == []  # Chilonzor only

    result = call_tool("hr_coverage", licensed.owner, days=1, _now=local(DAY, 10))
    assert [row["type"] for row in result["rows"]] == ["controlled_licence_missing"]
