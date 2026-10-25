"""What the bots say about pages carries no emoji, even for pages saved before 25.10.2026."""

import pytest

from apps.knowledge import bot_messages
from apps.knowledge.tests.factories import PageFactory
from apps.notifications.emoji import has_emoji

pytestmark = pytest.mark.django_db


def test_an_old_pages_excerpt_drops_its_emoji_callout_marks():
    # How the stored text read before tonight: the callout's emoji mark at the start of a line.
    page = PageFactory(body_text="⚠️ Qoldiq farq qilsa, smenani ochmang.\n✅ Mudirga xabar bering.")

    excerpt = bot_messages.page_excerpt(page)

    assert not has_emoji(excerpt)
    assert "Qoldiq farq qilsa, smenani ochmang." in excerpt
    assert "Mudirga xabar bering." in excerpt
