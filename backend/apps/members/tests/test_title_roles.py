"""A job title gives its access: approving someone or changing their job title gives the role it
names (the default role when it names none), as far as the person doing it may give that role.
Owners stay owners and a role set by hand stays."""

import importlib

import pytest
from django.apps import apps
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.members import bot_messages, join_links, services
from apps.members.audit_actions import MemberAction
from apps.members.models import AccessRole, Membership, Position
from apps.members.permissions import Perm
from apps.members.positions import create_default_positions, default_names
from apps.members.tests.factories import AccessRoleFactory, MembershipFactory, PositionFactory

pytestmark = pytest.mark.django_db


def role(company, name):
    return AccessRole.objects.get(company=company, name=name)


@pytest.fixture
def owner(company, member):
    return member.registered(company, "Owner")


@pytest.fixture
def kassir(company):
    return PositionFactory(company=company, name="Kassir", role=role(company, "Cashier"))


@pytest.fixture
def farmatsevt(company):
    return PositionFactory(company=company, name="Farmatsevt", role=role(company, "Pharmacist"))


def requested(company, position=None):
    """A join request with the details filled in."""
    return MembershipFactory(
        company=company,
        position=position,
        onboarded_at=timezone.now(),
        user__phone="+998901112233",
    )


def fresh(membership):
    return Membership.objects.select_related("role", "position").get(pk=membership.pk)


# Approving -----------------------------------------------------------------------------------


def test_approving_gives_the_job_titles_access(company, owner, kassir):
    person = services.approve(requested(company, kassir), by=owner.user)

    assert fresh(person).role == role(company, "Cashier")


def test_a_job_title_without_access_of_its_own_gives_the_default_role(company, owner):
    cleaner = PositionFactory(company=company, name="Farrosh")

    person = services.approve(requested(company, cleaner), by=owner.user)

    assert fresh(person).role == role(company, "Employee")


def test_the_approvers_choice_and_the_title_they_name_win(company, owner, kassir, farmatsevt):
    chosen = services.approve(
        requested(company, kassir), by=owner.user, role=role(company, "Manager")
    )
    renamed = services.approve(requested(company), by=owner.user, position=farmatsevt)

    assert fresh(chosen).role == role(company, "Manager")
    assert fresh(renamed).role == role(company, "Pharmacist")


def test_an_approver_who_may_not_give_the_titles_access_gives_the_default_role(
    company, member, kassir
):
    gatekeeper = AccessRoleFactory(company=company, permissions=[Perm.MEMBERS_APPROVE])
    approver = member.registered(company, gatekeeper.name)

    person = services.approve(requested(company, kassir), by=approver.user)

    assert fresh(person).role == role(company, "Employee")


def test_the_bot_card_says_which_access_approving_brings(company, kassir):
    text, _keyboard = bot_messages.join_request(requested(company, kassir))
    plain, _ = bot_messages.join_request(requested(company))

    assert "Access: Cashier" in text
    assert "Access:" not in plain  # the default role goes without saying


# Team links ---------------------------------------------------------------------------------


def joined_through(link, position=None):
    user = UserFactory(phone="+998901112233")
    membership, _admitted = join_links.open_link(user, link.start_param)
    return services.complete_onboarding(
        membership,
        first_name="Aziz",
        last_name="Karimov",
        position_id=(position or membership.position).pk
        if (position or membership.position)
        else None,
    )


def test_a_team_link_that_sets_the_job_title_gives_its_access(company, owner, kassir):
    link = join_links.create_link(company, by=owner, name="Kassirlar", position=kassir)

    person = joined_through(link)

    assert person.status == Membership.Status.APPROVED
    assert fresh(person).role == role(company, "Cashier")


def test_a_job_title_picked_through_a_team_link_never_raises_access(company, owner):
    boss = PositionFactory(company=company, name="Bosh menejer", role=role(company, "Manager"))
    link = join_links.create_link(company, by=owner, name="Hamma uchun")

    person = joined_through(link, position=boss)

    assert person.status == Membership.Status.APPROVED
    assert fresh(person).position == boss
    assert fresh(person).role == role(company, "Employee")  # nobody looked at that title


# Changing someone's job title ---------------------------------------------------------------


def test_a_new_job_title_brings_its_access(company, member, owner, kassir, farmatsevt):
    person = member.registered(company, "Pharmacist", position=farmatsevt)

    services.update_member(person, by=owner, position=kassir)

    assert fresh(person).role == role(company, "Cashier")
    row = AuditLog.objects.filter(action=MemberAction.CHANGED, target_id=person.pk).latest("pk")
    assert row.details["changes"]["role"] == ["Pharmacist", "Cashier"]


def test_access_set_by_hand_and_owners_stay(company, member, owner, kassir, farmatsevt):
    by_hand = member.registered(company, "Manager", position=farmatsevt)
    other_owner = member.registered(company, "Owner", position=farmatsevt)

    services.update_member(by_hand, by=owner, position=kassir)
    services.update_member(other_owner, by=owner, position=kassir)

    assert fresh(by_hand).role == role(company, "Manager")
    assert fresh(other_owner).role == role(company, "Owner")


