"""Owner endpoints of the knowledge base: permissions, tenancy, branch scope, hidden fields."""

import io
from datetime import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.companies.models import Branch
from apps.knowledge import services
from apps.knowledge.models import Page
from apps.knowledge.tests.factories import PageAckFactory, PageFactory, SpaceFactory
from apps.members.models import AccessRole

pytestmark = pytest.mark.django_db


def url(company, path="") -> str:
    return f"/api/v1/owner/companies/{company.pk}/knowledge/{path}"


@pytest.fixture
def editor(company, member):
    """A manager whose role also manages the knowledge base, limited to one branch."""
    role = AccessRole.objects.create(
        company=company,
        name="Editor",
        permissions=["dashboard.access", "knowledge.manage", "members.view"],
    )
    return member(company, role.name)


def png() -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (90, 120, 70)).save(buffer, format="PNG")
    return SimpleUploadedFile("pic.png", buffer.getvalue(), content_type="image/png")


# Permissions and tenancy ----------------------------------------------------------------


def test_reading_needs_only_dashboard_access(company, manager, owner_api):
    space = SpaceFactory(company=company)
    PageFactory(space=space)

    assert owner_api(manager).get(url(company, "spaces/")).status_code == 200
    assert owner_api(manager).get(url(company, "pages/")).status_code == 200
    assert owner_api(manager).get(url(company, "overview/")).status_code == 200


def test_employees_without_dashboard_access_get_403(company, cashier, owner_api):
    assert owner_api(cashier).get(url(company, "spaces/")).status_code == 403


def test_writing_needs_knowledge_manage(company, manager, owner, owner_api):
    space = SpaceFactory(company=company)
    page = PageFactory(space=space)
    denied = owner_api(manager)

    assert denied.post(url(company, "spaces/"), {"name": "Kassa"}, format="json").status_code == 403
    assert (
        denied.post(
            url(company, "pages/"), {"space": space.pk, "title": "x"}, format="json"
        ).status_code
        == 403
    )
    assert (
        denied.patch(url(company, f"pages/{page.pk}/"), {"title": "y"}, format="json").status_code
        == 403
    )
    assert denied.post(url(company, f"pages/{page.pk}/publish/")).status_code == 403
    assert denied.get(url(company, f"pages/{page.pk}/readers/")).status_code == 403
    assert denied.get(url(company, f"pages/{page.pk}/versions/")).status_code == 403
    assert (
        denied.post(
            url(company, f"pages/{page.pk}/links/"),
            {"target_type": "routine", "target_id": 1},
            format="json",
        ).status_code
        == 403
    )
    assert (
        denied.patch(
            url(company, "settings/"), {"notify_on_publish": False}, format="json"
        ).status_code
        == 403
    )

    created = owner_api(owner).post(
        url(company, "spaces/"), {"name": "Kassa", "icon": "💰"}, format="json"
    )
    assert created.status_code == 201
    assert created.data["name"] == "Kassa"


def test_another_companys_records_are_404(company, other_company, owner, owner_api, member):
    foreign_space = SpaceFactory(company=other_company)
    foreign_page = PageFactory(space=foreign_space)
    client = owner_api(owner)

    assert client.get(url(company, f"pages/{foreign_page.pk}/")).status_code == 404
    assert client.get(url(company, f"spaces/{foreign_space.pk}/tree/")).status_code == 404
    assert client.post(url(company, f"pages/{foreign_page.pk}/publish/")).status_code == 404
    assert (
        client.post(
            url(company, "pages/"), {"space": foreign_space.pk, "title": "x"}, format="json"
        ).status_code
        == 404
    )
    # And the other company's own URL doesn't open for this owner at all.
    assert client.get(url(other_company, "spaces/")).status_code == 404


def test_a_mini_app_token_gets_401(company, owner, api_as):
    assert api_as(owner).get(url(company, "spaces/")).status_code == 401


# Pages ----------------------------------------------------------------------------------


