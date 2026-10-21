"""Knowledge base services: spaces, pages and versions, publishing, reading, links, pictures."""

import io
from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.inbox.models import Notification
from apps.knowledge import defaults, queries, services
from apps.knowledge.conf import get_settings
from apps.knowledge.models import Page, PageAck, PageImage, PageVersion, Space
from apps.knowledge.tests.factories import PageFactory, SpaceFactory

pytestmark = pytest.mark.django_db


def jpeg_upload(name="photo.png") -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 120, 60)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


# Spaces ---------------------------------------------------------------------------------


def test_create_space_for_some_positions(company, owner, cashier_position):
    space = services.create_space(
        company,
        by=owner,
        name="  Kassa  ",
        icon="💰",
        audience_all=False,
        position_ids=[cashier_position.pk],
    )

    assert (space.name, space.icon, space.audience_all) == ("Kassa", "💰", False)
    assert list(space.positions.all()) == [cashier_position]
    assert AuditLog.objects.filter(action="knowledge.space_created", target_id=space.pk).exists()


def test_a_positions_space_needs_positions(company, owner):
    with pytest.raises(DomainError):
        services.create_space(company, by=owner, name="Kassa", audience_all=False)


def test_only_knowledge_managers_change_the_knowledge_base(company, manager, cashier):
    with pytest.raises(PermissionDenied):
        services.create_space(company, by=manager, name="Kassa")
    space = SpaceFactory(company=company)
    with pytest.raises(PermissionDenied):
        services.create_page(space, by=cashier, title="Rules")


def test_positions_of_another_company_are_refused(company, other_company, owner):
    from apps.members.models import Position

    foreign = Position.objects.create(company=other_company, name="Courier")
    with pytest.raises(DomainError):
        services.create_space(
            company, by=owner, name="Warehouse", audience_all=False, position_ids=[foreign.pk]
        )


def test_archive_and_reorder_spaces(company, owner):
    first, second = SpaceFactory(company=company), SpaceFactory(company=company)

    services.reorder_spaces(company, [second.pk, first.pk], by=owner)
    services.archive_space(first, by=owner)

    assert list(queries.visible_spaces(owner).filter(pk__in=[first.pk, second.pk])) == [second]
    first.refresh_from_db()
    assert first.archived_at is not None and first.position == 1


# Pages and versions ---------------------------------------------------------------------


def test_create_page_cleans_the_body_and_writes_version_one(company, owner):
    space = SpaceFactory(company=company)

    page = services.create_page(
        space, by=owner, title="Opening", body='<p onclick="x()">Count <b>the float</b></p>'
    )

    assert page.body == "<p>Count <b>the float</b></p>"
    assert page.body_text == "Count the float"
    assert (page.version, page.published) == (1, False)
    assert list(page.versions.values_list("version", flat=True)) == [1]


def test_saving_content_writes_a_version_and_settings_dont(company, owner):
    page = services.create_page(SpaceFactory(company=company), by=owner, title="Opening")

    page = services.save_page(page, by=owner, body="<p>Count the float</p>", note="Steps")
    page = services.save_page(page, by=owner, require_ack=True)
    page = services.save_page(page, by=owner, body="<p>Count the float</p>")  # no change

    assert page.version == 2 and page.require_ack
    versions = PageVersion.objects.filter(page=page).order_by("version")
    assert [(v.version, v.note) for v in versions] == [(1, "First version"), (2, "Steps")]


def test_an_old_editor_cant_overwrite_a_newer_save(company, owner):
    page = services.create_page(SpaceFactory(company=company), by=owner, title="Opening")
    services.save_page(page, by=owner, body="<p>Mine</p>", base_version=1)

    with pytest.raises(DomainError, match="newer version"):
        services.save_page(page, by=owner, body="<p>Theirs</p>", base_version=1)


def test_restore_an_old_version_saves_it_as_the_newest(company, owner):
    page = services.create_page(
        SpaceFactory(company=company), by=owner, title="Opening", body="<p>First</p>"
    )
    page = services.save_page(page, by=owner, body="<p>Second</p>")

    page = services.restore_version(page, 1, by=owner)

    assert (page.version, page.body) == (3, "<p>First</p>")
    assert page.versions.get(version=3).note == "Restored version 1"


def test_pages_nest_at_most_four_levels(company, owner):
    space = SpaceFactory(company=company)
    parent = None
    for level in range(4):
        parent = services.create_page(space, by=owner, title=f"Level {level}", parent=parent)

    with pytest.raises(DomainError, match="four levels"):
        services.create_page(space, by=owner, title="Too deep", parent=parent)


