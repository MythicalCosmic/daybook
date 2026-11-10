"""The equipment story of Demo Dorixona: the pharmacy's categories, coats and badges for the staff,
the cash-box keys with the heads, a phone and a scanner, photos on every hand-out, one coat still
to confirm, Sardor's worn coat swapped, Dilshod's lost badge with a deduction, and Jasur's two
things to hand back before he leaves."""

import pytest
from django.utils import timezone

from apps.assets import demo as assets_demo
from apps.assets.models import Asset, AssetAssignment, AssetCategory
from apps.companies.models import Feature
from apps.core.management.commands.ensure_company_defaults import ensure_company_defaults
from apps.core.management.commands.seed_demo import Command
from apps.hr.tests.conftest import DAY, local
from apps.lifecycle import demo
from apps.lifecycle.equipment import queries
from apps.lifecycle.models import Termination
from apps.members import demo as members_demo
from apps.members.models import Membership

pytestmark = pytest.mark.django_db


def test_the_equipment_story(freeze, django_capture_on_commit_callbacks):
    freeze(local(DAY, 10, 0))
    now = timezone.now()
    company, people = Command()._build_pharmacy(now)
    company.features = list(Feature.values)
    company.save()
    ensure_company_defaults(company)
    with django_capture_on_commit_callbacks(execute=True):
        members_demo.seed(company, people, now)
        demo.seed(company, people, now)
        assets_demo.seed(company, people, now)
        demo.finish(company, people, now)

    codes = set(AssetCategory.objects.filter(company=company).values_list("system_code", flat=True))
    assert {"lab_coat", "badge", "key", "cash_key", "phone", "scanner"} <= codes
    held = AssetAssignment.objects.filter(company=company, returned_on__isnull=True)
    # Every hand-out has its photo but the assets demo's older three; one coat waits.
    assert held.exclude(photo_out="").count() >= 25
    [waiting] = held.filter(acknowledged_at__isnull=True)
    assert (waiting.membership.first_name, waiting.asset.category.system_code) == (
        "Kamola",
        "lab_coat",
    )
    keys = held.filter(asset__category__system_code="cash_key")
    assert {row.membership.first_name for row in keys} == {"Bekzod", "Farrux"}
    assert held.filter(asset__category__system_code="phone", membership__first_name="Otabek")
    assert held.filter(asset__category__system_code="scanner", membership__first_name="Malika")

    sardor = Membership.objects.get(company=company, first_name="Sardor")
    coats = AssetAssignment.objects.filter(
        membership=sardor, asset__category__system_code="lab_coat"
    )
    assert sorted((row.returned_on is None, row.condition_in) for row in coats) == [
        (False, "worn"),
        (True, ""),
    ]
    dilshod = Membership.objects.get(company=company, first_name="Dilshod")
    lost = AssetAssignment.objects.get(membership=dilshod, asset__status=Asset.Status.DISPOSED)
    assert lost.asset.disposal == Asset.Disposal.LOST and lost.deduction_id is not None

    # Jasur leaves next week holding his badge and the scooter: both on his handover list.
    leaving = Termination.objects.get(membership=people["jasur"])
    listed = [item.title for item in leaving.handover.filter(kind="equipment")]
    assert len(listed) == 2 and any("Beyj" in title for title in listed)
    page = queries.people(company, people["owner"])
    jasur = next(row for row in page["people"] if row["person"]["id"] == people["jasur"].pk)
    assert jasur["leaving_soon"] and len(jasur["items"]) == 2
    assert page["totals"]["unconfirmed"] == 1
    # Stock to give out: coats, badges and door keys left over, never the register's fridges.
    stock = {row["category"]["name"] for row in queries.items(company, people["owner"])}
    assert stock and not any("fridge" in name.lower() for name in stock)
