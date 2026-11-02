"""hr/0002: everyone working in a company when HR arrived gets a profile, hired on the day of
their latest approval (in the company's calendar), run against today's models."""

import importlib
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from django.apps import apps as django_apps

from apps.audit.models import AuditLog
from apps.hr.models import EmployeeProfile
from apps.members.models import Membership
from apps.members.tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db

MIGRATION = importlib.import_module("apps.hr.migrations.0002_profiles_for_members")
TZ = ZoneInfo("Asia/Tashkent")


def run():
    MIGRATION.create_profiles(django_apps, None)


def test_current_members_get_a_profile_hired_on_their_approval(company, member):
    # Approved at 23:30 Tashkent on 3 March: still the 3rd there (the 3rd at 18:30 UTC).
    approved = member.registered(company, decided_at=datetime(2025, 3, 3, 23, 30, tzinfo=TZ))
    suspended = member.registered(
        company,
        status=Membership.Status.SUSPENDED,
        decided_at=datetime(2024, 1, 10, 9, tzinfo=TZ),
    )
    rejoined = member.registered(company, decided_at=datetime(2023, 6, 1, 9, tzinfo=TZ))
    AuditLog.objects.create(
        company=company,
        action="member.approved",
        target_type="membership",
        target_id=rejoined.pk,
        target="x",
    )
    AuditLog.objects.filter(target_id=rejoined.pk).update(
        created_at=datetime(2025, 9, 15, 10, tzinfo=TZ)
    )
    left = member.registered(company, status=Membership.Status.LEFT)
    pending = MembershipFactory(company=company)
    EmployeeProfile.objects.all().delete()

    run()
    run()  # a second run adds nothing

    hired = dict(EmployeeProfile.objects.values_list("membership_id", "hire_date"))
    assert hired == {
        approved.pk: date(2025, 3, 3),
        suspended.pk: date(2024, 1, 10),
        rejoined.pk: date(2025, 9, 15),
    }
    assert left.pk not in hired and pending.pk not in hired


def test_existing_profiles_are_kept(company, member):
    person = member.registered(company, decided_at=datetime(2025, 3, 3, 9, tzinfo=TZ))
    EmployeeProfile.objects.update_or_create(
        membership=person, defaults={"company": company, "hire_date": date(2020, 1, 1)}
    )

    run()

    assert EmployeeProfile.objects.get(membership=person).hire_date == date(2020, 1, 1)


def test_someone_without_an_approval_date_is_hired_when_they_registered(company, member):
    person = member(company, decided_at=None, onboarded_at=datetime(2025, 2, 1, 9, tzinfo=TZ))

    run()

    assert EmployeeProfile.objects.get(membership=person).hire_date == date(2025, 2, 1)
