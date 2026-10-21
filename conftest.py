from contextlib import ExitStack
from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.companies.models import Branch
from apps.companies.tests.factories import CompanyFactory
from apps.console import registry
from apps.core import redis as core_redis
from apps.members.models import AccessRole, Membership, Position
from apps.members.tests.factories import MembershipFactory
from apps.signin.tokens import OwnerAccessToken


@pytest.fixture
def company(db):
    return CompanyFactory()


@pytest.fixture
def other_company(db):
    return CompanyFactory()


class MemberMaker:
    """Makes members holding one of the company's default roles, approved unless told otherwise."""

    def __call__(self, company, role_name="Employee", **kwargs) -> Membership:
        kwargs.setdefault("status", Membership.Status.APPROVED)
        role = AccessRole.objects.get(company=company, name=role_name)
        return MembershipFactory(company=company, role=role, **kwargs)

    async def acreate(self, company, role_name="Employee", **kwargs) -> Membership:
        return await sync_to_async(self)(company, role_name, **kwargs)

    def registered(self, company, role_name="Employee", **kwargs) -> Membership:
        """Approved and through onboarding: someone who can actually work on tasks."""
        kwargs.setdefault("onboarded_at", timezone.now() - timedelta(days=30))
        kwargs.setdefault("user__phone", "+998901234567")
        return self(company, role_name, **kwargs)

    async def aregistered(self, company, role_name="Employee", **kwargs) -> Membership:
        return await sync_to_async(self.registered)(company, role_name, **kwargs)


@pytest.fixture
def member(db):
    return MemberMaker()


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    """Uploaded files (task proof photos) land in a throwaway directory."""
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture(autouse=True)
def private_media(settings, tmp_path):
    """Private files (receipts, documents, exports) land in a throwaway directory too."""
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "private_media"
    return settings.PRIVATE_MEDIA_ROOT


@pytest.fixture
def api_as(db):
    """`api_as(member)`: a DRF client signed in to the mini app API as that member's user."""

    def make(membership: Membership) -> APIClient:
        client = APIClient()
        token = AccessToken.for_user(membership.user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    return make


@pytest.fixture
def owner_api(db):
    """`owner_api(member)`: a DRF client with an owner dashboard token (`aud="dashboard"`)."""

    def make(membership: Membership) -> APIClient:
        client = APIClient()
        token = OwnerAccessToken.for_user(membership.user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    return make


# The people every module's demo.py gets (docs/PLAN-OWNER.md §2.3 rule 22), as seed_demo makes
# them: key -> (first name, last name, role, position). seed_demo gives roles and positions their
# Uzbek names (seed_demo.IN_UZBEK) only after every demo.py has run.
DEMO_PEOPLE = {
    "owner": ("Dilnoza", "Karimova", "Owner", "Office"),
    "manager": ("Bekzod", "Mirzayev", "Manager", "Head of pharmacy"),
    "worker": ("Alisher", "Valiyev", "Pharmacist", "Pharmacist"),
    "madina": ("Madina", "Saidova", "Pharmacist", "Senior pharmacist"),
    "jasur": ("Jasur", "Tursunov", "Employee", "Courier"),
    "nigora": ("Nigora", "Azimova", "Pharmacist", "Pharmacist"),
}


@pytest.fixture
def demo_people(db):
    """`demo_people(company)`: the six demo memberships, approved and onboarded, working in the
    company's first branch, to test `demo.seed(company, people, now)` without seed_demo."""

    def make(company) -> dict[str, Membership]:
        branch = company.branches.order_by("order", "pk").first()
        if branch is None:
            branch = Branch.objects.create(company=company, name=company.name)
        roles = {role.name: role for role in AccessRole.objects.filter(company=company)}
        people = {}
        for index, (key, (first, last, role, position)) in enumerate(DEMO_PEOPLE.items()):
            position_row, _ = Position.objects.get_or_create(
                company=company, name=position, defaults={"order": index}
            )
            membership = MembershipFactory(
                company=company,
                role=roles[role],
                position=position_row,
                status=Membership.Status.APPROVED,
                first_name=first,
                last_name=last,
                onboarded_at=timezone.now() - timedelta(days=60),
                home_branch=branch,
                user__first_name=first,
                user__last_name=last,
                user__phone=f"+99890111000{index + 1}",
            )
            membership.branches.add(branch)
            people[key] = membership
        return people

    return make


@pytest.fixture
def isolated_registries():
    """Register test providers freely; every console, inbox and exports registry is back to
    what the apps' hooks registered when the test ends."""
    with ExitStack() as stack:
        for each in registry.REGISTRIES:
            stack.enter_context(each.isolated())
        yield registry


@pytest.fixture
def empty_registries():
    """Like `isolated_registries`, but every console, inbox and exports registry starts empty:
    for the registries' own tests, which see exactly what they register whatever the apps add.
    To empty a single registry (keeping, say, the real inbox kinds a notification needs), use
    `registry.X.isolated(empty=True, keep=(...))`."""
    with ExitStack() as stack:
        for each in registry.REGISTRIES:
            stack.enter_context(each.isolated(empty=True))
        yield registry


@pytest.fixture
def fake_redis():
    """Every `apps.core.redis` client talks to an in-memory server for this test."""
    server = core_redis.use_fake()
    yield server
    core_redis.reset()


@pytest.fixture
def sent_messages(monkeypatch):
    """Telegram messages the backend tried to send, captured instead of sent."""
    sent = []

    def record(bot, chat_id, text, reply_markup=None, photo=None, photo_storage="default"):
        sent.append(
            {
                "bot": bot,
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
                "photo": photo,
                "photo_storage": photo_storage,
            }
        )

    monkeypatch.setattr("apps.notifications.telegram.send_message", record)
    return sent
