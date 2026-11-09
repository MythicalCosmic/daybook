"""The tutor agent (docs/PLAN-LEARNING.md §6): the weekly report (template, and Claude's
opening with the number check), names only within the reader's branches, "Assign suggested",
nudges after a hard test, its page, and "Ask the tutor"."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.conf import settings
from django.utils import timezone

from apps.ai import agents, chat
from apps.ai.agents import tutor
from apps.ai.models import AgentEvent, AIConversation
from apps.companies.tests.factories import BranchFactory
from apps.inbox import services as inbox
from apps.inbox.models import Notification
from apps.learning import queries
from apps.learning.models import AnswerLog, Attempt, TutorSuggestion
from apps.learning.tests.factories import CourseFactory, LessonFactory
from apps.learning.tests.q2.fixtures import (
    ai_on,
    branch_viewer,
    local,
    person,
    question,
    quiz,
    topic,
)
from apps.members.permissions import Perm
from apps.recognition.models import PointsEntry
from apps.timeoff.models import TimeOff

pytestmark = pytest.mark.django_db

MONDAY = local(2026, 11, 9, 9, 0)


def answers(member, topic_row, shares, at):
    asked = question(member.company, "true_false", topic=topic_row)
    for index, share in enumerate(shares):
        AnswerLog.objects.create(
            company=member.company,
            membership=member,
            question=asked,
            topic=topic_row,
            source="attempt",
            correct=share == 1,
            share=share,
            at=at + timedelta(minutes=index),
        )


@pytest.fixture
def week(pharmacy, staff, manager, monkeypatch):
    """A week of training: Alisher weak in the cold chain, one test, Madina's points."""
    cold = topic(pharmacy)
    madina = person(pharmacy, first_name="Madina", last_name="Saidova")
    answers(staff, cold, [0, 0, 1], MONDAY - timedelta(days=3))
    test = quiz(pharmacy, [question(pharmacy, "true_false", topic=cold)])
    Attempt.objects.create(
        company=pharmacy,
        quiz=test,
        membership=staff,
        started_at=MONDAY - timedelta(days=2),
        finished_at=MONDAY - timedelta(days=2),
        state="finished",
        percent=40,
        passed=False,
    )
    PointsEntry.objects.create(
        company=pharmacy,
        membership=madina,
        points=45,
        reason="quiz",
        key="test:madina",
        at=MONDAY - timedelta(days=1),
    )
    course = CourseFactory(company=pharmacy, title="Sovuq zanjir")
    monkeypatch.setattr(
        queries,
        "courses_for_topic",
        lambda company, topic_id: [course] if topic_id == cold.pk else [],
    )
    state = ai_on(pharmacy)
    return SimpleNamespace(cold=cold, madina=madina, course=course, state=state, test=test)


def reports(member=None):
    rows = Notification.objects.filter(kind="learning.tutor_report")
    return rows.filter(recipient=member) if member else rows


def test_the_tutor_is_an_agent_with_its_settings(pharmacy):
    agent = agents.get("tutor")
    assert (agent.icon, agent.features, agent.needs_claude, agent.default_enabled) == (
        "graduation-cap",
        ("learning",),
        False,
        True,
    )
    assert agent.defaults() == {
        "weekly_report": True,
        "report_day": "0",
        "at": "09:00",
        "nudge_learners": True,
        "suggest": True,
        "weak_threshold": 60,
    }
    assert agent.works_in(pharmacy)
    assert str(agent.schedule(agent.defaults())) == (
        "Workdays at 09:00; the weekly report on Monday"
    )


def test_the_weekly_report_to_each_manager_about_their_people(week, pharmacy, manager, staff):
    done = tutor.run(pharmacy, week.state, MONDAY)
    [report] = reports(manager)
    assert done >= 2  # a suggestion and the report
    assert report.title == "Weekly training report"
    assert "This week: 1 test, 40 % on average." in report.body
    assert "Weakest topic: Sovuq zanjir (39 %)." in report.body
    assert "Most points this week: Madina Saidova (45)." in report.body
    assert "Needs help: Alisher Valiyev (Sovuq zanjir)." in report.body
    assert "1 suggestion waits for you on the tutor's page." in report.body
    assert [action["key"] for action in report.actions] == ["assign"]
    assert report.url == f"/c/{pharmacy.pk}/learning/tutor"
    assert report.data["facts"]["tests"] == {"count": 1, "average": 40}
    assert TutorSuggestion.objects.filter(kind="assign", membership=staff).exists()
    assert set(AgentEvent.objects.filter(agent="tutor").values_list("kind", flat=True)) == {
        "suggestions_made",
        "report_sent",
    }
    # Once a week.
    tutor.run(pharmacy, week.state, MONDAY + timedelta(days=1))
    assert reports(manager).count() == 1


