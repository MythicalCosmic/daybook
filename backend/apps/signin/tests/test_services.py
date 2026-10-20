"""Who may sign in to the dashboard, and the client's address behind Caddy."""

from datetime import timedelta

import pytest
from django.test import RequestFactory
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from apps.accounts.tests.factories import UserFactory
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.signin import housekeeping, services
from apps.signin.models import DeviceSession
from apps.signin.tests.factories import DeviceSessionFactory

pytestmark = pytest.mark.django_db


def test_owners_managers_and_accountants_may_sign_in(company, member):
    for role in ("Owner", "Manager", "Accountant"):
        assert services.can_sign_in(member(company, role).user), role


def test_employees_and_cashiers_may_not(company, member):
    for role in ("Employee", "Cashier"):
        assert not services.can_sign_in(member(company, role).user), role


def test_a_custom_role_with_dashboard_access_may(company, member):
    person = member(company, "Employee")
    person.role.permissions = [Perm.DASHBOARD_ACCESS]
    person.role.save()

    assert services.can_sign_in(person.user)


def test_only_approved_members_of_active_companies_may(company, member, other_company):
    pending = member(company, "Owner", status=Membership.Status.PENDING)
    assert not services.can_sign_in(pending.user)

    owner = member(other_company, "Owner")
    other_company.is_active = False
    other_company.save()
    assert not services.can_sign_in(owner.user)


def test_platform_admins_are_not_special(settings):
    admin = UserFactory(is_superuser=True)
    settings.PLATFORM_ADMIN_TG_IDS = [admin.telegram_id]

    assert not services.can_sign_in(admin)


def test_deactivated_users_may_not(company, member):
    owner = member(company, "Owner")
    owner.user.is_active = False

    assert not services.can_sign_in(owner.user)


def test_client_ip_is_the_address_caddy_saw():
    request = RequestFactory().get(
        "/", HTTP_X_FORWARDED_FOR="1.2.3.4, 213.230.10.20", REMOTE_ADDR="172.18.0.5"
    )

    assert services.client_ip(request) == "213.230.10.20"


def test_client_ip_without_a_proxy_header_is_the_peer():
    assert services.client_ip(RequestFactory().get("/", REMOTE_ADDR="10.1.1.1")) == "10.1.1.1"


def test_a_malformed_address_is_dropped():
    request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="not-an-ip", REMOTE_ADDR="10.1.1.1")

    assert services.client_ip(request) is None


def test_the_daily_flush_drops_expired_tokens_and_dead_sessions(company, member):
    owner = member(company, "Owner")
    now = timezone.now()
    OutstandingToken.objects.create(
        user=owner.user, jti="old", token="x", created_at=now, expires_at=now - timedelta(days=1)
    )
    fresh = OutstandingToken.objects.create(
        user=owner.user, jti="new", token="y", created_at=now, expires_at=now + timedelta(days=1)
    )
    ended_long_ago = DeviceSessionFactory(user=owner.user, revoked_at=now - timedelta(days=31))
    ended_lately = DeviceSessionFactory(user=owner.user, revoked_at=now - timedelta(days=1))
    idle = DeviceSessionFactory(user=owner.user, last_seen_at=now - timedelta(days=60))
    active = DeviceSessionFactory(user=owner.user)

    housekeeping.flush_expired_tokens()

    assert list(OutstandingToken.objects.all()) == [fresh]
    remaining = set(DeviceSession.objects.values_list("pk", flat=True))
    assert remaining == {ended_lately.pk, active.pk}
    assert ended_long_ago.pk not in remaining and idle.pk not in remaining


def test_the_flush_runs_from_beat(settings):
    entry = settings.CELERY_BEAT_SCHEDULE["signin-flush-expired-tokens"]

    assert entry["task"] == "apps.signin.tasks.flush_expired_tokens"
