"""Team links: one link (or QR code) that adds many people at once."""

from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.companies.tests.factories import BranchFactory
from apps.core.exceptions import DomainError
from apps.groups.models import GroupEvent, TelegramGroup
from apps.inbox.models import Notification
from apps.members import join_links, services
from apps.members.audit_actions import MemberAction
from apps.members.models import AccessRole, JoinLink, Membership
from apps.members.permissions import Perm
from apps.members.tests.factories import AccessRoleFactory, MembershipFactory, PositionFactory

pytestmark = pytest.mark.django_db


def make_link(company, by, **fields):
    fields.setdefault("name", "Staff meeting")
    return join_links.create_link(company, by=by, **fields)


def opened(link):
    """Someone opens the link in the bot: their membership (pending, no account yet)."""
    user = UserFactory(phone="+998901112233")
    membership, _admitted = join_links.open_link(user, link.start_param)
    return membership


def finish(membership, first_name="Aziz", position=None):
    """They create their account in the app."""
    return services.complete_onboarding(
        membership,
        first_name=first_name,
        last_name="Karimov",
        position_id=position.pk if position else None,
    )


def test_a_link_adds_people_straight_away_with_its_branch_and_role(
    company, member, sent_messages, django_capture_on_commit_callbacks
):
    owner = member.registered(company, "Owner")
    branch = company.branches.first()
    cashier = AccessRole.objects.get(company=company, name="Cashier")
    link = make_link(company, owner, branch=branch, role=cashier)

    membership = opened(link)
    assert membership.status == Membership.Status.PENDING
    assert membership.join_link == link
    with django_capture_on_commit_callbacks(execute=True):
        joined = finish(membership)

    assert joined.status == Membership.Status.APPROVED
    assert joined.joined_by_link is True
    assert joined.role == cashier
    assert joined.home_branch == branch
    assert list(joined.branches.all()) == [branch]
    assert joined.decided_by == owner.user
    link.refresh_from_db()
    assert link.uses == 1
    row = AuditLog.objects.get(action=AuditLog.Action.MEMBER_APPROVED, target_id=joined.pk)
    assert row.details["link"] == "Staff meeting"
    # The person hears a welcome with the menu, not "your request was approved".
    welcome = next(m for m in sent_messages if m["chat_id"] == joined.user.telegram_id)
    assert "Welcome to the team, Aziz!" in welcome["text"]
    assert "approved" not in welcome["text"]


def test_without_a_role_the_link_gives_the_default_one(company, member):
    owner = member.registered(company, "Owner")
    link = make_link(company, owner)

    joined = finish(opened(link))

    assert joined.role == AccessRole.objects.get(company=company, is_default=True)


def test_a_link_that_asks_first_leaves_a_request_with_its_choices(
    company, member, django_capture_on_commit_callbacks
):
    owner = member.registered(company, "Owner")
    manager = member.registered(company, "Manager")
    second = BranchFactory(company=company, name="Yunusobod")
    # A role the manager may give too (they hold its permissions).
    cashier = AccessRoleFactory(company=company, permissions=[Perm.SALES_VIEW, Perm.FINANCE_CLAIM])
    link = make_link(company, owner, auto_approve=False, branch=second, role=cashier)

    with django_capture_on_commit_callbacks(execute=True):
        request = finish(opened(link))

    assert request.status == Membership.Status.PENDING
    note = Notification.objects.get(recipient=manager, kind="members.join")
    assert "Team link: Staff meeting" in note.body
    link.refresh_from_db()
    assert link.uses == 1  # a place is used by finishing, whatever the link decides

    approved = services.approve_request(request, by=manager)  # no choices: the link's
    assert approved.role == cashier
    assert approved.home_branch == second
    assert approved.joined_by_link is False


def test_an_approver_who_may_not_give_the_links_role_gives_the_default(company, member):
    owner = member.registered(company, "Owner")
    head = AccessRoleFactory(company=company, permissions=[Perm.MEMBERS_APPROVE, Perm.BRANCHES_ALL])
    approver = member.registered(company, head.name)
    manager_role = AccessRole.objects.get(company=company, name="Manager")
    link = make_link(company, owner, auto_approve=False, role=manager_role)
    request = finish(opened(link))

    approved = services.approve_request(request, by=approver)

    assert approved.role == AccessRole.objects.get(company=company, is_default=True)


