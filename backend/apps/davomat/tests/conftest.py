"""Fixtures of the Davomat tests: the edition switched on, an organization set up the way the
first-run page sets it up, and its people."""

from dataclasses import dataclass

import pytest
from django.core.cache import cache

from apps.companies.models import Branch
from apps.davomat import queries, services
from apps.members.models import AccessRole, Membership

DASHBOARD = {"HTTP_X_REQUESTED_WITH": "dashboard", "HTTP_ORIGIN": "http://testserver"}
OWNER_PASSWORD = "Tashkent-Spring-2026"
PASSWORD = "Samarkand-Autumn-77"
API = "/api/v1/owner"


@pytest.fixture(autouse=True)
def fresh_cache():
    """Lockout counters and throttles live in the cache: every test starts from zero."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def davomat(settings):
    settings.EDITION = "davomat"
    return settings


@dataclass
class Org:
    owner: Membership
    main: Branch
    second: Branch

    @property
    def company(self):
        return self.owner.company

    def role(self, kind: str) -> AccessRole:
        return next(
            role
            for role in AccessRole.objects.filter(company=self.company)
            if queries.role_kind(role) == kind
        )

    def user(self, kind: str, username: str, *, branches=None, first_name="Test") -> Membership:
        return services.create_user(
            self.company,
            by=self.owner,
            username=username,
            password=PASSWORD,
            role=self.role(kind),
            first_name=first_name,
            last_name=kind.title(),
            branches=[self.main] if branches is None else branches,
        )

    def employee(self, first_name: str, last_name: str = "", **fields) -> Membership:
        fields.setdefault("branches", [self.main])
        return services.create_employee(
            self.company, by=self.owner, first_name=first_name, last_name=last_name, **fields
        )

    def url(self, path: str) -> str:
        return f"{API}/companies/{self.company.pk}/{path}"


@pytest.fixture
def org(db, davomat) -> Org:
    """ "Namuna MChJ" as the setup page makes it, with a second branch "Chilonzor"."""
    owner = services.setup_organization(
        name="Namuna MChJ",
        timezone="Asia/Tashkent",
        language="en",
        admin={
            "username": "owner",
            "password": OWNER_PASSWORD,
            "first_name": "Dilnoza",
            "last_name": "Karimova",
        },
    )
    main = owner.company.branches.get()
    second = Branch.objects.create(company=owner.company, name="Chilonzor", code="CHL", order=1)
    owner = Membership.objects.select_related("company", "user", "role").get(pk=owner.pk)
    return Org(owner=owner, main=main, second=second)
