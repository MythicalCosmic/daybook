from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.companies.models import Company
from apps.members.models import Membership
from apps.reports import kpis

pytestmark = pytest.mark.django_db


def seed(**options) -> None:
    call_command("seed_demo", stdout=StringIO(), **options)


def test_the_demo_builds_and_rebuilds(settings):
    settings.DEBUG = True

    seed()
    seed(reset=True)  # everything the demo made can be removed again

    company = Company.objects.get(slug="demo-shop")
    assert company.memberships.filter(status=Membership.Status.APPROVED).count() == 6
    today = timezone.localdate()
    report = kpis.team(company, today - timedelta(days=14), today, timezone.now())
    with_work = {str(person): score for person, score in report.rows if score.total}
    assert {"Alisher Valiyev", "Madina Saidova", "Jasur Tursunov", "Nigora Azimova"} <= set(
        with_work
    )
    assert with_work["Nigora Azimova"].on_time_percent == 100
    assert with_work["Jasur Tursunov"].missed == 2


def test_the_demo_stays_out_of_production():
    with pytest.raises(CommandError):
        seed()