def test_the_position_is_chosen_for_them_but_they_can_change_it(company, member):
    owner = member.registered(company, "Owner")
    pharmacist = PositionFactory(company=company, name="Pharmacist")
    courier = PositionFactory(company=company, name="Courier")
    link = make_link(company, owner, position=pharmacist)

    membership = opened(link)
    assert membership.position == pharmacist  # the app preselects it

    joined = finish(membership, position=courier)
    assert joined.position == courier


def test_the_last_place_goes_to_one_person_then_the_link_is_full(
    company, member, django_capture_on_commit_callbacks
):
    owner = member.registered(company, "Owner")
    link = make_link(company, owner, max_uses=2)
    first, second, third = (opened(link) for _ in range(3))  # all opened while there was room

    assert finish(first).status == Membership.Status.APPROVED
    assert finish(second).status == Membership.Status.APPROVED
    with django_capture_on_commit_callbacks(execute=True):
        late = finish(third)

    assert late.status == Membership.Status.PENDING  # an ordinary request now
    link.refresh_from_db()
    assert link.uses == 2
    assert link.status_at(timezone.now()) == JoinLink.Status.FULL
    with pytest.raises(DomainError, match="no places left"):
        opened(link)


def test_expired_and_stopped_links_are_explained(company, member):
    owner = member.registered(company, "Owner")
    link = make_link(company, owner, expires_at=timezone.now() + timedelta(hours=1))
    JoinLink.objects.filter(pk=link.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
    with pytest.raises(DomainError, match="expired"):
        opened(link)

    stopped = make_link(company, owner, name="Old")
    join_links.update_link(stopped, by=owner, is_active=False)
    with pytest.raises(DomainError, match="switched off"):
        opened(stopped)

    with pytest.raises(DomainError, match="invalid"):
        join_links.find("j_nope")


def test_a_link_that_ends_while_someone_signs_up_leaves_them_a_request(company, member):
    owner = member.registered(company, "Owner")
    link = make_link(company, owner)
    membership = opened(link)
    join_links.update_link(link, by=owner, is_active=False)

    assert finish(membership).status == Membership.Status.PENDING


def test_someone_already_on_the_team_just_hears_where_they_stand(company, member):
    owner = member.registered(company, "Owner")
    link = make_link(company, owner, max_uses=1)
    worker = member.registered(company)
    JoinLink.objects.filter(pk=link.pk).update(uses=1)  # full: still no error for a member

    membership, admitted = join_links.open_link(worker.user, link.start_param)

    assert membership == worker
    assert admitted is False


def test_a_waiting_request_is_let_in_by_a_link_that_adds_straight_away(company, member):
    owner = member.registered(company, "Owner")
    waiting = MembershipFactory(company=company, onboarded_at=timezone.now(), first_name="Ali")
    link = make_link(company, owner)

    membership, admitted = join_links.open_link(waiting.user, link.start_param)

    assert admitted is True
    assert membership.status == Membership.Status.APPROVED
    assert membership.joined_by_link is True
    link.refresh_from_db()
    assert link.uses == 1
    # Opening it again counts nothing more.
    assert join_links.open_link(waiting.user, link.start_param) == (membership, False)


def test_opening_the_same_link_again_uses_no_extra_place(company, member):
    owner = member.registered(company, "Owner")
    link = make_link(company, owner, auto_approve=False)
    request = finish(opened(link))

    again, admitted = join_links.open_link(request.user, link.start_param)

    assert (again, admitted) == (request, False)
    link.refresh_from_db()
    assert link.uses == 1


def test_people_who_left_come_back_through_an_approver(company, member):
    owner = member.registered(company, "Owner")
    link = make_link(company, owner)
    returning = MembershipFactory(
        company=company, status=Membership.Status.LEFT, onboarded_at=timezone.now()
    )
    audit.record(
        AuditLog.Action.MEMBER_LEFT, company_id=company.pk, actor=owner.user, target=returning
    )

    membership, admitted = join_links.open_link(returning.user, link.start_param)

    assert admitted is False
    assert membership.status == Membership.Status.PENDING


def test_people_turned_down_before_come_back_through_an_approver(company, member):
    owner = member.registered(company, "Owner")
    link = make_link(company, owner)
    turned_down = MembershipFactory(company=company, onboarded_at=timezone.now())
    services.reject(turned_down, by=owner.user)
    Membership.objects.filter(pk=turned_down.pk).update(
        decided_at=timezone.now() - timedelta(days=3)  # past the cooldown
    )

    membership, admitted = join_links.open_link(turned_down.user, link.start_param)

    assert admitted is False
    assert membership.status == Membership.Status.PENDING


def test_someone_coming_back_starts_without_their_old_link(company, member):
    owner = member.registered(company, "Owner")
    link = make_link(company, owner)
    joined = finish(opened(link))
    Membership.objects.filter(pk=joined.pk).update(status=Membership.Status.LEFT)  # offboarded

    again, _created = services.request_access(joined.user, company)  # the main invite link

    assert again.status == Membership.Status.PENDING
    assert again.join_link is None
    assert again.joined_by_link is False


def test_a_maker_who_lost_the_right_to_approve_lets_nobody_in(company, member):
    manager = member.registered(company, "Manager")
    link = make_link(company, manager)
    manager.role = AccessRole.objects.get(company=company, name="Employee")
    manager.save()

    assert finish(opened(link)).status == Membership.Status.PENDING


def test_a_maker_who_left_lets_nobody_in(company, member):
    manager = member.registered(company, "Manager")
    link = make_link(company, manager)
    manager.status = Membership.Status.LEFT
    manager.save()

    assert finish(opened(link)).status == Membership.Status.PENDING


def test_a_closed_branch_stops_automatic_joining(company, member):
    owner = member.registered(company, "Owner")
    second = BranchFactory(company=company, name="Yunusobod")
    link = make_link(company, owner, branch=second)
    second.is_active = False
    second.save()

    assert finish(opened(link)).status == Membership.Status.PENDING


# Making and changing links -------------------------------------------------------------------


def test_making_a_link_is_audited(company, member):
    owner = member.registered(company, "Owner")

    link = make_link(company, owner, max_uses=30)

    assert link.created_by == owner
    assert link.start_param == f"j_{link.code}"
    assert AuditLog.objects.filter(action=MemberAction.LINK_CREATED, target_id=link.pk).exists()


def test_a_link_needs_a_branch_when_the_company_has_several(company, member):
    owner = member.registered(company, "Owner")
    BranchFactory(company=company, name="Yunusobod")

    with pytest.raises(DomainError, match="branch"):
        make_link(company, owner)
    # Asking first, the approver picks the branch later.
    assert make_link(company, owner, auto_approve=False).branch is None


def test_a_link_can_only_give_a_role_its_maker_may_give(company, member):
    head = AccessRoleFactory(company=company, permissions=[Perm.MEMBERS_APPROVE, Perm.BRANCHES_ALL])
    approver = member.registered(company, head.name)
    manager_role = AccessRole.objects.get(company=company, name="Manager")

    with pytest.raises(DomainError, match="permissions you have yourself"):
        make_link(company, approver, role=manager_role)


def test_a_link_never_makes_people_owners(company, member):
    owner = member.registered(company, "Owner")

    with pytest.raises(DomainError, match="owners"):
        make_link(company, owner, role=AccessRole.objects.get(company=company, is_owner=True))


def test_a_branch_manager_makes_links_for_their_branches_only(company, member):
    member.registered(company, "Owner")
    mine = company.branches.first()
    other = BranchFactory(company=company, name="Yunusobod")
    # Enough to give the default role (Employee: finance.claim).
    role = AccessRoleFactory(
        company=company, permissions=[Perm.MEMBERS_APPROVE, Perm.FINANCE_CLAIM]
    )
    head = member.registered(company, role.name, home_branch=mine)
    head.branches.add(mine)

    with pytest.raises(DomainError, match="branches you manage"):
        make_link(company, head, branch=other)
    with pytest.raises(DomainError, match="your branches"):
        make_link(company, head, auto_approve=False)
    link = make_link(company, head, branch=mine)
    assert join_links.may_edit(head, link)


def test_people_without_approval_rights_make_no_links(company, member):
    worker = member.registered(company)

    with pytest.raises(PermissionDenied):
        make_link(company, worker)


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"name": "  "}, "name"),
        ({"max_uses": 0}, "from 1 to 500"),
        ({"max_uses": 501}, "from 1 to 500"),
        ({"expires_at": "past"}, "future"),
        ({"expires_at": "too far"}, "at most a year"),
    ],
)
def test_bad_values_are_refused(company, member, fields, message):
    owner = member.registered(company, "Owner")
    now = timezone.now()
    if fields.get("expires_at") == "past":
        fields["expires_at"] = now - timedelta(minutes=1)
    elif fields.get("expires_at") == "too far":
        fields["expires_at"] = now + timedelta(days=400)

    with pytest.raises(DomainError, match=message):
        make_link(company, owner, **fields)