def test_a_branch_manager_hears_only_about_their_people(week, pharmacy, staff):
    yunusobod = BranchFactory(company=pharmacy, name="Yunusobod")
    nigora = person(pharmacy, branch=yunusobod, first_name="Nigora", last_name="Azimova")
    answers(nigora, topic(pharmacy, "Retsept"), [0, 0, 0], MONDAY - timedelta(days=2))
    head = branch_viewer(pharmacy, [yunusobod], perms=(Perm.LEARNING_MANAGE,))
    tutor.run(pharmacy, week.state, MONDAY)
    [report] = reports(head)
    assert "Nigora Azimova" in report.body
    assert "Alisher Valiyev" not in report.body and "Madina Saidova" not in report.body


def test_not_before_the_report_day(week, pharmacy, manager):
    week.state.config = {**week.state.config, "report_day": "2"}
    week.state.save()
    tutor.run(pharmacy, week.state, MONDAY)
    assert not reports().exists()
    tutor.run(pharmacy, week.state, MONDAY + timedelta(days=3))  # Thursday
    assert reports(manager).count() == 1


def test_assign_suggested_accepts_every_open_assign_suggestion(
    week, pharmacy, manager, staff, monkeypatch
):
    given = []
    monkeypatch.setattr(
        "apps.learning.courses.assign",
        lambda course, members, *, by, source="manual", due_at=None: given.append(
            (course.pk, [m.pk for m in members], source)
        ),
    )
    tutor.run(pharmacy, week.state, MONDAY)
    [report] = reports(manager)
    message = inbox.run_action(report.pk, "assign", by=manager)
    assert message == "Assigned 1 course."
    assert given == [(week.course.pk, [staff.pk], "tutor")]
    assert TutorSuggestion.objects.get(kind="assign").state == "accepted"


def test_with_claude_the_report_opens_with_two_sentences(week, pharmacy, manager, fake_claude):
    line = "Bu hafta 1 ta test topshirildi, o‘rtacha 40 %. Sovuq zanjir hali sust."
    fake_claude.script(*(fake_claude.json({"text": line}) for _ in range(3)))
    tutor.run(pharmacy, week.state, MONDAY)
    [report] = reports(manager)
    assert report.body.startswith(line)
    request = fake_claude.requests[0]
    assert request["model"] == settings.AI_MODEL_FAST
    assert request["output_config"]["effort"] == "low"
    assert tutor.REPORT_SYSTEM in request["system"]
    assert "+99890" not in str(request["messages"])  # no phone numbers, ids or pay


def test_a_number_claude_made_up_keeps_the_template(week, pharmacy, manager, fake_claude):
    fake_claude.script(
        *(fake_claude.json({"text": "Bu hafta 17 ta test topshirildi."}) for _ in range(3))
    )
    tutor.run(pharmacy, week.state, MONDAY)
    [report] = reports(manager)
    assert report.body.startswith("Mandatory training") or report.body.startswith("This week")
    assert "17" not in report.body


def test_a_nudge_the_day_after_a_hard_test(week, pharmacy, staff, monkeypatch):
    lesson = LessonFactory(company=pharmacy, title="Muzlatgich va termometr")
    monkeypatch.setattr(queries, "lessons_for_topic", lambda company, topic_id: [lesson])
    attempt = Attempt.objects.get()
    question_row = week.test.items.first().question
    AnswerLog.objects.create(
        company=pharmacy,
        membership=staff,
        question=question_row,
        topic=week.cold,
        source="attempt",
        attempt=attempt,
        correct=False,
        share=0,
        at=attempt.finished_at,
    )
    week.state.config = {**week.state.config, "weekly_report": False}
    week.state.save()
    assert tutor.run(pharmacy, week.state, MONDAY) == 1
    [nudge] = Notification.objects.filter(kind="learning.nudge", recipient=staff)
    assert nudge.title == "Yesterday's test on Sovuq zanjir was hard"
    assert nudge.body == "This lesson helps: Muzlatgich va termometr."
    assert nudge.app_screen == f"lesson:{lesson.pk}"
    assert tutor.run(pharmacy, week.state, MONDAY + timedelta(days=1)) == 0  # one every 3 days