def test_create_save_publish_flow(company, owner, owner_api):
    space = SpaceFactory(company=company)
    client = owner_api(owner)

    created = client.post(
        url(company, "pages/"),
        {
            "space": space.pk,
            "title": "Opening",
            "emoji": "🔓",
            "body": "<p>Step one</p><script>x</script>",
        },
        format="json",
    )
    assert created.status_code == 201
    page_id = created.data["id"]
    assert created.data["body"] == "<p>Step one</p>"
    assert created.data["published"] is False and created.data["can_edit"] is True

    saved = client.patch(
        url(company, f"pages/{page_id}/"),
        {"body": "<p>Step one</p><p>Step two</p>", "base_version": 1, "note": "Two steps"},
        format="json",
    )
    assert saved.status_code == 200 and saved.data["version"] == 2

    stale = client.patch(
        url(company, f"pages/{page_id}/"), {"body": "<p>old</p>", "base_version": 1}, format="json"
    )
    assert stale.status_code == 400

    published = client.post(
        url(company, f"pages/{page_id}/publish/"), {"notify": False}, format="json"
    )
    assert published.status_code == 200 and published.data["published"] is True

    versions = client.get(url(company, f"pages/{page_id}/versions/"))
    assert [row["version"] for row in versions.data] == [2, 1]
    assert versions.data[0]["current"] is True
    old = client.get(url(company, f"pages/{page_id}/versions/1/"))
    assert old.data["body"] == "<p>Step one</p>"
    restored = client.post(url(company, f"pages/{page_id}/versions/1/restore/"))
    assert restored.data["version"] == 3


def test_tree_shows_drafts_only_to_managers(company, owner, manager, owner_api):
    space = SpaceFactory(company=company)
    parent = PageFactory(space=space, title="Parent")
    PageFactory(space=space, parent=parent, title="Child")
    PageFactory(space=space, title="Draft", published=False)

    managed = owner_api(owner).get(url(company, f"spaces/{space.pk}/tree/")).data
    read = owner_api(manager).get(url(company, f"spaces/{space.pk}/tree/")).data

    assert [node["title"] for node in managed] == ["Parent", "Draft"]
    assert managed[0]["children"][0]["title"] == "Child"
    assert [node["title"] for node in read] == ["Parent"]


def test_list_hides_drafts_and_read_counts_from_readers(
    company, owner, manager, owner_api, cashier
):
    space = SpaceFactory(company=company)
    live = PageFactory(space=space, require_ack=True)
    PageFactory(space=space, published=False, title="Secret draft")
    PageAckFactory(page=live, membership=cashier)

    as_reader = owner_api(manager).get(url(company, "pages/")).data["results"]
    as_editor = (
        owner_api(owner).get(url(company, "pages/"), {"status": "published"}).data["results"]
    )

    assert [row["id"] for row in as_reader] == [live.pk]
    assert as_reader[0]["read"] is None
    assert as_editor[0]["read"]["read"] == 1
    drafts = owner_api(owner).get(url(company, "pages/"), {"status": "draft"}).data["results"]
    assert [row["title"] for row in drafts] == ["Secret draft"]


def test_detail_hides_a_draft_from_readers(company, manager, owner_api):
    draft = PageFactory(space=SpaceFactory(company=company), published=False)

    assert owner_api(manager).get(url(company, f"pages/{draft.pk}/")).status_code == 404


def test_search_filter(company, owner, owner_api):
    space = SpaceFactory(company=company)
    PageFactory(space=space, title="Kassani ochish")
    PageFactory(space=space, title="Other", body="<p>Z-hisobot kassada</p>")
    PageFactory(space=space, title="Unrelated")

    found = owner_api(owner).get(url(company, "pages/"), {"q": "kassa"}).data["results"]

    assert {row["title"] for row in found} == {"Kassani ochish", "Other"}