def test_changing_stopping_and_deleting_a_link(company, member):
    owner = member.registered(company, "Owner")
    link = make_link(company, owner)
    joined = finish(opened(link))

    join_links.update_link(link, by=owner, name="Morning shift", max_uses=10)
    link.refresh_from_db()
    assert (link.name, link.max_uses) == ("Morning shift", 10)
    join_links.update_link(link, by=owner, is_active=False)
    join_links.update_link(link, by=owner, is_active=True)
    actions = list(
        AuditLog.objects.filter(target_type="joinlink", target_id=link.pk)
        .order_by("pk")
        .values_list("action", flat=True)
    )
    assert actions == [
        MemberAction.LINK_CREATED,
        MemberAction.LINK_CHANGED,
        MemberAction.LINK_STOPPED,
        MemberAction.LINK_RESUMED,
    ]

    join_links.delete_link(link, by=owner)
    joined.refresh_from_db()
    assert joined.status == Membership.Status.APPROVED  # people who joined stay
    assert joined.join_link == link  # and so does the row, out of every list
    assert not join_links.visible_links(owner).filter(pk=link.pk).exists()
    with pytest.raises(DomainError, match="invalid"):
        join_links.find(link.start_param)


# The note to approvers -------------------------------------------------------------------


def test_approvers_hear_about_a_burst_of_joins_in_one_note(
    company, member, django_capture_on_commit_callbacks
):
    owner = member.registered(company, "Owner")
    manager = member.registered(company, "Manager")
    link = make_link(company, owner, max_uses=20)
    people = [opened(link) for _ in range(3)]

    for index, membership in enumerate(people):
        finish(membership, first_name=f"Person{index}")
    with django_capture_on_commit_callbacks(execute=True):
        count = join_links.report_joins(link.pk)

    assert count == 3
    notes = Notification.objects.filter(kind=join_links.REPORT_KIND)
    assert {note.recipient_id for note in notes} == {owner.pk, manager.pk}
    note = notes.get(recipient=owner)
    assert note.title == "3 people joined through «Staff meeting»"
    assert "Person0 Karimov" in note.body
    assert "Joined: 3 of 20" in note.body
    # Nobody new since: no second note.
    assert join_links.report_joins(link.pk) == 0