def test_no_nudge_while_on_time_off(week, pharmacy, staff, monkeypatch):
    monkeypatch.setattr(
        queries, "lessons_for_topic", lambda company, topic_id: [LessonFactory(company=company)]
    )
    attempt = Attempt.objects.get()
    AnswerLog.objects.create(
        company=pharmacy,
        membership=staff,
        question=week.test.items.first().question,
        topic=week.cold,
        source="attempt",
        attempt=attempt,
        correct=False,
        share=0,
        at=attempt.finished_at,
    )
    TimeOff.objects.create(
        company=pharmacy,
        membership=staff,
        status="approved",
        first_day=MONDAY.date(),
        last_day=MONDAY.date() + timedelta(days=4),
    )
    week.state.config = {**week.state.config, "weekly_report": False}
    week.state.save()
    assert tutor.run(pharmacy, week.state, MONDAY) == 0


def test_nothing_while_learning_is_off(week, pharmacy):
    pharmacy.features = [feature for feature in pharmacy.features if feature != "learning"]
    pharmacy.save(update_fields=["features"])
    assert tutor.run(pharmacy, week.state, MONDAY) == 0
    assert not reports().exists()
    assert not agents.get("tutor").works_in(pharmacy)


def test_the_tutor_page(week, owner_api, pharmacy, manager):
    client = owner_api(manager)
    page = client.get(f"/api/v1/owner/companies/{pharmacy.pk}/learning/tutor/").json()
    assert page["agent"]["listed"] and page["agent"]["enabled"]
    assert page["report"]["sent_at"] is None  # worked out now: nothing sent yet
    assert "Weakest topic: Sovuq zanjir (39 %)." in page["report"]["lines"]
    tutor.run(pharmacy, week.state, MONDAY)
    page = client.get(f"/api/v1/owner/companies/{pharmacy.pk}/learning/tutor/").json()
    assert page["report"]["sent_at"] is not None and page["report"]["week"] == "2026-W46"
    assert page["suggestions"]["assign"] == 1 and page["suggestions"]["total"] == 1
    assert [row["name"] for row in page["weakest"]] == ["Sovuq zanjir"]
    assert {event["text"] for event in page["events"]} >= {"Made 1 suggestion"}


def may_ask(member):
    member.role.permissions = [*member.role.permissions, Perm.AI_USE]
    member.role.save(update_fields=["permissions"])


def test_ask_the_tutor(week, owner_api, pharmacy, manager, settings):
    settings.AI_FAKE = True
    may_ask(manager)
    client = owner_api(manager)
    made = client.post(f"/api/v1/owner/companies/{pharmacy.pk}/learning/tutor/conversations/")
    assert made.status_code == 201
    conversation = AIConversation.objects.get(pk=made.json()["id"])
    assert conversation.agent == "tutor"
    assert tutor.CHAT_SYSTEM in chat.system_text(conversation, pharmacy)
    from apps.ai.tools.registry import ToolContext

    ctx = ToolContext.for_member(manager)
    assert {
        tool.domain for tool in chat.conversation_tools(conversation, ctx)
    } <= tutor.CHAT_DOMAINS
    turn = chat.start_turn(conversation, by=manager, text="Kim sust?")
    chat.run_turn(turn.pk)
    turn.refresh_from_db()
    assert turn.status == "done"
    assert "The weakest topics right now" in turn.text and "Sovuq zanjir" in turn.text
    listed = client.get(f"/api/v1/owner/companies/{pharmacy.pk}/learning/tutor/conversations/")
    assert [row["id"] for row in listed.json()] == [conversation.pk]
    ask_ai = client.get(f"/api/v1/owner/companies/{pharmacy.pk}/ai/conversations/").json()
    assert conversation.pk not in [row["id"] for row in ask_ai]


def test_ask_the_tutor_needs_learning(owner_api, pharmacy, manager, settings):
    settings.AI_FAKE = True
    may_ask(manager)
    ai_on(pharmacy)
    pharmacy.features = [feature for feature in pharmacy.features if feature != "learning"]
    pharmacy.save(update_fields=["features"])
    made = owner_api(manager).post(
        f"/api/v1/owner/companies/{pharmacy.pk}/learning/tutor/conversations/"
    )
    assert made.status_code == 404
    assert timezone.now()  # the clock is real here
