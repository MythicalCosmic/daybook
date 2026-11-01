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


def test_two_turns_send_the_same_system_and_tools_and_replay_the_history(
    owner_api, owner, company, fake_claude, monkeypatch, django_capture_on_commit_callbacks
):
    """PLAN §8.4: the cached prefix is byte-identical across turns, whatever the time, the page
    or the asker's language; turn 2 replays turn 1's stored messages exactly."""
    from apps.ai import chat

    fake_claude.script(
        fake_claude.json({"x": 1}),  # a thinking block and text, as Opus/Sonnet answer
        fake_claude.text("Ikkinchi javob."),
    )
    client = owner_api(owner)
    conversation, _turn = ask(client, company, "Salom", django_capture_on_commit_callbacks)
    later = timezone.now() + timedelta(minutes=7)
    monkeypatch.setattr(chat.timezone, "now", lambda: later)
    owner.user.language = "ru"
    owner.user.save(update_fields=["language"])

    with django_capture_on_commit_callbacks(execute=True):
        client.post(
            url(company, f"conversations/{conversation['id']}/turns/"),
            {"text": "Yana", "page": "/people/17"},
            format="json",
        )

    first, second = fake_claude.requests
    assert json.dumps(second["system"]) == json.dumps(first["system"])
    assert json.dumps(second["tools"]) == json.dumps(first["tools"])
    assert second["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "now=" not in json.dumps(first["system"]) and "page=" not in json.dumps(first["system"])
    stored = [
        {"role": message.role, "content": message.content}
        for message in AIMessage.objects.filter(conversation_id=conversation["id"]).order_by("seq")
    ]
    assert second["messages"][: len(first["messages"])] == first["messages"] == stored[:1]
    assert second["messages"][1] == stored[1]  # turn 1's answer, thinking block included
    assert stored[1]["content"][0]["type"] == "thinking"
    context, question = second["messages"][-1]["content"]
    assert question == {"type": "text", "text": "Yana"}
    assert "page=/people/17" in context["text"] and "language=Russian" in context["text"]


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


def test_a_cancel_during_a_call_leaves_nothing_of_the_turn_in_the_context(
    owner_api, owner, company, fake_claude, monkeypatch, django_capture_on_commit_callbacks
):
    """Cancel arrives while Claude is answering a tool round: what that round brings back
    (a tool_use, its results) must not stay in the history, or every later question replays a
    tool_use without its result (a 400 for the rest of the conversation)."""
    from apps.ai import chat

    fake_claude.script(
        fake_claude.message([tool_use("tasks_search", {"overdue": True})], stop_reason="tool_use"),
        fake_claude.text("Ikkinchi savolga javob."),
    )
    answer = fake_claude._answer
    calls = []

    def cancelled_while_answering(request):
        calls.append(request)
        if len(calls) == 1:
            chat.cancel_turn(AITurn.objects.get(), by=owner)
        return answer(request)

    monkeypatch.setattr(fake_claude, "_answer", cancelled_while_answering)
    client = owner_api(owner)
    conversation, turn_id = ask(client, company, "Birinchi", django_capture_on_commit_callbacks)

    assert AITurn.objects.get(pk=turn_id).status == "cancelled"
    assert not AIMessage.objects.filter(turn_id=turn_id, in_context=True).exists()
    with django_capture_on_commit_callbacks(execute=True):
        client.post(
            url(company, f"conversations/{conversation['id']}/turns/"),
            {"text": "Ikkinchi"},
            format="json",
        )
    second = fake_claude.requests[-1]
    assert [message["role"] for message in second["messages"]] == ["user"]
    assert second["messages"][0]["content"][-1] == {"type": "text", "text": "Ikkinchi"}


def test_a_turn_asks_before_every_call_not_only_when_it_was_queued(
    owner_api, owner, company, fake_claude, django_capture_on_commit_callbacks
):
    """The budget and the AI switch are checked by the worker before each call: a question
    queued before AI was switched off isn't sent, and a tool loop whose first round spent the
    rest of the month's budget makes no second call."""
    from apps.ai import chat, conf

    client = owner_api(owner)
    conversation = client.post(url(company, "conversations/")).json()
    turn_id = client.post(
        url(company, f"conversations/{conversation['id']}/turns/"), {"text": "?"}, format="json"
    ).json()["turn_id"]  # queued; the job waits for the commit
    conf.get_settings(company).__class__.objects.filter(company=company).update(enabled=False)

    chat.run_turn(turn_id)

    assert fake_claude.requests == []
    assert AITurn.objects.get(pk=turn_id).status == "failed"

    conf.get_settings(company).__class__.objects.filter(company=company).update(
        enabled=True, monthly_budget_usd="0.01"
    )
    fake_claude.script(
        fake_claude.message(
            [tool_use("tasks_search", {"overdue": True})],
            stop_reason="tool_use",
            model="claude-sonnet-5-5",
            input_tokens=10_000,  # $0.02 on Sonnet 5.5: more than the month's budget
        ),
        fake_claude.text("Hech qachon yuborilmaydi."),
    )
    _conversation, second = ask(client, company, "Yana", django_capture_on_commit_callbacks)

    assert len(fake_claude.requests) == 1
    turn = AITurn.objects.get(pk=second)
    assert (turn.status, turn.error_code) == ("failed", "budget_reached")


def test_a_turn_whose_job_died_does_not_hold_the_conversation_forever(
    owner_api, owner, company, settings, django_capture_on_commit_callbacks
):
    """A worker restart loses a running turn: it stays "running" and every new question got
    409 "busy". After a while it no longer counts: it is taken out (cancelled), and the next
    question goes ahead."""
    settings.AI_FAKE = True
    client = owner_api(owner)
    conversation = client.post(url(company, "conversations/")).json()
    path = url(company, f"conversations/{conversation['id']}/turns/")
    first = client.post(path, {"text": "?"}, format="json").json()["turn_id"]  # never run
    assert client.post(path, {"text": "??"}, format="json").status_code == 409
    AITurn.objects.filter(pk=first).update(
        status="running", created_at=timezone.now() - timedelta(minutes=20)
    )

    with django_capture_on_commit_callbacks(execute=True):
        again = client.post(path, {"text": "Nechta vazifa kechikmoqda?"}, format="json")

    assert again.status_code == 202
    assert AITurn.objects.get(pk=first).status == "cancelled"
    assert not AIMessage.objects.filter(turn_id=first, in_context=True).exists()
    assert AITurn.objects.get(pk=again.json()["turn_id"]).status == "done"


def test_a_question_goes_to_claude_without_phone_numbers_or_usernames(
    owner_api, owner, company, fake_claude, django_capture_on_commit_callbacks
):
    """What the asker types is scrubbed like every tool result before it reaches Claude; the
    conversation still shows them what they typed."""
    fake_claude.script(fake_claude.text("Bo‘ldi."))
    said = "Alisherga +998 90 123 45 67 orqali qo‘ng‘iroq qildimi? @alisher_v ham yozdi"
    client = owner_api(owner)

    conversation, _turn = ask(client, company, said, django_capture_on_commit_callbacks)

    [request] = fake_claude.requests
    sent = json.dumps(request["messages"], ensure_ascii=False)
    assert "123 45 67" not in sent and "@alisher_v" not in sent and "[hidden]" in sent
    shown = client.get(url(company, f"conversations/{conversation['id']}/messages/")).json()
    assert shown[0]["text"] == said


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