def test_a_branch_head_hears_only_about_links_of_their_branches(company, member):
    owner = member.registered(company, "Owner")
    mine = company.branches.first()
    other = BranchFactory(company=company, name="Yunusobod")
    role = AccessRoleFactory(company=company, permissions=[Perm.MEMBERS_APPROVE])
    head = member.registered(company, role.name, home_branch=mine)
    head.branches.add(mine)
    link = make_link(company, owner, branch=other)
    finish(opened(link))

    join_links.report_joins(link.pk)

    recipients = set(
        Notification.objects.filter(kind=join_links.REPORT_KIND).values_list(
            "recipient_id", flat=True
        )
    )
    assert recipients == {owner.pk}


def test_groups_get_one_post_for_people_who_joined_together(
    company, member, django_capture_on_commit_callbacks, monkeypatch
):
    owner = member.registered(company, "Owner")
    group = TelegramGroup.objects.create(
        company=company, chat_id=-100123, title="Team", events=[GroupEvent.MEMBERS]
    )
    posts = []
    monkeypatch.setattr(
        "apps.groups.tasks.queue_post", lambda group_id, message, *a: posts.append(message)
    )
    link = make_link(company, owner)
    for index in range(2):  # approving queues no post of its own (callbacks aren't run here)
        finish(opened(link), first_name=f"Person{index}")

    with django_capture_on_commit_callbacks(execute=True):
        join_links.report_joins(link.pk)

    [(text, _markup)] = posts
    assert "2 new people joined the team" in text
    assert "Person0 Karimov" in text and "Person1 Karimov" in text
    assert group.is_active


