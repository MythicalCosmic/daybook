"""Ask AI: conversations, the bounded tool loop, polling, cancel (v0.2 AI contract §5)."""

import json
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.ai.models import AIMessage, AITurn
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory

pytestmark = pytest.mark.django_db


def url(company, path):
    return f"/api/v1/owner/companies/{company.pk}/ai/{path}"


@pytest.fixture
def owner(company, member, ai_on):
    ai_on(company)
    person = member.registered(company, "Owner", first_name="Dilnoza", last_name="Karimova")
    worker = member.registered(company, first_name="Alisher", last_name="Valiyev")
    TaskFactory(
        company=company,
        kind=Task.Kind.ASSIGNED,
        created_by=person,
        assignee=worker,
        due_at=timezone.now() - timedelta(hours=5),
        title="Muzlatgich haroratini tekshirish",
    )
    return person


def ask(client, company, text, capture):
    conversation = client.post(url(company, "conversations/")).json()
    with capture(execute=True):
        started = client.post(
            url(company, f"conversations/{conversation['id']}/turns/"),
            {"text": text},
            format="json",
        )
    assert started.status_code == 202, started.content
    return conversation, started.json()["turn_id"]


def test_fake_ai_answers_with_a_real_tool(
    owner_api, owner, company, settings, django_capture_on_commit_callbacks
):
    settings.AI_FAKE = True
    client = owner_api(owner)
    assert client.get(url(company, "status/")).json()["features"]["chat"] is True

    conversation, turn_id = ask(
        client, company, "Nechta vazifa kechikmoqda?", django_capture_on_commit_callbacks
    )

    turn = client.get(url(company, f"turns/{turn_id}/")).json()
    assert turn["status"] == "done"
    assert "1" in turn["text"] and "(task:" in turn["text"]
    [step] = turn["steps"]
    assert step["status"] == "done" and step["label"]
    messages = client.get(url(company, f"conversations/{conversation['id']}/messages/")).json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["steps"] == turn["steps"]
    listed = client.get(url(company, "conversations/")).json()
    assert listed[0]["title"] == "Nechta vazifa kechikmoqda?"


def tool_use(name, tool_input, tool_id="toolu_1"):
    return {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}


def test_the_tool_loop_with_claude(
    owner_api, owner, company, fake_claude, django_capture_on_commit_callbacks
):
    task = Task.objects.get()
    fake_claude.script(
        fake_claude.message(
            [tool_use("tasks_search", {"overdue": True})],
            stop_reason="tool_use",
            model="claude-sonnet-5-5",
        ),
        fake_claude.text(
            f"**1 ta vazifa kechikmoqda:** [{task.title}](task:{task.pk}), "
            "[Kimdir](member:999999), [sayt](https://example.com).",
            model="claude-sonnet-5-5",
        ),
    )
    client = owner_api(owner)

    _conversation, turn_id = ask(
        client, company, "Kechikkan vazifalar?", django_capture_on_commit_callbacks
    )

    turn = client.get(url(company, f"turns/{turn_id}/")).json()
    assert turn["status"] == "done"
    assert f"[{task.title}](task:{task.pk})" in turn["text"]
    assert "member:999999" not in turn["text"] and "Kimdir" in turn["text"]
    assert "https://" not in turn["text"] and "sayt" in turn["text"]
    first, second = fake_claude.requests
    assert first["model"] == "claude-sonnet-5-5"
    assert first["output_config"]["effort"] == "medium"
    assert first["fallbacks"] == "default"
    assert "tool_choice" not in first and "temperature" not in first
    names = [tool["name"] for tool in first["tools"]]
    assert names == sorted(names) and "tasks_search" in names
    assert all(tool["strict"] is True for tool in first["tools"])
    results = second["messages"][-1]["content"]
    assert results[0]["type"] == "tool_result" and results[0]["tool_use_id"] == "toolu_1"
    assert json.loads(results[0]["content"])["total"] == 1


def test_history_is_replayed_as_stored(
    owner_api, owner, company, fake_claude, django_capture_on_commit_callbacks
):
    fake_claude.script(fake_claude.text("Birinchi javob."), fake_claude.text("Ikkinchi javob."))
    client = owner_api(owner)
    conversation, _turn = ask(client, company, "Salom", django_capture_on_commit_callbacks)

    with django_capture_on_commit_callbacks(execute=True):
        client.post(
            url(company, f"conversations/{conversation['id']}/turns/"),
            {"text": "Yana"},
            format="json",
        )

    first, second = fake_claude.requests
    assert second["messages"][: len(first["messages"])] == first["messages"]
    assert second["messages"][-1] == {"role": "user", "content": [{"type": "text", "text": "Yana"}]}
    assert second["system"] == first["system"]
    assert second["tools"] == first["tools"]


def test_the_loop_stops_after_eight_rounds(
    owner_api, owner, company, fake_claude, django_capture_on_commit_callbacks
):
    rounds = [
        fake_claude.message(
            [tool_use("tasks_search", {"overdue": True}, f"toolu_{n}")], stop_reason="tool_use"
        )
        for n in range(8)
    ]
    fake_claude.script(*rounds, fake_claude.text("Yetarli."))

    ask(owner_api(owner), company, "Hammasi", django_capture_on_commit_callbacks)

    assert len(fake_claude.requests) == 9
    assert fake_claude.requests[-1]["tool_choice"] == {"type": "none"}
    assert AITurn.objects.get().text == "Yetarli."


def test_a_refusal_fails_the_turn(
    owner_api, owner, company, fake_claude, django_capture_on_commit_callbacks
):
    fake_claude.script(fake_claude.refusal("bio"))

    _conversation, turn_id = ask(owner_api(owner), company, "?", django_capture_on_commit_callbacks)

    turn = AITurn.objects.get(pk=turn_id)
    assert (turn.status, turn.error_code) == ("failed", "refused")


def test_cancel_takes_the_turn_out_of_the_context(owner_api, owner, company, settings):
    settings.AI_FAKE = True
    client = owner_api(owner)
    conversation = client.post(url(company, "conversations/")).json()
    turn_id = client.post(
        url(company, f"conversations/{conversation['id']}/turns/"), {"text": "?"}, format="json"
    ).json()["turn_id"]  # not run: the job waits for the commit

    cancelled = client.post(url(company, f"turns/{turn_id}/cancel/")).json()

    assert cancelled["status"] == "cancelled"
    assert not AIMessage.objects.filter(turn_id=turn_id, in_context=True).exists()


def test_chat_needs_ai_use_and_is_private(owner_api, owner, company, member, settings):
    settings.AI_FAKE = True
    manager = member.registered(company, "Manager")
    assert owner_api(manager).post(url(company, "conversations/")).status_code == 403
    conversation = owner_api(owner).post(url(company, "conversations/")).json()
    other_owner = member.registered(company, "Owner")

    seen = owner_api(other_owner).get(url(company, f"conversations/{conversation['id']}/messages/"))

    assert seen.status_code == 404


def test_without_claude_chat_is_off(owner_api, owner, company):
    client = owner_api(owner)

    assert client.get(url(company, "status/")).json()["features"]["chat"] is False
    response = client.post(url(company, "conversations/"))
    assert response.status_code == 403 and response.json()["code"] == "ai_off"
