"""Every owner endpoint of company setup and groups, checked the same way (rule 21, §5):

- another company's id, or another company's branch or group id in our URL, answers 404;
- a member with dashboard access but without the endpoint's permission gets 403;
- someone without dashboard access gets 403, a mini app token 401;
- list endpoints make the same number of queries for 2 rows as for 6 (no N+1).
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.companies.tests.factories import BranchFactory
from apps.groups.tests.factories import TelegramGroupFactory
from apps.members.tests.factories import PositionFactory

pytestmark = pytest.mark.django_db

# (method, path under O/, a role with dashboard access that lacks the permission, or None when
# dashboard access is enough). `{branch}` and `{group}` are filled in per test.
ENDPOINTS = [
    ("get", "settings/", None),
    ("patch", "settings/", "Manager"),
    ("post", "settings/logo/", "Manager"),
    ("delete", "settings/logo/", "Manager"),
    ("get", "features/", "Manager"),
    ("patch", "features/", "Manager"),
    ("get", "branches/", None),
    ("post", "branches/", "Manager"),
    ("get", "branches/{branch}/", None),
    ("patch", "branches/{branch}/", "Manager"),
    ("post", "branches/{branch}/deactivate/", "Manager"),
    ("post", "branches/{branch}/activate/", "Manager"),
    ("post", "branches/reorder/", "Manager"),
    ("get", "branches/managers/", "Manager"),
    ("get", "invite/", "Accountant"),
    ("post", "invite/regenerate/", "Accountant"),
    ("get", "setup/", None),
    ("post", "setup/dismiss/", "Manager"),
    ("post", "setup/resume/", "Manager"),
    ("get", "groups/", "Accountant"),
    ("patch", "groups/{group}/", "Accountant"),
    ("post", "groups/{group}/disconnect/", "Accountant"),
]
IDS = [f"{method} {path}" for method, path, _role in ENDPOINTS]


def call(client, method, company, path, branch, group):
    url = f"/api/v1/owner/companies/{company.pk}/" + path.format(branch=branch.pk, group=group.pk)
    return getattr(client, method)(url, {}, format="json")


@pytest.fixture
def targets(company):
    return company.branches.first(), TelegramGroupFactory(company=company)


@pytest.mark.parametrize(("method", "path", "role"), ENDPOINTS, ids=IDS)
def test_another_companys_ids_are_not_found(
    method, path, role, company, other_company, member, owner_api, targets
):
    """An owner of `company` asking about `other_company` (or its rows) learns nothing."""
    owner = member(company, "Owner")
    member(other_company, "Owner")
    theirs = other_company.branches.first(), TelegramGroupFactory(company=other_company)
    client = owner_api(owner)

    assert call(client, method, other_company, path, *theirs).status_code == 404
    if "{" in path:
        # Their row behind our company id: the same 404, never their data.
        assert call(client, method, company, path, *theirs).status_code == 404


@pytest.mark.parametrize(("method", "path", "role"), ENDPOINTS, ids=IDS)
def test_a_missing_permission_is_refused(method, path, role, company, member, owner_api, targets):
    if role is None:
        pytest.skip("dashboard access is enough")
    lacking = member(company, role)

    assert call(owner_api(lacking), method, company, path, *targets).status_code == 403


@pytest.mark.parametrize(("method", "path", "role"), ENDPOINTS, ids=IDS)
def test_without_dashboard_access_or_with_a_mini_app_token(
    method, path, role, company, member, owner_api, targets
):
    employee = member(company, "Employee")
    assert call(owner_api(employee), method, company, path, *targets).status_code == 403

    mini_app = APIClient()
    mini_app.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(employee.user)}")
    assert call(mini_app, method, company, path, *targets).status_code == 401


def _queries(client, url) -> int:
    with CaptureQueriesContext(connection) as captured:
        assert client.get(url).status_code == 200
    return len(captured)


def test_the_branch_list_makes_no_query_per_branch(company, member, owner_api):
    owner = member(company, "Owner")
    client = owner_api(owner)
    url = f"/api/v1/owner/companies/{company.pk}/branches/"
    BranchFactory(company=company, manager=member(company, "Manager"))
    few = _queries(client, url)

    for _ in range(4):
        BranchFactory(company=company, manager=member(company, "Manager"))

    assert _queries(client, url) == few


def test_the_manager_options_make_no_query_per_person(company, member, owner_api):
    owner = member(company, "Owner")
    client = owner_api(owner)
    url = f"/api/v1/owner/companies/{company.pk}/branches/managers/"
    member(company, "Employee", position=PositionFactory(company=company))
    few = _queries(client, url)

    for _ in range(4):
        member(company, "Employee", position=PositionFactory(company=company))

    assert _queries(client, url) == few


def test_the_group_list_makes_no_query_per_group(company, member, owner_api):
    owner = member(company, "Owner")
    client = owner_api(owner)
    url = f"/api/v1/owner/companies/{company.pk}/groups/"

    def connect():
        group = TelegramGroupFactory(company=company, linked_by=member(company, "Manager"))
        group.positions.set([PositionFactory(company=company)])
        group.branches.set([BranchFactory(company=company)])

    connect()
    few = _queries(client, url)

    for _ in range(4):
        connect()

    assert _queries(client, url) == few