def test_approving_through_a_link_queues_the_note_not_a_post_each(
    company, member, django_capture_on_commit_callbacks, monkeypatch
):
    owner = member.registered(company, "Owner")
    link = make_link(company, owner)
    queued, announced = [], []
    monkeypatch.setattr("apps.members.tasks.queue_link_report", queued.append)
    monkeypatch.setattr("apps.groups.tasks.announce_member.delay", lambda pk: announced.append(pk))

    with django_capture_on_commit_callbacks(execute=True):
        finish(opened(link))

    assert queued == [link.pk]
    assert announced == []


def test_the_note_waits_for_the_burst(monkeypatch, settings):
    from apps.members import tasks

    calls = []
    monkeypatch.setattr(
        tasks.report_link_joins, "apply_async", lambda args, countdown: calls.append(countdown)
    )

    tasks.queue_link_report(424242)
    tasks.queue_link_report(424242)  # a second join within the delay rides along

    assert calls == [tasks.LINK_REPORT_DELAY]


# Deciding many requests at once ------------------------------------------------------------


def asking(company, **fields):
    fields.setdefault("onboarded_at", timezone.now())
    return MembershipFactory(company=company, user__phone="+998901239988", **fields)


def test_many_requests_are_approved_in_one_go(company, member):
    owner = member.registered(company, "Owner")
    cashier = AccessRole.objects.get(company=company, name="Cashier")
    first, second = asking(company), asking(company)
    not_ready = asking(company, onboarded_at=None)

    results = services.decide_many(
        company,
        by=owner,
        ids=[first.pk, second.pk, not_ready.pk, 999999],
        approve_them=True,
        role=cashier,
    )

    assert [row["ok"] for row in results] == [True, True, False, False]
    assert "filled in their details" in results[2]["detail"]
    assert "no longer exists" in results[3]["detail"]
    for row in (first, second):
        row.refresh_from_db()
        assert row.status == Membership.Status.APPROVED
        assert row.role == cashier


def test_one_refusal_doesnt_stop_the_rest(company, member):
    head = AccessRoleFactory(company=company, permissions=[Perm.MEMBERS_APPROVE, Perm.BRANCHES_ALL])
    approver = member.registered(company, head.name)
    manager_role = AccessRole.objects.get(company=company, name="Manager")
    preset = asking(company, role=manager_role)  # a role on the request the approver can't give
    plain = asking(company)

    results = services.decide_many(
        company, by=approver, ids=[preset.pk, plain.pk], approve_them=True
    )

    assert [row["ok"] for row in results] == [False, True]
    assert results[0]["detail"]


def test_many_requests_are_rejected_in_one_go(company, member):
    owner = member.registered(company, "Owner")
    first, second = asking(company), asking(company)

    results = services.decide_many(
        company, by=owner, ids=[first.pk, second.pk], approve_them=False, reason="Full team"
    )

    assert all(row["ok"] for row in results)
    first.refresh_from_db()
    assert first.status == Membership.Status.REJECTED
