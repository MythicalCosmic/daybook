"""The employee bot's people pickers with departments: a card's "Someone else" still offers the
member's branch (the server decides per task)."""

import pytest
from asgiref.sync import sync_to_async

from apps.members.models import Membership
from apps.projects import services as project_services
from apps.tasks import services
from bot.handlers.member.tasks import _colleagues

pytestmark = pytest.mark.django_db(transaction=True)


def fresh(member: Membership) -> Membership:
    return Membership.objects.select_related("role", "company", "user").get(pk=member.pk)


async def test_a_project_lead_still_has_people_to_hand_their_card_to(company, member):
    """The card's "Someone else" shows for whoever may manage it (its giver among them), and its
    picker is `_colleagues`, now `departments.assignable`: without tasks.assign that is the
    member's department team only. A project lead without tasks.assign (who may give cards to
    the project's people, `_ensure_may_assign`) now gets an empty list; before, the people of
    their branches. The same goes for anyone else answering from the card without
    tasks.assign."""

    def setup():
        branch = company.branches.first()
        owner = member.registered(company, "Owner")
        lead, worker, other = (member.registered(company, home_branch=branch) for _ in range(3))
        for person in (lead, worker, other):
            person.branches.add(branch)
        project = project_services.create_project(
            company, by=owner, name="Yangi filial", lead=lead, member_ids=[worker.pk, other.pk]
        )
        task = services.create_task(
            by=fresh(lead), assignee=fresh(worker), title="Vitrina", project=project
        )
        return fresh(lead), task, other

    lead, task, other = await sync_to_async(setup)()

    people = await _colleagues(lead, exclude=task.assignee_id)

    def hand_over():
        return services.reassign_task(task, by=fresh(lead), assignee=fresh(other))

    # The server lets the lead hand it to them (passes)...
    assert (await sync_to_async(hand_over)()).assignee_id == other.pk
    # ...but the bot offered nobody.
    assert other.pk in {person.pk for person in people}
