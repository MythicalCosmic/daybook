"""What the knowledge base gives the registries: search, activity, bot buttons, copy, AI."""

import pytest

from apps.ai.tools.testing import call_tool
from apps.console import registry
from apps.inbox.models import Notification
from apps.inbox.services import run_action
from apps.knowledge import providers, services
from apps.knowledge.models import Page, PageImage, Space
from apps.knowledge.tests.factories import PageFactory, SpaceFactory

pytestmark = pytest.mark.django_db


def test_registrations_use_app_prefixed_keys():
    assert "knowledge.page" in registry.SEARCH
    assert "knowledge.published" in registry.STREAM
    assert "knowledge.pages" in registry.PULSE
    assert "knowledge.spaces" in registry.COPY_PARTS


def test_palette_search_respects_who_reads_what(company, owner, cook, cashier_position):
    till = SpaceFactory(company=company, audience_all=False, positions=[cashier_position])
    PageFactory(space=till, title="Kassani ochish")
    PageFactory(space=SpaceFactory(company=company), title="Kassa draft", published=False)

    assert {hit.title for hit in providers.search(owner, "kassa", 5)} == {
        "Kassani ochish",
        "Kassa draft",
    }
    assert providers.search(cook, "kassa", 5) == []
    [hit] = [hit for hit in providers.search(owner, "draft", 5)]
    assert hit.url == f"/c/{company.pk}/knowledge/p/{hit.id}"
    assert "Draft" in hit.subtitle


def test_activity_stream_lists_published_pages(company, owner):
    page = services.create_page(
        SpaceFactory(company=company), by=owner, title="Opening", body="<p>x</p>"
    )
    services.publish_page(page, by=owner, notify_readers=False)

    [item] = providers.stream(owner, None, 10)

    assert item.kind == "knowledge.published" and "Opening" in item.title
    assert item.actor == {"id": owner.pk, "name": owner.full_name or str(owner)}


def test_read_button_sends_the_page_into_the_chat(
    company, owner, cashier, sent_messages, settings, django_capture_on_commit_callbacks
):
    settings.TELEGRAM_DRY_RUN = False
    page = services.create_page(
        SpaceFactory(company=company),
        by=owner,
        title="Opening",
        body="<h2>Steps</h2><p>Count the float</p>",
        require_ack=True,
    )
    services.publish_page(page, by=owner)
    note = Notification.objects.get(kind="knowledge.page_published", recipient=cashier)

    with django_capture_on_commit_callbacks(execute=True):
        message = run_action(note.pk, "read", by=cashier)

    assert message == "Sent the page below 👇"
    sent = [m for m in sent_messages if "Count the float" in m["text"]]
    assert sent and sent[0]["chat_id"] == cashier.user.telegram_id
    assert "<b>Steps</b>" in sent[0]["text"]
    keyboard = sent[0]["reply_markup"]["inline_keyboard"]
    assert keyboard[0][0]["callback_data"].startswith("kb:ack:")


def test_copy_spaces_into_another_company(company, other_company, owner, member):
    target_owner = member(other_company, "Owner")
    space = SpaceFactory(company=company, name="Kassa")
    parent = PageFactory(space=space, title="Parent")
    PageFactory(space=space, parent=parent, title="Child")
    PageFactory(space=space, title="Draft", published=False)

    created = providers.copy_spaces(company, other_company, target_owner)

    copied = Space.objects.filter(company=other_company, name="Kassa").get()
    titles = set(Page.objects.filter(space=copied).values_list("title", flat=True))
    assert titles == {"Parent", "Child"}
    child = Page.objects.get(space=copied, title="Child")
    assert child.parent.title == "Parent" and child.parent.company == other_company
    assert created >= 3


def test_copy_brings_pictures_along(company, other_company, owner, member):
    import io

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), (1, 2, 3)).save(buffer, format="PNG")
    image = services.upload_image(company, SimpleUploadedFile("a.png", buffer.getvalue()), by=owner)
    space = SpaceFactory(company=company)
    PageFactory(space=space, body=f'<img data-image-id="{image.pk}" alt="x"><p>t</p>')

    providers.copy_spaces(company, other_company, member(other_company, "Owner"))

    copy = PageImage.objects.get(company=other_company)
    page = Page.objects.get(company=other_company, space__name=space.name)
    assert f'data-image-id="{copy.pk}"' in page.body and copy.page == page


def test_ai_tools_search_and_read_pages(company, owner, cook, cashier_position):
    till = SpaceFactory(company=company, audience_all=False, positions=[cashier_position])
    page = PageFactory(space=till, title="Kassani ochish", body="<p>Razmen 500 000</p>")

    found = call_tool("knowledge_search", owner, query="kassa")
    read = call_tool("knowledge_page", owner, page_id=page.pk)
    denied = call_tool("knowledge_page", cook, page_id=page.pk)

    assert [row["id"] for row in found["rows"]] == [page.pk]
    assert "Razmen" in read["data"]["text"]
    assert denied.get("error") in ("not_allowed", "not_found")
