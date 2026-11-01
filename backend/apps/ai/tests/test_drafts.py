"""Task drafts end to end: start, listen, understand, create, cancel, undo, expire."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.ai import drafts, services, speech
from apps.ai.models import AgentEvent, AIDraft
from apps.ai.tests.conftest import OGG
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


@pytest.fixture
def team(company, member, ai_on):
    """A manager with AI on and two people to give work to."""
    ai_on(company)
    manager = member.registered(company, "Manager", first_name="Bekzod", last_name="Mirzayev")
    alisher = member.registered(company, first_name="Alisher", last_name="Valiyev")
    madina = member.registered(company, first_name="Madina", last_name="Saidova")
    for person in (manager, alisher, madina):
        person.user.language = "uz"
        person.user.save(update_fields=["language"])
    return {"manager": manager, "alisher": alisher, "madina": madina}


SAID = (
    "Alisher, ertaga soat 10 gacha muzlatgich haroratini tekshirib, rasmini yubor. "
    "Madina, bugun kechqurun kassani sanab qo‘y."
)


def start(member, django_capture_on_commit_callbacks, **kwargs):
    kwargs.setdefault("source", AIDraft.Source.MINIAPP)
    with django_capture_on_commit_callbacks(execute=True):
        draft = services.start_draft(member, **kwargs)
    draft.refresh_from_db()
    return draft


def test_typed_text_becomes_ready_drafts(team, django_capture_on_commit_callbacks):
    draft = start(team["manager"], django_capture_on_commit_callbacks, text=SAID)

    assert draft.status == AIDraft.Status.READY
    assert draft.engine == AIDraft.Engine.RULES
    assert draft.transcript == SAID
    [fridge, cash] = draft.drafts
    assert fridge["assignee_id"] == team["alisher"].pk
    assert fridge["proof"] == "photo"
    assert cash["assignee_id"] == team["madina"].pk
    event = AgentEvent.objects.get(kind="draft_ready")
    assert event.params == {"count": 2, "author": "Bekzod Mirzayev"}
    assert event.subject_type == "draft" and event.subject_id == draft.pk


def test_applying_creates_the_tasks_through_the_task_services(
    team, django_capture_on_commit_callbacks
):
    draft = start(team["manager"], django_capture_on_commit_callbacks, text=SAID)

    with django_capture_on_commit_callbacks(execute=True):
        result = services.apply_draft(draft, team["manager"])

    assert result.failed == []
    tasks = list(Task.objects.filter(pk__in=result.created).order_by("pk"))
    assert [task.assignee for task in tasks] == [team["alisher"], team["madina"]]
    assert all(task.created_by == team["manager"] for task in tasks)
    assert tasks[0].proof == "photo"
    draft.refresh_from_db()
    assert draft.status == AIDraft.Status.APPLIED
    assert draft.applied_ids == result.created
    assert draft.applied_by == team["manager"]
    # Twice is a no-op that answers the same.
    again = services.apply_draft(draft, team["manager"])
    assert again.created == result.created
    assert Task.objects.filter(created_by=team["manager"]).count() == 2


def test_one_bad_draft_does_not_stop_the_others(
    team, company, member, django_capture_on_commit_callbacks
):
    draft = start(team["manager"], django_capture_on_commit_callbacks, text=SAID)
    stranger = member.registered(company)  # not allowed: another branch? no: give a bad id
    edited = [
        {"title": "Muzlatgich haroratini tekshirish", "assignee_id": team["alisher"].pk},
        {"title": "Kassani sanash", "assignee_id": 999_999},
        {"title": "", "assignee_id": None},
    ]

    result = services.apply_draft(draft, team["manager"], edited)

    assert len(result.created) == 1
    assert [failure["index"] for failure in result.failed] == [1, 2]
    assert stranger.pk not in [task.assignee_id for task in Task.objects.all()]


def test_only_the_author_creates_or_cancels(team, django_capture_on_commit_callbacks):
    from django.core.exceptions import PermissionDenied

    draft = start(team["manager"], django_capture_on_commit_callbacks, text=SAID)

    with pytest.raises(PermissionDenied):
        services.apply_draft(draft, team["alisher"])
    with pytest.raises(PermissionDenied):
        services.discard_draft(draft, team["alisher"])


def test_someone_who_cannot_give_work_gets_drafts_for_themselves(
    team, django_capture_on_commit_callbacks
):
    draft = start(team["alisher"], django_capture_on_commit_callbacks, text=SAID)

    assert {item["assignee_id"] for item in draft.drafts} <= {None}
    with django_capture_on_commit_callbacks(execute=True):
        result = services.apply_draft(draft, team["alisher"])
    assert {task.assignee_id for task in Task.objects.filter(pk__in=result.created)} == {
        team["alisher"].pk
    }


def test_a_voice_note_is_heard_by_the_fake_service(
    team, settings, django_capture_on_commit_callbacks
):
    settings.AI_FAKE = True

    draft = start(team["manager"], django_capture_on_commit_callbacks, audio=OGG, seconds=9)

    assert draft.status == AIDraft.Status.READY
    assert draft.engine == AIDraft.Engine.FAKE
    assert draft.audio.name.endswith(".ogg")
    assert draft.audio_seconds == 9
    assert draft.transcript.startswith("Alisher, ertaga")
    assert draft.transcribed_at is not None
    assert len(draft.drafts) == 2


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (speech.SpeechError("down"), "speech_unavailable"),
        (speech.AudioUnreadable("bad"), "audio_unreadable"),
    ],
)
def test_speech_failures_fail_the_draft(
    team, settings, monkeypatch, error, code, django_capture_on_commit_callbacks
):
    settings.AI_SPEECH_URL = "http://stt:8000/v1"

    def broken(*args, **kwargs):
        raise error

    monkeypatch.setattr(speech, "transcribe", broken)
    draft = start(team["manager"], django_capture_on_commit_callbacks, audio=OGG, seconds=5)

    assert draft.status == AIDraft.Status.FAILED
    assert draft.error_code == code
    assert AgentEvent.objects.filter(kind="draft_failed").count() == 1


def test_silence_is_nothing_heard(team, settings, monkeypatch, django_capture_on_commit_callbacks):
    settings.AI_SPEECH_URL = "http://stt:8000/v1"
    monkeypatch.setattr(speech, "transcribe", lambda *a, **k: speech.Transcript("", "uz", 3.0))

    draft = start(team["manager"], django_capture_on_commit_callbacks, audio=OGG, seconds=3)

    assert (draft.status, draft.error_code) == (AIDraft.Status.FAILED, "nothing_heard")


def test_a_busy_service_is_tried_again_then_given_up(team, settings, monkeypatch):
    """deploy/stt answers 503 while its models load: the job comes back in 20 s, five times,
    then the draft fails as speech_unavailable."""
    from apps.ai import tasks as jobs

    settings.AI_SPEECH_URL = "http://stt:8000/v1"

    def busy(*args, **kwargs):
        raise speech.SpeechBusy("loading")

    monkeypatch.setattr(speech, "transcribe", busy)
    draft = services.start_draft(team["manager"], audio=OGG, seconds=3, source="miniapp")
    countdowns = []

    class Again(Exception):
        pass

    def retry(*, countdown):
        countdowns.append(countdown)
        return Again()

    monkeypatch.setattr(jobs.process_draft, "retry", retry)
    jobs.process_draft.push_request(retries=0)
    try:
        with pytest.raises(Again):
            jobs.process_draft.run(draft.pk)
    finally:
        jobs.process_draft.pop_request()
    draft.refresh_from_db()
    assert countdowns == [jobs.SPEECH_RETRY_SECONDS]
    assert draft.status == AIDraft.Status.TRANSCRIBING  # still listening for the app's poll

    jobs.process_draft.push_request(retries=jobs.SPEECH_RETRIES)
    try:
        jobs.process_draft.run(draft.pk)
    finally:
        jobs.process_draft.pop_request()
    draft.refresh_from_db()
    assert (draft.status, draft.error_code) == (AIDraft.Status.FAILED, "speech_unavailable")


def test_the_language_given_is_sent_to_the_speech_service(
    team, settings, monkeypatch, django_capture_on_commit_callbacks
):
    settings.AI_SPEECH_URL = "http://stt:8000/v1"
    heard = {}

    def transcribe(audio, **kwargs):
        heard.update(kwargs)
        return speech.Transcript("Алишер, завтра проверь холодильник", "ru", 4.0)

    monkeypatch.setattr(speech, "transcribe", transcribe)
    draft = start(
        team["manager"], django_capture_on_commit_callbacks, audio=OGG, seconds=4, language="ru"
    )

    assert heard["language"] == "ru"
    assert heard["content_type"] == "audio/ogg"
    assert heard["filename"].endswith(".ogg")
    assert "Alisher Valiyev" in heard["prompt"]
    assert "холодильник" in heard["prompt"]
    assert draft.language == "ru"


@pytest.mark.parametrize(
    ("kwargs", "code", "status"),
    [
        ({"text": "x" * 2001}, "text_too_long", 400),
        ({"text": "   "}, "text_too_long", 400),
        ({"audio": OGG, "seconds": 121}, "audio_too_long", 400),
        ({"audio": b"OggS" + b"\x00" * (10 * 1024 * 1024)}, "audio_too_big", 400),
        ({"audio": b"<html>not audio</html>", "seconds": 3}, "audio_unreadable", 400),
    ],
)
def test_bad_input_is_refused_with_a_code(team, settings, kwargs, code, status):
    settings.AI_FAKE = True

    with pytest.raises(services.DraftRefused) as refused:
        services.start_draft(team["manager"], source="miniapp", **kwargs)

    assert (refused.value.code, refused.value.status) == (code, status)
    assert not AIDraft.objects.exists()


def test_with_ai_off_nothing_starts(company, member):
    manager = member.registered(company, "Manager")

    with pytest.raises(services.DraftRefused) as refused:
        services.start_draft(manager, text="Kassani sana", source="miniapp")

    assert (refused.value.code, refused.value.status) == ("ai_off", 403)


def test_voice_needs_a_speech_service_but_text_does_not(team):
    with pytest.raises(services.DraftRefused) as refused:
        services.start_draft(team["manager"], audio=OGG, seconds=3, source="miniapp")
    assert refused.value.code == "ai_off"

    assert services.start_draft(team["manager"], text="Kassani sana", source="miniapp")


def test_the_daily_limit(team, django_capture_on_commit_callbacks):
    from apps.ai import conf

    row = conf.get_settings(team["manager"].company)
    row.member_daily_drafts = 2
    row.save()
    for _ in range(2):
        services.start_draft(team["manager"], text="Kassani sana", source="miniapp")

    with pytest.raises(services.DraftRefused) as refused:
        services.start_draft(team["manager"], text="Kassani sana", source="miniapp")

    assert (refused.value.code, refused.value.status) == ("limit_reached", 429)


def test_auto_create_makes_the_tasks_at_once_and_undo_takes_them_back(
    company, member, ai_on, card_edits, django_capture_on_commit_callbacks
):
    ai_on(company, auto_create=True)
    manager = member.registered(company, "Manager", first_name="Bekzod", last_name="Mirzayev")
    alisher = member.registered(company, first_name="Alisher", last_name="Valiyev")

    with django_capture_on_commit_callbacks(execute=True):
        draft = services.start_draft(
            manager,
            text="Alisher, ertaga soat 10 gacha muzlatgich haroratini tekshir.",
            source="bot",
            tg={"bot": "employee", "chat_id": 77, "message_id": 5},
        )
    draft.refresh_from_db()

    assert draft.status == AIDraft.Status.APPLIED
    assert draft.auto_applied
    [task] = Task.objects.filter(pk__in=draft.applied_ids)
    assert task.assignee == alisher
    assert card_edits[-1]["message_id"] == 5
    assert "Undo" in str(card_edits[-1]["reply_markup"])

    with django_capture_on_commit_callbacks(execute=True):
        services.undo_draft(draft, manager)
    task.refresh_from_db()
    draft.refresh_from_db()
    assert task.status == Task.Status.CANCELLED
    assert draft.status == AIDraft.Status.DISCARDED and draft.undone_at is not None


def test_auto_create_waits_when_a_draft_has_no_time(
    company, member, ai_on, django_capture_on_commit_callbacks
):
    ai_on(company, auto_create=True)
    manager = member.registered(company, "Manager")
    member.registered(company, first_name="Alisher", last_name="Valiyev")

    draft = start(manager, django_capture_on_commit_callbacks, text="Alisher, kassani sana.")

    assert draft.status == AIDraft.Status.READY


def test_undo_is_only_for_a_while(company, member, ai_on, django_capture_on_commit_callbacks):
    ai_on(company, auto_create=True)
    manager = member.registered(company, "Manager")
    member.registered(company, first_name="Alisher", last_name="Valiyev")
    draft = start(
        manager, django_capture_on_commit_callbacks, text="Alisher, ertaga soat 10 da kassani sana."
    )
    AIDraft.objects.filter(pk=draft.pk).update(applied_at=timezone.now() - timedelta(minutes=11))

    from apps.core.exceptions import DomainError

    with pytest.raises(DomainError):
        services.undo_draft(draft, manager)


def test_the_bot_card_follows_the_draft(team, card_edits, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        draft = services.start_draft(
            team["manager"],
            text=SAID,
            source="bot",
            tg={"bot": "employee", "chat_id": 77, "message_id": 5},
        )

    edit = card_edits[-1]
    assert (edit["bot"], edit["chat_id"], edit["message_id"]) == ("employee", 77, 5)
    assert "Alisher Valiyev" in edit["text"]
    assert "Madina Saidova" in edit["text"]
    buttons = [b["text"] for row in edit["reply_markup"]["inline_keyboard"] for b in row]
    assert len(buttons) == 2  # Create 2 tasks, Cancel (no https mini app here)
    assert f"aid:apply:{draft.pk}" in str(edit["reply_markup"])


def test_ready_drafts_expire_after_a_day(team, card_edits, django_capture_on_commit_callbacks):
    draft = start(team["manager"], django_capture_on_commit_callbacks, text=SAID)
    AIDraft.objects.filter(pk=draft.pk).update(finished_at=timezone.now() - timedelta(hours=25))

    assert drafts.expire_stale() == 1

    draft.refresh_from_db()
    assert (draft.status, draft.error_code) == (AIDraft.Status.EXPIRED, "expired")


def test_old_recordings_are_deleted_and_the_words_stay(
    team, settings, django_capture_on_commit_callbacks
):
    settings.AI_FAKE = True
    draft = start(team["manager"], django_capture_on_commit_callbacks, audio=OGG, seconds=3)
    path = draft.audio.path
    AIDraft.objects.filter(pk=draft.pk).update(created_at=timezone.now() - timedelta(days=31))

    assert drafts.purge_audio() == 1

    draft.refresh_from_db()
    assert not draft.audio
    assert draft.transcript
    import os

    assert not os.path.exists(path)


def test_the_card_writes_dates_in_the_readers_language(team, django_capture_on_commit_callbacks):
    """A Russian reader saw "Ertaga, 10:00" (the Uzbek word, capitalised mid-line)."""
    from django.utils import translation

    from apps.ai import bot_messages

    draft = start(team["manager"], django_capture_on_commit_callbacks, text=SAID)

    with translation.override("ru"):
        text, _markup = bot_messages.draft_card(draft)
    with translation.override("en"):
        english, _markup = bot_messages.draft_card(draft)

    lines = text.split("<blockquote")[0].lower()  # the transcript itself stays as said
    assert "10:00" in lines and "18:00" in lines
    assert ("сегодня, " in lines or "завтра, " in lines) and "с фото" in lines
    assert "ertaga" not in lines and "bugun" not in lines
    first = english.split("<blockquote")[0]
    assert "today, " in first or "tomorrow, " in first
    assert "Today" not in first and "Tomorrow" not in first


def test_a_created_task_of_ones_own_says_for_you(
    company, member, ai_on, django_capture_on_commit_callbacks
):
    """The card said "for you" before Create and the author's own name after."""
    from django.utils import translation

    from apps.ai import bot_messages

    ai_on(company)
    worker = member.registered(company, first_name="Alisher", last_name="Valiyev")
    draft = start(
        worker, django_capture_on_commit_callbacks, text="Ertaga soat 10 da kassani sanash."
    )
    with django_capture_on_commit_callbacks(execute=True):
        services.apply_draft(draft, worker)
    draft.refresh_from_db()

    with translation.override("en"):
        text, _markup = bot_messages.draft_card(draft)

    assert "for you" in text
    assert "Alisher Valiyev" not in text
