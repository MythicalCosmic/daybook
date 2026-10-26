"""Team links: the rules a review pinned down (places per person, deleting a link mid-burst,
branches and roles checked at every join, the owner API's error shapes)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.companies.tests.factories import BranchFactory
from apps.core.exceptions import DomainError
from apps.groups.models import GroupEvent, TelegramGroup
from apps.inbox.models import Notification
from apps.members import join_links, services, tasks
from apps.members.models import AccessRole, JoinLink, Membership
from apps.members.permissions import Perm
from apps.members.tests.factories import AccessRoleFactory, MembershipFactory

pytestmark = pytest.mark.django_db


def make_link(company, by, **fields):
    fields.setdefault("name", "Staff meeting")
    return join_links.create_link(company, by=by, **fields)


def opened(link):
    user = UserFactory(phone="+998901112233")
    membership, _admitted = join_links.open_link(user, link.start_param)
    return membership


def finish(membership, first_name="Aziz"):
    return services.complete_onboarding(
        membership, first_name=first_name, last_name="Karimov", position_id=None
    )


def branch_head(company, member):
    """A head of the company's first branch who may approve and give the Employee role only."""
    mine = company.branches.first()
    role = AccessRoleFactory(
        company=company, permissions=[Perm.MEMBERS_APPROVE, Perm.FINANCE_CLAIM]
    )
    head = member.registered(company, role.name, home_branch=mine)
    head.branches.add(mine)
    return head, mine


# 1. Places: one person can use up a link's places by switching between links ---------------


def test_switching_back_and_forth_between_links_uses_one_place(company, member):
    owner = member.registered(company, "Owner")
    meeting = make_link(company, owner, name="Meeting", auto_approve=False, max_uses=2)
    other = make_link(company, owner, name="Other", auto_approve=False)
    request = finish(opened(meeting))  # 1 of 2: fair

    join_links.open_link(request.user, other.start_param)
    join_links.open_link(request.user, meeting.start_param)  # the same person, again

    meeting.refresh_from_db()
    assert meeting.uses == 1, "one person took two of the link's places"
    opened(meeting)  # someone new can still use the second place


def test_a_former_member_scanning_two_links_doesnt_fill_them(company, member):
    owner = member.registered(company, "Owner")
    morning = make_link(company, owner, name="Morning", max_uses=2)
    evening = make_link(company, owner, name="Evening", max_uses=2)
    returning = MembershipFactory(
        company=company, status=Membership.Status.LEFT, onboarded_at=timezone.now()
    )
    audit.record(
        AuditLog.Action.MEMBER_LEFT, company_id=company.pk, actor=owner.user, target=returning
    )

    for link in (morning, evening, morning):  # never let in, so they can go on and on
        join_links.open_link(returning.user, link.start_param)

    morning.refresh_from_db()
    assert morning.uses <= 1
    assert morning.status_at(timezone.now()) == JoinLink.Status.ACTIVE


# 2. The note and the group post are lost when the link is deleted within the burst ---------


def test_deleting_the_link_right_after_the_meeting_still_tells_approvers_and_groups(
    company, member, django_capture_on_commit_callbacks, monkeypatch
):
    owner = member.registered(company, "Owner")
    manager = member.registered(company, "Manager")
    TelegramGroup.objects.create(
        company=company, chat_id=-100123, title="Team", events=[GroupEvent.MEMBERS]
    )
    posts = []
    monkeypatch.setattr(
        "apps.groups.tasks.queue_post", lambda group_id, message, *a: posts.append(message)
    )
    queued = []  # the burst's note waits 90 s (tests run tasks at once, so hold it here)
    monkeypatch.setattr("apps.members.tasks.queue_link_report", queued.append)
    link = make_link(company, owner)
    with django_capture_on_commit_callbacks(execute=True):
        for index in range(2):
            finish(opened(link), first_name=f"Person{index}")

    join_links.delete_link(link, by=owner)  # "nobody else may join": done with it
    with django_capture_on_commit_callbacks(execute=True):
        for link_id in dict.fromkeys(queued):
            tasks.report_link_joins(link_id)  # 90 s later

    assert Notification.objects.filter(kind=join_links.REPORT_KIND, recipient=manager).exists(), (
        "the manager never hears that two people joined"
    )
    assert posts, "the team's group never hears about the new people"


# 3. A link without a branch adds people with no branch once a second branch opens ----------


def test_a_link_made_with_one_branch_never_adds_people_without_a_branch(company, member):
    owner = member.registered(company, "Owner")
    link = make_link(company, owner)  # one branch: the rule asks for none
    BranchFactory(company=company, name="Yunusobod")  # a second pharmacy opens

    joined = finish(opened(link))

    # Contract: auto_approve needs a branch when the company has 2+ branches. Either the
    # person waits for an approver to pick it, or they get one; never no branch at all.
    assert joined.status == Membership.Status.PENDING or joined.home_branch_id is not None


# 4. An edit by someone else is checked against the editor, the join against the maker ------