def test_move_reorders_siblings_and_refuses_cycles(company, owner):
    space = SpaceFactory(company=company)
    a, b, c = (services.create_page(space, by=owner, title=t) for t in "abc")

    services.move_page(c, by=owner, parent=None, index=0)
    assert list(
        Page.objects.filter(space=space).order_by("position").values_list("title", flat=True)
    ) == ["c", "a", "b"]

    services.move_page(b, by=owner, parent=a, index=0)
    with pytest.raises(DomainError, match="inside itself"):
        services.move_page(a, by=owner, parent=b, index=0)


def test_moving_a_page_to_another_space_takes_its_children(company, owner):
    first, second = SpaceFactory(company=company), SpaceFactory(company=company)
    parent = services.create_page(first, by=owner, title="Parent")
    child = services.create_page(first, by=owner, title="Child", parent=parent)

    services.move_page(parent, by=owner, parent=None, index=0, space=second)

    child.refresh_from_db()
    assert child.space == second and child.parent_id == parent.pk


def test_archive_takes_the_subtree_and_restore_brings_it_back(company, owner):
    space = SpaceFactory(company=company)
    parent = services.create_page(space, by=owner, title="Parent")
    child = services.create_page(space, by=owner, title="Child", parent=parent)

    services.archive_page(parent, by=owner)
    assert Page.objects.filter(pk__in=[parent.pk, child.pk], archived_at__isnull=False).count() == 2

    services.restore_page(parent, by=owner)
    assert not Page.objects.filter(pk__in=[parent.pk, child.pk], archived_at__isnull=False).exists()


# Publishing and reading -----------------------------------------------------------------


def test_publishing_tells_the_readers_with_a_read_button(company, owner, cashier, courier):
    space = SpaceFactory(company=company, audience_all=False, positions=[cashier.position])
    page = services.create_page(space, by=owner, title="Close the till", body="<p>Z report</p>")

    services.publish_page(page, by=owner)

    [note] = Notification.objects.filter(kind="knowledge.page_published")
    assert note.recipient == cashier  # the courier doesn't read the till space; the owner wrote it
    assert "Close the till" in note.title
    assert note.app_screen == f"knowledge.page:{page.pk}"
    assert [action["key"] for action in note.actions] == ["read"]


def test_publishing_can_stay_quiet(company, owner, cashier):
    page = services.create_page(SpaceFactory(company=company), by=owner, title="T", body="<p>x</p>")
    services.publish_page(page, by=owner, notify_readers=False)

    settings_row = get_settings(company)
    settings_row.notify_on_publish = False
    settings_row.save()
    other = services.create_page(page.space, by=owner, title="U", body="<p>y</p>")
    services.publish_page(other, by=owner)

    assert not Notification.objects.filter(kind="knowledge.page_published").exists()


def test_an_empty_page_cant_be_published(company, owner):
    page = services.create_page(SpaceFactory(company=company), by=owner, title="Empty")

    with pytest.raises(DomainError):
        services.publish_page(page, by=owner)


def test_acknowledge_once_per_version_and_reread_asks_again(company, owner, cashier):
    page = services.create_page(
        SpaceFactory(company=company),
        by=owner,
        title="Rules",
        body="<p>v1</p>",
        require_ack=True,
        publish=True,
        notify_readers=False,
    )

    first = services.acknowledge(page, by=cashier)
    again = services.acknowledge(page, by=cashier)
    assert first.pk == again.pk
    assert queries.to_read(cashier) == []

    # A small fix keeps the acknowledgement; a real change with "read it again" doesn't.
    page = services.save_page(page, by=owner, body="<p>v1 fixed</p>")
    assert queries.to_read(cashier) == []
    page = services.save_page(page, by=owner, body="<p>v3</p>", reread=True)
    assert [p.pk for p in queries.to_read(cashier)] == [page.pk]
    assert Notification.objects.filter(kind="knowledge.page_published", recipient=cashier).exists()

    services.acknowledge(page, by=cashier)
    assert queries.to_read(cashier) == []
    assert PageAck.objects.filter(page=page, membership=cashier).count() == 2


def test_people_cant_acknowledge_pages_they_dont_read(company, owner, courier, cashier_position):
    space = SpaceFactory(company=company, audience_all=False, positions=[cashier_position])
    page = PageFactory(space=space)

    with pytest.raises(PermissionDenied):
        services.acknowledge(page, by=courier)


def test_drafts_and_pages_under_drafts_are_hidden_from_readers(company, owner, cashier):
    space = SpaceFactory(company=company)
    draft = PageFactory(space=space, published=False)
    under = PageFactory(space=space, parent=draft)
    live = PageFactory(space=space)

    assert set(queries.reader_pages(cashier)) == {live}
    assert {draft, under, live} <= set(queries.readable_pages(owner))


def test_remind_unread_reaches_only_who_hasnt_read(company, owner, cashier, courier):
    page = PageFactory(space__company=company, require_ack=True)
    services.acknowledge(page, by=courier)

    count = services.remind_unread(page, by=owner)

    assert count == 1
    assert list(
        Notification.objects.filter(kind="knowledge.read_reminder").values_list(
            "recipient", flat=True
        )
    ) == [cashier.pk]