def test_move_endpoint(company, owner, owner_api):
    space = SpaceFactory(company=company)
    first, second = PageFactory(space=space), PageFactory(space=space)

    response = owner_api(owner).post(
        url(company, f"pages/{second.pk}/move/"), {"parent": first.pk, "index": 0}, format="json"
    )

    assert response.status_code == 200
    assert response.data["breadcrumbs"] == [{"id": first.pk, "title": first.title, "emoji": ""}]


def test_ack_from_the_dashboard(company, manager, owner_api):
    page = PageFactory(space=SpaceFactory(company=company), require_ack=True)

    response = owner_api(manager).post(url(company, f"pages/{page.pk}/ack/"))

    assert response.status_code == 200 and response.data["version"] == 1
    detail = owner_api(manager).get(url(company, f"pages/{page.pk}/")).data
    assert detail["my_ack"]["current"] is True


# Readers and branch scope ---------------------------------------------------------------


def test_readers_are_limited_to_the_viewers_branches(company, editor, owner, owner_api, member):
    chilonzor = company.branches.first()
    yunusobod = Branch.objects.create(company=company, name="Yunusobod")
    editor.branches.set([chilonzor])
    near = member(company, "Employee", first_name="Alisher", home_branch=chilonzor)
    near.branches.set([chilonzor])
    far = member(company, "Employee", first_name="Nigora", home_branch=yunusobod)
    far.branches.set([yunusobod])
    page = PageFactory(space=SpaceFactory(company=company), require_ack=True)
    PageAckFactory(page=page, membership=far)

    scoped = owner_api(editor).get(url(company, f"pages/{page.pk}/readers/")).data
    everyone = owner_api(owner).get(url(company, f"pages/{page.pk}/readers/")).data

    scoped_ids = {row["member"]["id"] for row in scoped["results"]}
    assert near.pk in scoped_ids and far.pk not in scoped_ids
    assert far.pk in {row["member"]["id"] for row in everyone["results"]}
    statuses = {row["member"]["id"]: row["status"] for row in everyone["results"]}
    assert statuses[far.pk] == "read" and statuses[near.pk] == "unread"
    unread = owner_api(owner).get(url(company, f"pages/{page.pk}/readers/"), {"status": "unread"})
    assert far.pk not in {row["member"]["id"] for row in unread.data["results"]}


def test_readers_show_who_read_an_older_version(company, owner, owner_api, cashier):
    page = PageFactory(space=SpaceFactory(company=company), require_ack=True)
    PageAckFactory(page=page, membership=cashier, version=1)
    Page.objects.filter(pk=page.pk).update(version=2, ack_version=2)

    data = owner_api(owner).get(url(company, f"pages/{page.pk}/readers/")).data

    row = next(row for row in data["results"] if row["member"]["id"] == cashier.pk)
    assert row["status"] == "outdated" and row["version"] == 1
    assert data["counts"]["outdated"] == 1


def test_remind_endpoint(company, owner, owner_api, cashier):
    page = PageFactory(space=SpaceFactory(company=company), require_ack=True)

    response = owner_api(owner).post(url(company, f"pages/{page.pk}/remind/"))

    assert response.status_code == 200 and response.data["reminded"] >= 1


# Links ----------------------------------------------------------------------------------


def test_link_targets_skip_routine_tasks_and_say_whose(company, owner, manager, owner_api):
    from apps.tasks.models import TaskTemplate
    from apps.tasks.tests.factories import TaskFactory

    manager.first_name, manager.last_name = "Bekzod", "Mirzayev"
    manager.save(update_fields=["first_name", "last_name"])
    routine = TaskTemplate.objects.create(company=company, title="Close the till", due_time="22:00")
    TaskFactory(assignee=manager, created_by=owner, title="Close the till", template=routine)
    one_off = TaskFactory(
        assignee=manager,
        created_by=owner,
        title="Close the till early",
        due_at=timezone.make_aware(datetime(2026, 10, 21, 18, 0)),
    )

    targets = owner_api(owner).get(url(company, "link-targets/"), {"q": "close"}).data

    assert [(row["type"], row["id"]) for row in targets] == [
        ("routine", routine.pk),
        ("task", one_off.pk),
    ]
    assert targets[1]["subtitle"] == "Bekzod Mirzayev · 21.10"


