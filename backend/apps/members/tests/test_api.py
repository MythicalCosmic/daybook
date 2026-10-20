import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.companies.tests.factories import BranchFactory
from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm
from apps.members.tests.factories import MembershipFactory, PositionFactory

pytestmark = pytest.mark.django_db


def client_for(membership: Membership) -> APIClient:
    api = APIClient()
    token = RefreshToken.for_user(membership.user).access_token
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api


@pytest.fixture
def newcomer(company, member):
    """Approved, phone shared in the bot, registration not finished yet."""
    return member(company, user__phone="+998901234567")


def onboard(membership, **overrides):
    payload = {"first_name": "Ali", "last_name": "Valiyev"} | overrides
    return client_for(membership).post(
        f"/api/v1/companies/{membership.company_id}/onboarding/", payload, format="json"
    )


def test_positions_lists_only_this_companys_active_positions(company, other_company, newcomer):
    PositionFactory(company=company, name="Cashier")
    PositionFactory(company=company, name="Retired", is_active=False)
    PositionFactory(company=other_company, name="Driver")

    response = client_for(newcomer).get(f"/api/v1/companies/{company.pk}/positions/")

    assert response.status_code == 200
    assert [p["name"] for p in response.data] == ["Cashier"]


def test_other_companies_look_like_they_do_not_exist(other_company, newcomer):
    response = client_for(newcomer).get(f"/api/v1/companies/{other_company.pk}/positions/")

    assert response.status_code == 404


def test_pending_person_sees_positions_to_create_their_account(company):
    pending = MembershipFactory(company=company)

    response = client_for(pending).get(f"/api/v1/companies/{company.pk}/positions/")

    assert response.status_code == 200


def test_rejected_person_cannot_see_positions(company):
    rejected = MembershipFactory(company=company, status=Membership.Status.REJECTED)

    response = client_for(rejected).get(f"/api/v1/companies/{company.pk}/positions/")

    assert response.status_code == 404


def test_pending_person_creates_their_account(company, django_capture_on_commit_callbacks):
    pending = MembershipFactory(company=company, user__phone="+998901234567")

    with django_capture_on_commit_callbacks() as callbacks:
        response = onboard(pending)

    assert response.status_code == 200
    assert response.data["status"] == "pending"
    assert response.data["is_onboarded"] is True
    assert len(callbacks) == 1  # the approvers are asked now


def test_positions_require_authentication(company):
    assert APIClient().get(f"/api/v1/companies/{company.pk}/positions/").status_code == 401


def test_onboarding_completes_registration(company, newcomer, django_capture_on_commit_callbacks):
    cashier = PositionFactory(company=company, name="Cashier")

    with django_capture_on_commit_callbacks() as callbacks:
        response = onboard(newcomer, position_id=cashier.pk)

    assert response.status_code == 200
    assert response.data["is_onboarded"] is True
    assert response.data["position"] == {"id": cashier.pk, "name": "Cashier"}
    newcomer.refresh_from_db()
    assert (newcomer.first_name, newcomer.last_name) == ("Ali", "Valiyev")
    assert newcomer.onboarded_at is not None
    assert len(callbacks) == 1  # the bot confirms it


def test_onboarding_needs_a_shared_phone(company, member):
    no_phone = member(company)

    response = onboard(no_phone)

    assert response.status_code == 400
    assert "phone" in response.data["detail"]


def test_onboarding_needs_a_position_when_the_company_has_some(company, newcomer):
    PositionFactory(company=company)

    response = onboard(newcomer)

    assert response.status_code == 400


def test_onboarding_without_positions_is_fine_when_the_company_has_none(newcomer):
    response = onboard(newcomer)

    assert response.status_code == 200
    assert response.data["position"] is None


@pytest.mark.parametrize("which", ["other_company", "inactive"])
def test_onboarding_rejects_positions_it_should_not_offer(company, other_company, newcomer, which):
    if which == "inactive":
        position = PositionFactory(company=company, is_active=False)
    else:
        position = PositionFactory(company=other_company)
    PositionFactory(company=company)

    response = onboard(newcomer, position_id=position.pk)

    assert response.status_code == 400
    newcomer.refresh_from_db()
    assert newcomer.position is None


def test_onboarding_happens_once(newcomer):
    assert onboard(newcomer).status_code == 200

    response = onboard(newcomer, first_name="Someone else")

    assert response.status_code == 400
    newcomer.refresh_from_db()
    assert newcomer.first_name == "Ali"


def test_onboarding_rejects_blank_names(newcomer):
    response = onboard(newcomer, first_name="  ")

    assert response.status_code == 400
    assert "first_name" in response.data


def test_schema_documents_the_mini_app_api(client):
    response = client.get("/api/schema/")

    assert response.status_code == 200
    for path in (b"/api/v1/auth/telegram/", b"/api/v1/me/", b"onboarding"):
        assert path in response.content


def test_the_member_list_follows_branch_scope(company, member):
    here = company.branches.get()
    there = BranchFactory(company=company)
    AccessRole.objects.create(company=company, name="Lead", permissions=[Perm.TASKS_ASSIGN])
    lead = member.registered(company, "Lead", first_name="Lola")
    lead.branches.set([here])
    colleague = member.registered(company, first_name="Kamol")
    colleague.branches.set([here, there])
    elsewhere = member.registered(company, first_name="Vali")
    elsewhere.branches.set([there])
    nowhere = member.registered(company, first_name="Zafar")
    manager = member.registered(company, "Manager", first_name="Anvar")  # branches.all
    url = f"/api/v1/companies/{company.pk}/members/"

    scoped = client_for(lead).get(url)
    everyone = client_for(manager).get(url)

    assert [m["id"] for m in scoped.data] == [colleague.pk, lead.pk]
    assert {m["id"] for m in everyone.data} == {
        lead.pk,
        colleague.pk,
        elsewhere.pk,
        nowhere.pk,
        manager.pk,
    }