def test_the_hourly_job_reminds_once_per_version(company, owner, cashier):
    page = PageFactory(space__company=company, require_ack=True)
    Page.objects.filter(pk=page.pk).update(ack_since=timezone.now() - timedelta(hours=30))

    assert services.remind_due() == 1
    assert services.remind_due() == 0
    assert Notification.objects.filter(kind="knowledge.read_reminder").count() == 2  # owner too


def test_the_hourly_job_waits_for_the_delay_and_respects_zero(company, owner, cashier):
    page = PageFactory(space__company=company, require_ack=True)

    assert services.remind_due() == 0  # just published
    Page.objects.filter(pk=page.pk).update(ack_since=timezone.now() - timedelta(days=3))
    settings_row = get_settings(company)
    settings_row.remind_unread_after_hours = 0
    settings_row.save()
    assert services.remind_due() == 0


# Links and pictures ---------------------------------------------------------------------


def test_link_a_page_to_a_routine_of_the_company(company, other_company, owner):
    from apps.tasks.models import TaskTemplate

    routine = TaskTemplate.objects.create(company=company, title="Open the till", due_time="09:00")
    foreign = TaskTemplate.objects.create(company=other_company, title="X", due_time="09:00")
    page = PageFactory(space__company=company)

    link = services.link_page(page, by=owner, target_type="routine", target_id=routine.pk)
    again = services.link_page(page, by=owner, target_type="routine", target_id=routine.pk)

    assert link.pk == again.pk and link.target_title == "Open the till"
    with pytest.raises(DomainError):
        services.link_page(page, by=owner, target_type="routine", target_id=foreign.pk)
    services.unlink(link, by=owner)
    assert not page.links.exists()


def test_routines_are_read_through_the_task_apps_contract(company, owner, monkeypatch):
    """Knowledge never reads TaskTemplate itself: titles and search go through tasks.queries."""
    import inspect
    from types import SimpleNamespace

    from apps.knowledge import targets
    from apps.tasks import queries as task_queries
    from apps.tasks.models import TaskTemplate

    asked = []

    def routine(company_id, routine_id):
        asked.append((company_id, routine_id))
        return SimpleNamespace(title="Close the till")

    monkeypatch.setattr(task_queries, "routine", routine)
    assert targets.title(company.pk, "routine", 5, by=None) == "Close the till"
    assert asked == [(company.pk, 5)]
    monkeypatch.undo()
    TaskTemplate.objects.create(company=company, title="Close the till", due_time="22:00")
    TaskTemplate.objects.create(company=company, title="Gym", due_time="07:00", personal=True)
    found = targets.search(owner, "")
    assert [(row.type, row.title) for row in found] == [("routine", "Close the till")]
    assert "TaskTemplate" not in inspect.getsource(targets)


def test_upload_image_re_encodes_into_private_storage(company, owner):
    image = services.upload_image(company, jpeg_upload("evil.svg.png"), by=owner)

    assert image.file.name.startswith(f"knowledge/{company.pk}/")
    assert image.file.name.endswith(".jpg")
    assert (image.width, image.height) == (64, 48)


def test_upload_refuses_what_isnt_a_picture(company, owner):
    svg = SimpleUploadedFile("x.png", b"<svg onload='alert(1)'></svg>", content_type="image/png")

    with pytest.raises(DomainError):
        services.upload_image(company, svg, by=owner)


def test_saving_a_page_claims_its_pictures(company, owner):
    image = services.upload_image(company, jpeg_upload(), by=owner)
    page = services.create_page(
        SpaceFactory(company=company),
        by=owner,
        title="With picture",
        body=f'<p>Look</p><img data-image-id="{image.pk}" alt="till">',
    )

    assert PageImage.objects.get(pk=image.pk).page == page


# Defaults -------------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_new_company_gets_one_space_once(company):
    assert Space.objects.filter(company=company).count() == 1  # from company_created

    Space.objects.filter(company=company).update(archived_at=timezone.now())
    defaults.ensure(company)

    assert Space.objects.filter(company=company).count() == 1


def test_the_author_has_read_what_they_publish(company, owner, cashier):
    page = services.create_page(
        SpaceFactory(company=company),
        by=owner,
        title="Rules",
        body="<p>v1</p>",
        require_ack=True,
        publish=True,
        notify_readers=False,
    )

    assert queries.to_read(owner) == []
    assert [p.pk for p in queries.to_read(cashier)] == [page.pk]
    page = services.save_page(page, by=owner, body="<p>v2</p>", reread=True, notify_readers=False)
    assert PageAck.objects.filter(page=page, membership=owner, version=2).exists()