def test_a_link_another_approver_changed_still_lets_people_in(company, member):
    owner = member.registered(company, "Owner")
    head, mine = branch_head(company, member)
    link = make_link(company, head, branch=mine)
    cashier = AccessRole.objects.get(company=company, name="Cashier")  # beyond the head

    join_links.update_link(link, by=owner, role=cashier)  # accepted: the owner may give it
    joined = finish(opened(link))

    assert joined.status == Membership.Status.APPROVED, (
        "the owner's change was accepted and the link shows as active, yet every join is "
        "now refused (checked against the head, who can't give Cashier)"
    )


# 5. role: null = the default role, which is not re-checked against the maker ----------------


def test_a_link_without_a_role_rechecks_the_default_role_against_its_maker(company, member):
    member.registered(company, "Owner")
    head, mine = branch_head(company, member)
    link = make_link(company, head, branch=mine)  # the default role today: Employee
    AccessRole.objects.filter(company=company).update(is_default=False)
    AccessRole.objects.filter(company=company, name="Cashier").update(is_default=True)

    joined = finish(opened(link))

    # Contract: "the role is re-checked against the creator's permissions at every join: if
    # the creator ... may no longer give that role, the person becomes an ordinary request".
    assert joined.status == Membership.Status.PENDING, f"let in as {joined.role}"


# Contract details of the owner API ----------------------------------------------------------


def url(company, suffix=""):
    return f"/api/v1/owner/companies/{company.pk}/join-links/{suffix}"


def test_rule_errors_are_400_with_a_detail_as_the_contract_says(owner_api, company, member):
    head, mine = branch_head(company, member)
    head.role.permissions = [*head.role.permissions, Perm.DASHBOARD_ACCESS]
    head.role.save()
    other = BranchFactory(company=company, name="Yunusobod")
    cashier = AccessRole.objects.get(company=company, name="Cashier")
    api = owner_api(head)

    role_beyond = api.post(
        url(company), {"name": "M", "branch_id": mine.pk, "role_id": cashier.pk}, format="json"
    )
    not_my_branch = api.post(url(company), {"name": "M", "branch_id": other.pk}, format="json")

    # "business rules (branch required, role not allowed, branch outside your branches) →
    # 400 {"detail": "message"}"
    assert (role_beyond.status_code, not_my_branch.status_code) == (400, 400)


def test_a_past_end_comes_back_on_its_field(owner_api, company, member):
    owner = member.registered(company, "Owner")

    response = owner_api(owner).post(
        url(company),
        {"name": "M", "expires_at": (timezone.now() - timedelta(hours=1)).isoformat()},
        format="json",
    )

    # "serializer validation → 400 {"<field>": ["message"]} (name, max_uses, expires_at, ids…)"
    assert response.status_code == 400
    assert "expires_at" in response.data, response.data


def test_bulk_results_have_one_row_per_id_sent(owner_api, company, member):
    owner = member.registered(company, "Owner")
    first = MembershipFactory(company=company, onboarded_at=timezone.now())

    response = owner_api(owner).post(
        f"/api/v1/owner/companies/{company.pk}/join-requests/bulk/",
        {"ids": [first.pk, first.pk], "action": "reject"},
        format="json",
    )

    # "results: one per id, in the order sent"
    assert len(response.data["results"]) == 2, response.data


def test_the_bot_promises_no_waiting_only_when_the_link_can_really_let_them_in(company, member):
    from apps.members import bot_messages

    manager = member.registered(company, "Manager")
    link = make_link(company, manager)
    manager.role = AccessRole.objects.get(company=company, name="Employee")  # can't approve now
    manager.save()

    text, _markup = bot_messages.status(opened(link))

    assert "no waiting" not in text, "they will wait: the link's maker may not approve anyone"


def test_someone_waiting_on_a_link_that_filled_up_hears_where_they_stand(company, member):
    """Someone whose request came through a link (they used its last place) opens it again to
    see how things are: they're told "no places left, ask your manager for a new one"."""
    owner = member.registered(company, "Owner")
    link = make_link(company, owner, auto_approve=False, max_uses=1)
    request = finish(opened(link))

    try:
        membership, admitted = join_links.open_link(request.user, link.start_param)
    except DomainError as exc:
        pytest.fail(f"someone already waiting on the link is told: {exc}")
    assert (membership, admitted) == (request, False)


# Queries (controls: these pass) ---------------------------------------------------------------


def test_the_list_of_links_costs_the_same_for_two_or_twelve_links(owner_api, company, member):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    owner = member.registered(company, "Owner")
    api = owner_api(owner)

    def count():
        with CaptureQueriesContext(connection) as queries:
            assert api.get(url(company)).status_code == 200
        return len(queries)

    for index in range(2):
        make_link(company, owner, name=f"L{index}")
    few = count()
    for index in range(10):
        make_link(company, owner, name=f"M{index}", max_uses=5)
    assert count() == few


def test_join_requests_with_links_cost_the_same_for_two_or_twelve(owner_api, company, member):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    owner = member.registered(company, "Owner")
    link = make_link(company, owner, auto_approve=False)
    api = owner_api(owner)

    def count():
        with CaptureQueriesContext(connection) as queries:
            response = api.get(f"/api/v1/owner/companies/{company.pk}/join-requests/")
            assert response.status_code == 200
        return len(queries)

    for _ in range(2):
        finish(opened(link))
    few = count()
    for _ in range(10):
        finish(opened(link))
    assert count() == few