def test_link_targets_links_and_linked(company, owner, manager, owner_api):
    from apps.tasks.models import TaskTemplate

    routine = TaskTemplate.objects.create(
        company=company, title="Opening checklist", due_time="09:00"
    )
    page = PageFactory(space=SpaceFactory(company=company))
    client = owner_api(owner)

    targets = client.get(url(company, "link-targets/"), {"q": "opening"}).data
    assert targets == [
        {"type": "routine", "id": routine.pk, "title": "Opening checklist", "subtitle": "09:00"}
    ]

    created = client.post(
        url(company, f"pages/{page.pk}/links/"),
        {"target_type": "routine", "target_id": routine.pk},
        format="json",
    )
    assert created.status_code == 201

    linked = owner_api(manager).get(
        url(company, "pages/linked/"), {"target_type": "routine", "target_id": routine.pk}
    )
    assert [row["page"]["id"] for row in linked.data] == [page.pk]
    assert client.get(url(company, f"pages/{page.pk}/")).data["links"][0]["target_title"] == (
        "Opening checklist"
    )

    deleted = client.delete(url(company, f"links/{created.data['id']}/"))
    assert deleted.status_code == 204


# Pictures -------------------------------------------------------------------------------


def test_uploaded_picture_shows_through_a_signed_link_for_readers_only(
    company, owner, owner_api, cashier, cook, cashier_position, client
):
    space = SpaceFactory(company=company, audience_all=False, positions=[cashier_position])
    uploaded = owner_api(owner).post(url(company, "images/"), {"file": png()}, format="multipart")
    assert uploaded.status_code == 201
    image_id = uploaded.data["id"]
    page = services.create_page(
        space,
        by=owner,
        title="With picture",
        body=f'<img data-image-id="{image_id}" alt="till"><p>Text</p>',
        publish=True,
        notify_readers=False,
    )

    body = owner_api(owner).get(url(company, f"pages/{page.pk}/")).data["body"]
    assert 'src="/api/v1/files/' in body

    from apps.core.files import signed_url
    from apps.knowledge.models import PageImage

    image = PageImage.objects.get(pk=image_id)
    as_cashier = signed_url(
        image.file, user=cashier.user, company_id=company.pk, check=f"knowledge.image:{image_id}"
    )
    as_cook = signed_url(
        image.file, user=cook.user, company_id=company.pk, check=f"knowledge.image:{image_id}"
    )
    assert client.get(as_cashier).status_code == 200
    assert client.get(as_cook).status_code == 404


def test_upload_refuses_svg(company, owner, owner_api):
    svg = SimpleUploadedFile("x.png", b"<svg onload='alert(1)'/>", content_type="image/png")

    response = owner_api(owner).post(url(company, "images/"), {"file": svg}, format="multipart")

    assert response.status_code == 400


# Overview and settings ------------------------------------------------------------------


def test_overview_lists_pages_that_need_readers(company, owner, owner_api, cashier, cook):
    page = PageFactory(space=SpaceFactory(company=company), require_ack=True, title="Rules")
    PageAckFactory(page=page, membership=cashier)

    data = owner_api(owner).get(url(company, "overview/")).data

    assert data["counts"]["require_ack"] == 1
    assert data["attention"][0]["id"] == page.pk
    assert data["attention"][0]["read"]["read"] == 1


def test_settings_round_trip(company, owner, owner_api):
    client = owner_api(owner)

    assert client.get(url(company, "settings/")).data == {
        "notify_on_publish": True,
        "remind_unread_after_hours": 24,
    }
    changed = client.patch(
        url(company, "settings/"), {"remind_unread_after_hours": 48}, format="json"
    )
    assert changed.data["remind_unread_after_hours"] == 48
