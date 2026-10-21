"""Edge cases found in review: tenancy on every endpoint, list query counts, announcements of
pages nobody can open yet, moves of archived pages, audit of reordering, the reminder clock."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.inbox.models import Notification
from apps.knowledge import queries, services
from apps.knowledge.models import Page, PageLink
from apps.knowledge.tests.factories import PageAckFactory, PageFactory, SpaceFactory
from apps.tasks.tests.factories import TaskTemplateFactory

pytestmark = pytest.mark.django_db


def owner_url(company, path="") -> str:
    return f"/api/v1/owner/companies/{company.pk}/knowledge/{path}"


def app_url(company, path="") -> str:
    return f"/api/v1/companies/{company.pk}/knowledge/{path}"


# Tenancy: another company's ids answer 404 everywhere ------------------------------------


def test_every_owner_endpoint_hides_another_companys_rows(company, other_company, owner, owner_api):
    space = SpaceFactory(company=other_company)
    page = PageFactory(space=space)
    services.save_page(page, by=None, body="<p>Second version</p>")
    routine = TaskTemplateFactory(company=other_company, title="Their routine")
    link = PageLink.objects.create(
        company=other_company, page=page, target_type="routine", target_id=routine.pk
    )
    client = owner_api(owner)
    reads = [
        f"spaces/{space.pk}/",
        f"spaces/{space.pk}/tree/",
        f"pages/{page.pk}/",
        f"pages/{page.pk}/versions/",
        f"pages/{page.pk}/versions/1/",
        f"pages/{page.pk}/readers/",
        f"pages/{page.pk}/links/",
    ]
    writes = [
        ("patch", f"spaces/{space.pk}/", {"name": "Mine now"}),
        ("post", f"spaces/{space.pk}/archive/", {}),
        ("post", f"spaces/{space.pk}/restore/", {}),
        ("patch", f"pages/{page.pk}/", {"title": "Mine now"}),
        ("post", f"pages/{page.pk}/publish/", {}),
        ("post", f"pages/{page.pk}/unpublish/", {}),
        ("post", f"pages/{page.pk}/move/", {"index": 0}),
        ("post", f"pages/{page.pk}/archive/", {}),
        ("post", f"pages/{page.pk}/restore/", {}),
        ("post", f"pages/{page.pk}/ack/", {}),
        ("post", f"pages/{page.pk}/versions/1/restore/", {}),
        ("post", f"pages/{page.pk}/remind/", {}),
        ("post", f"pages/{page.pk}/links/", {"target_type": "routine", "target_id": routine.pk}),
        ("delete", f"links/{link.pk}/", None),
    ]

    for path in reads:
        assert client.get(owner_url(company, path)).status_code == 404, path
    for method, path, body in writes:
        response = getattr(client, method)(owner_url(company, path), body, format="json")
        assert response.status_code == 404, path

    # Ids of the other company inside a payload are refused too.
    mine = SpaceFactory(company=company)
    my_page = PageFactory(space=mine)
    assert (
        client.post(
            owner_url(company, "pages/"),
            {"space": mine.pk, "parent": page.pk, "title": "x"},
            format="json",
        ).status_code
        == 404
    )
    assert (
        client.post(
            owner_url(company, f"pages/{my_page.pk}/move/"),
            {"space": space.pk, "index": 0},
            format="json",
        ).status_code
        == 404
    )
    assert (
        client.post(
            owner_url(company, f"pages/{my_page.pk}/links/"),
            {"target_type": "routine", "target_id": routine.pk},
            format="json",
        ).status_code
        == 400
    )
    page.refresh_from_db()
    assert page.title != "Mine now" and page.archived_at is None


def test_every_employee_endpoint_hides_another_companys_rows(
    company, other_company, cashier, api_as
):
    space = SpaceFactory(company=other_company)
    page = PageFactory(space=space)
    client = api_as(cashier)

    assert client.get(app_url(company, f"spaces/{space.pk}/")).status_code == 404
    assert client.get(app_url(company, f"pages/{page.pk}/")).status_code == 404
    assert client.post(app_url(company, f"pages/{page.pk}/ack/")).status_code == 404
    assert client.get(app_url(other_company, "")).status_code == 404


# Query counts: lists don't grow with their rows -------------------------------------------


def _many_pages(company, owner, n):
    space = SpaceFactory(company=company)
    for index in range(n):
        page = PageFactory(space=space, require_ack=index % 2 == 0, updated_by=owner)
        PageAckFactory(page=page, membership=owner)
    return space


def test_page_list_queries_dont_grow_with_rows(
    company, owner, owner_api, django_assert_max_num_queries
):
    client = owner_api(owner)
    _many_pages(company, owner, 3)
    with django_assert_max_num_queries(40) as few:
        assert client.get(owner_url(company, "pages/")).status_code == 200
    _many_pages(company, owner, 12)
    with django_assert_max_num_queries(len(few.captured_queries) + 2):
        response = client.get(owner_url(company, "pages/"))
    assert response.data["count"] == 15


def test_space_list_and_overview_queries_dont_grow_with_rows(
    company, owner, owner_api, django_assert_max_num_queries
):
    client = owner_api(owner)
    _many_pages(company, owner, 2)
    with django_assert_max_num_queries(60) as spaces_few:
        client.get(owner_url(company, "spaces/"))
    with django_assert_max_num_queries(80) as overview_few:
        client.get(owner_url(company, "overview/"))
    for _ in range(5):
        _many_pages(company, owner, 2)
    with django_assert_max_num_queries(len(spaces_few.captured_queries) + 2):
        assert len(client.get(owner_url(company, "spaces/")).data) >= 6
    # Read counts look up each space's audience once: a few queries per space at most.
    with django_assert_max_num_queries(len(overview_few.captured_queries) + 5 * 2):
        client.get(owner_url(company, "overview/"))


# Announcing only what readers can open --------------------------------------------------


def test_a_page_under_a_draft_is_not_announced_or_reminded(company, owner, cashier):
    space = SpaceFactory(company=company)
    draft = services.create_page(space, by=owner, title="Coming soon", body="<p>Soon</p>")
    child = services.create_page(
        space, by=owner, title="Inside", body="<p>Read me</p>", parent=draft, require_ack=True
    )

    services.publish_page(child, by=owner)

    assert not Notification.objects.filter(kind=services.KIND_PUBLISHED).exists()
    with pytest.raises(DomainError, match="pages above"):
        services.remind_unread(child, by=owner)
    Page.objects.filter(pk=child.pk).update(ack_since=timezone.now() - timedelta(days=3))
    assert services.remind_due() == 0
    assert queries.to_read(cashier) == []

    services.publish_page(draft, by=owner)
    assert services.remind_due() == 1
    reminded = Notification.objects.filter(kind=services.KIND_REMINDER, recipient=cashier)
    assert reminded.count() == 1


def test_a_page_in_an_archived_space_is_not_announced(company, owner, cashier):
    space = SpaceFactory(company=company)
    page = services.create_page(space, by=owner, title="Old rules", body="<p>Old</p>")
    services.archive_space(space, by=owner)

    services.publish_page(page, by=owner)

    assert not Notification.objects.filter(kind=services.KIND_PUBLISHED).exists()


# Moves and reordering -------------------------------------------------------------------


def test_archived_pages_and_spaces_dont_take_moves(company, owner):
    space = SpaceFactory(company=company)
    shelf = SpaceFactory(company=company)
    page = PageFactory(space=space)
    services.archive_space(shelf, by=owner)

    with pytest.raises(DomainError, match="space is archived"):
        services.move_page(page, by=owner, parent=None, index=0, space=shelf)
    services.archive_page(page, by=owner)
    with pytest.raises(DomainError, match="Restore it first"):
        services.move_page(page, by=owner, parent=None, index=0)


def test_reordering_spaces_is_audited(company, owner):
    first, second = SpaceFactory(company=company), SpaceFactory(company=company)

    services.reorder_spaces(company, [second.pk, first.pk], by=owner)

    changed = AuditLog.objects.filter(action="knowledge.space_changed")
    # Only the space whose place changed: the second one was already first.
    assert list(changed.values_list("target_id", flat=True)) == [first.pk]
    assert changed.get().details["changed"] == ["position"]
    first.refresh_from_db()
    assert first.position == 1


# The reminder clock ---------------------------------------------------------------------


def test_asking_for_confirmations_later_restarts_the_reminder_clock(company, owner, cashier):
    space = SpaceFactory(company=company)
    page = services.create_page(space, by=owner, title="Rules", body="<p>Rules</p>", publish=True)
    Page.objects.filter(pk=page.pk).update(ack_since=timezone.now() - timedelta(days=30))

    services.save_page(page, by=owner, require_ack=True)

    page.refresh_from_db()
    assert timezone.now() - page.ack_since < timedelta(minutes=1)
    assert services.remind_due() == 0  # the company's 24 hours start now


# The archive ------------------------------------------------------------------------------


def test_the_archive_lists_what_was_archived_and_when(company, owner, owner_api):
    space = SpaceFactory(company=company, name="Old shelf")
    first = PageFactory(space=space, title="First")
    second = PageFactory(space=space, title="Second")
    services.archive_page(first, by=owner)
    services.archive_page(second, by=owner)
    services.archive_space(space, by=owner)
    client = owner_api(owner)

    pages = client.get(
        owner_url(company, "pages/"), {"status": "archived", "ordering": "-archived_at"}
    )
    spaces = client.get(owner_url(company, "spaces/"), {"archived": "true"})

    assert [row["title"] for row in pages.data["results"]] == ["Second", "First"]
    assert all(row["archived_at"] for row in pages.data["results"])
    [shelf] = [row for row in spaces.data if row["id"] == space.pk]
    assert shelf["archived"] is True and shelf["archived_at"]
