"""Mini app endpoints of the knowledge base: what each person reads, and "I've read it"."""

import pytest

from apps.knowledge.models import PageAck, PageLink
from apps.knowledge.tests.factories import PageFactory, SpaceFactory
from apps.members.models import Membership
from apps.tasks.tests.factories import TaskFactory, TaskTemplateFactory

pytestmark = pytest.mark.django_db


def url(company, path="") -> str:
    return f"/api/v1/companies/{company.pk}/knowledge/{path}"


@pytest.fixture
def shelves(company, cashier_position):
    everyone = SpaceFactory(company=company, name="Handbook")
    till = SpaceFactory(
        company=company, name="Till", audience_all=False, positions=[cashier_position]
    )
    return everyone, till


def test_home_shows_my_spaces_and_what_to_read(company, api_as, cashier, courier, shelves):
    everyone, till = shelves
    rules = PageFactory(space=everyone, title="Rules", require_ack=True)
    PageFactory(space=till, title="Close the till", require_ack=True)
    PageFactory(space=everyone, title="Draft", published=False)

    as_cashier = api_as(cashier).get(url(company)).data
    as_courier = api_as(courier).get(url(company)).data

    assert [space["name"] for space in as_cashier["spaces"]] == ["Handbook", "Till"]
    assert {page["title"] for page in as_cashier["to_read"]} == {"Rules", "Close the till"}
    assert [space["name"] for space in as_courier["spaces"]] == ["Handbook"]
    assert [page["id"] for page in as_courier["to_read"]] == [rules.pk]
    assert "Draft" not in {page["title"] for page in as_cashier["recent"]}


def test_a_space_meant_for_others_is_404(company, api_as, courier, shelves):
    _everyone, till = shelves

    assert api_as(courier).get(url(company, f"spaces/{till.pk}/")).status_code == 404


def test_space_tree_has_only_published_pages(company, api_as, cashier, shelves):
    everyone, _till = shelves
    parent = PageFactory(space=everyone, title="Parent")
    PageFactory(space=everyone, parent=parent, title="Child")
    PageFactory(space=everyone, title="Draft", published=False)

    data = api_as(cashier).get(url(company, f"spaces/{everyone.pk}/")).data

    assert [node["title"] for node in data["pages"]] == ["Parent"]
    assert data["pages"][0]["children"][0]["title"] == "Child"
    assert data["space"]["counts"]["pages"] == 2


def test_managers_dont_see_drafts_in_the_app_either(company, api_as, owner, shelves):
    everyone, _till = shelves
    draft = PageFactory(space=everyone, published=False)

    assert api_as(owner).get(url(company, f"pages/{draft.pk}/")).status_code == 404


def test_read_a_page_and_confirm(company, api_as, cashier, shelves):
    everyone, _till = shelves
    page = PageFactory(space=everyone, require_ack=True)
    client = api_as(cashier)

    detail = client.get(url(company, f"pages/{page.pk}/")).data
    assert detail["my_ack"] is None and detail["can_edit"] is False

    confirmed = client.post(url(company, f"pages/{page.pk}/ack/"))
    assert confirmed.status_code == 200
    assert PageAck.objects.filter(page=page, membership=cashier, version=1).exists()
    assert client.get(url(company, f"pages/{page.pk}/")).data["my_ack"]["current"] is True
    assert client.get(url(company)).data["to_read"] == []


def test_cant_confirm_a_page_meant_for_others(company, api_as, courier, shelves):
    _everyone, till = shelves
    page = PageFactory(space=till, require_ack=True)

    assert api_as(courier).post(url(company, f"pages/{page.pk}/ack/")).status_code == 404


def test_search_finds_only_my_pages(company, api_as, courier, shelves):
    everyone, till = shelves
    PageFactory(space=everyone, title="Kassa qoidalari")
    PageFactory(space=till, title="Kassani yopish")

    found = api_as(courier).get(url(company, "search/"), {"q": "kassa"}).data

    assert [row["title"] for row in found] == ["Kassa qoidalari"]
    assert api_as(courier).get(url(company, "search/"), {"q": "k"}).data == []


def test_how_to_do_this_for_a_task(company, api_as, cashier, courier, shelves):
    _everyone, till = shelves
    open_page = PageFactory(space=till, title="Open the till")
    task = TaskFactory(assignee=cashier, title="Open the Chilonzor till")
    PageLink.objects.create(company=company, page=open_page, target_type="task", target_id=task.pk)
    query = {"target_type": "task", "target_id": task.pk}

    mine = api_as(cashier).get(url(company, "linked/"), query)
    theirs = api_as(courier).get(url(company, "linked/"), query)

    assert [row["page"]["title"] for row in mine.data] == ["Open the till"]
    assert theirs.data == []
    assert api_as(courier).get(url(company, "linked/"), {"target_type": "x"}).status_code == 400


def test_links_never_show_someone_elses_task(
    company, api_as, member, cashier, shelves, cashier_position
):
    """A colleague reading the same page doesn't see the title of a task that isn't theirs;
    routines (company-wide) show to every reader."""
    _everyone, till = shelves
    colleague = member(company, "Employee", position=cashier_position, first_name="Nigora")
    open_page = PageFactory(space=till, title="Open the till")
    task = TaskFactory(assignee=cashier, title="Madina: recount the float")
    routine = TaskTemplateFactory(company=company, title="Opening checklist")
    PageLink.objects.create(company=company, page=open_page, target_type="task", target_id=task.pk)
    PageLink.objects.create(
        company=company, page=open_page, target_type="routine", target_id=routine.pk
    )

    page_for_her = api_as(colleague).get(url(company, f"pages/{open_page.pk}/")).data
    page_for_madina = api_as(cashier).get(url(company, f"pages/{open_page.pk}/")).data
    by_task = api_as(colleague).get(
        url(company, "linked/"), {"target_type": "task", "target_id": task.pk}
    )

    assert [link["target_type"] for link in page_for_her["links"]] == ["routine"]
    assert {link["target_type"] for link in page_for_madina["links"]} == {"task", "routine"}
    assert by_task.data == []


def test_other_companies_and_strangers_get_404(company, other_company, api_as, member, shelves):
    everyone, _till = shelves
    page = PageFactory(space=everyone)
    outsider = member(other_company)
    pending = member(company, status=Membership.Status.PENDING)

    assert api_as(outsider).get(url(company, f"pages/{page.pk}/")).status_code == 404
    assert api_as(pending).get(url(company)).status_code == 404


def test_suspended_people_are_turned_away(company, api_as, cashier, shelves):
    Membership.objects.filter(pk=cashier.pk).update(status=Membership.Status.SUSPENDED)

    response = api_as(cashier).get(url(company))

    assert response.status_code == 403 and response.data["code"] == "suspended"