def test_without_roles_manage_the_job_title_changes_but_not_the_access(
    company, member, kassir, farmatsevt
):
    hr = AccessRoleFactory(
        company=company,
        permissions=[Perm.MEMBERS_MANAGE, Perm.SALES_OPERATE, Perm.FINANCE_CLAIM],
    )
    editor = member.registered(company, hr.name)
    person = member.registered(company, "Pharmacist", position=farmatsevt)

    services.update_member(person, by=editor, position=kassir)

    assert fresh(person).position == kassir
    assert fresh(person).role == role(company, "Pharmacist")


def test_a_role_chosen_with_the_new_title_wins(
    owner_api, company, member, owner, kassir, farmatsevt
):
    person = member.registered(company, "Pharmacist", position=farmatsevt)

    response = owner_api(owner).patch(
        f"/api/v1/owner/companies/{company.pk}/people/{person.pk}/",
        {"position_id": kassir.pk, "role_id": role(company, "Manager").pk},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["role"]["name"] == "Manager"
    assert response.data["role_follows_title"] is False


# The access a job title gives ---------------------------------------------------------------


def test_setting_a_titles_access_needs_roles_manage_and_never_the_owner_role(
    company, member, owner, kassir
):
    titles = AccessRoleFactory(company=company, permissions=[Perm.POSITIONS_MANAGE])
    clerk = member.registered(company, titles.name)

    with pytest.raises(PermissionDenied):
        services.save_position(company, by=clerk, position=kassir, role=None)
    with pytest.raises(DomainError, match="Owner"):
        services.save_position(company, by=owner, position=kassir, role=role(company, "Owner"))
    services.save_position(company, by=clerk, position=kassir, name="Kassir (kunduzgi)")
    assert Position.objects.get(pk=kassir.pk).role == role(company, "Cashier")


def test_giving_a_titles_access_to_the_people_who_hold_it(company, member, owner):
    kassir = PositionFactory(company=company, name="Kassir")
    follows = member.registered(company, "Employee", position=kassir)
    by_hand = member.registered(company, "Manager", position=kassir)
    boss = member.registered(company, "Owner", position=kassir)

    saved = services.save_position(
        company, by=owner, position=kassir, role=role(company, "Cashier"), apply_to_holders=True
    )

    assert saved.applied == 1
    assert fresh(follows).role == role(company, "Cashier")
    assert fresh(by_hand).role == role(company, "Manager")
    assert fresh(boss).role == role(company, "Owner")
    assert AuditLog.objects.filter(action=MemberAction.ROLE_CHANGED, target_id=follows.pk).exists()


def test_a_role_a_job_title_gives_cant_be_deleted(company, owner):
    stock = AccessRoleFactory(company=company, name="Ombor")
    PositionFactory(company=company, name="Ombor xodimi", role=stock)

    with pytest.raises(DomainError, match="Job titles give this role"):
        services.delete_role(stock, by=owner)


def test_the_positions_api_shows_and_changes_a_titles_access(owner_api, company, member, owner):
    kassir = PositionFactory(company=company, name="Kassir")
    holder = member.registered(company, "Employee", position=kassir)
    api = owner_api(owner)
    url = f"/api/v1/owner/companies/{company.pk}/positions/"

    listed = {row["id"]: row for row in api.get(url).data}
    assert listed[kassir.pk]["role"] is None
    response = api.patch(
        f"{url}{kassir.pk}/",
        {"role_id": role(company, "Cashier").pk, "apply_to_holders": True},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["role"]["name"] == "Cashier"
    assert response.data["applied"] == 1
    detail = api.get(f"/api/v1/owner/companies/{company.pk}/people/{holder.pk}/").data
    assert detail["role"]["name"] == "Cashier"
    assert detail["role_follows_title"] is True


# New companies and companies made before ----------------------------------------------------


def test_a_new_companys_titles_give_their_usual_access(company):
    create_default_positions(company)
    names = default_names(company.default_language)
    titles = {p.name: p.role for p in Position.objects.filter(company=company)}

    assert titles[names[6]] == role(company, "Cashier")  # Cashier
    assert titles[names[5]] == role(company, "Pharmacist")  # Pharmacist
    assert titles[names[11]] is None  # Cleaner: the default role
    assert not any(r is not None and r.is_owner for r in titles.values())


def test_titles_made_before_get_their_usual_access(company):
    kassir = Position.objects.create(company=company, name="Kassir")
    courier = Position.objects.create(company=company, name="Kuryer")
    migration = importlib.import_module("apps.members.migrations.0015_position_role")

    migration.give_default_roles(apps, None)

    assert Position.objects.get(pk=kassir.pk).role == role(company, "Cashier")
    assert Position.objects.get(pk=courier.pk).role is None
