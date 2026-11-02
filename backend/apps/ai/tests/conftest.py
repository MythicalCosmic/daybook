"""Fixtures of the AI tests: a scripted Claude, a company with AI on, captured bot edits."""

import pytest

from apps.ai import agents, availability, conf
from apps.ai.agents import voice_tasks
from apps.ai.fakes import FakeAnthropic
from apps.companies.models import Feature
from apps.hr.tests.conftest import (  # noqa: F401  (HR's pharmacy, for the HR assistant)
    chilonzor,
    freeze,
    shop,
    staff,
    yunusobod,
)

# The first bytes of a Telegram voice message (an Ogg page), enough for the upload check.
OGG = b"OggS\x00\x02" + b"\x00" * 64


@pytest.fixture
def fake_claude(monkeypatch, settings):
    """Claude "configured" (a key) and answered by a script: `fake_claude.script(...)`."""
    settings.ANTHROPIC_API_KEY = "sk-test"
    fake = FakeAnthropic()
    monkeypatch.setattr("apps.ai.client.get_client", lambda: fake)
    availability.reset_breaker()
    return fake


def switch_ai_on(company, *, auto_create: bool = False, max_seconds: int = 120):
    """AI on for `company` as an owner's consent leaves it, with the voice agent on."""
    if Feature.AI not in company.features:
        company.features = [*company.features, Feature.AI]
        company.save(update_fields=["features"])
    row = conf.get_settings(company)
    row.enabled = True
    row.save()
    state = agents.state_of(company, voice_tasks.KEY)
    state.enabled = True
    state.config = {"auto_create": auto_create, "max_seconds": max_seconds}
    state.save()
    return row


@pytest.fixture
def ai_on():
    return switch_ai_on


@pytest.fixture
def card_edits(monkeypatch):
    """Bot messages the backend edited (the draft card), captured instead of sent."""
    edits = []

    def record(bot, chat_id, message_id, text, reply_markup=None):
        edits.append(
            {
                "bot": bot,
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "reply_markup": reply_markup,
            }
        )

    monkeypatch.setattr("apps.notifications.telegram.edit_message", record)
    return edits
