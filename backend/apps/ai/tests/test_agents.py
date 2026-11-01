"""The agents: registry, the deadline watcher, the morning plan, the photo checker, the runner,
and their owner endpoints (v0.2 AI contract §3, §5)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.ai import agents, events, services
from apps.ai.agents import deadline_watcher, morning_plan, photo_checker, runner
from apps.ai.models import AgentEvent, AgentState
from apps.reminders import engine
from apps.tasks import services as task_services
from apps.tasks.models import Task, TaskComment
from apps.tasks.tests.factories import TaskFactory

pytestmark = pytest.mark.django_db

ZONE = ZoneInfo("Asia/Tashkent")


def local(hour: int, minute: int = 0, days: int = 0) -> datetime:
    today = timezone.localtime(timezone.now(), ZONE).date() + timedelta(days=days)
    return datetime(today.year, today.month, today.day, hour, minute, tzinfo=ZONE)


@pytest.fixture
def crew(company, member, ai_on):
    ai_on(company)
    company.timezone = "Asia/Tashkent"
    company.workdays = [0, 1, 2, 3, 4, 5, 6]
    company.save()
    giver = member.registered(company, "Manager", first_name="Bekzod", last_name="Mirzayev")
    worker = member.registered(company, first_name="Alisher", last_name="Valiyev")
    for person in (giver, worker):
        person.user.telegram_id = 9_000_000 + person.pk
        person.user.save(update_fields=["telegram_id"])
    for key in ("deadline_watcher", "morning_plan"):
        state = agents.state_of(company, key)
        state.enabled = True
        state.save()
    return {"giver": giver, "worker": worker}


def late_task(crew, hours: int = 3, **fields) -> Task:
    return TaskFactory(
        company=crew["giver"].company,
        kind=Task.Kind.ASSIGNED,
        created_by=crew["giver"],
        assignee=crew["worker"],
        due_at=local(12) - timedelta(hours=hours),
        title="Muzlatgich haroratini tekshirish",
        **fields,
    )


def test_the_agents_in_the_dashboards_order():
    assert [agent.key for agent in agents.all_agents()] == [
        "voice_tasks",
        "deadline_watcher",
        "morning_plan",
        "photo_checker",
    ]
    assert agents.get("photo_checker").needs_claude
    assert not agents.get("photo_checker").default_enabled


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"escalate_after_hours": 0}, "escalate_after_hours"),
        ({"escalate_after_hours": 49}, "escalate_after_hours"),
        ({"escalate_after_hours": "2"}, "escalate_after_hours"),
        ({"quiet_from": "25:00"}, "quiet_from"),
        ({"nope": True}, "nope"),
    ],
)
def test_settings_are_checked_against_the_fields(changes, error):
    agent = agents.get("deadline_watcher")

    with pytest.raises(ValidationError) as raised:
        agents.clean_config(agent, changes, agent.defaults())

    assert error in raised.value.message_dict


def test_late_work_reaches_its_giver_once(crew, sent_messages, django_capture_on_commit_callbacks):
    task = late_task(crew)
    state = agents.state_of(crew["giver"].company, deadline_watcher.KEY)

    with django_capture_on_commit_callbacks(execute=True):
        told = deadline_watcher.run(task.company, state, local(12))
    with django_capture_on_commit_callbacks(execute=True):
        again = deadline_watcher.run(task.company, state, local(12, 30))

    assert (told, again) == (1, 0)
    [message] = sent_messages
    assert message["chat_id"] == crew["giver"].user.telegram_id
    assert "Muzlatgich haroratini tekshirish" in message["text"]
    assert "ail:hour:" in str(message["reply_markup"])
    event = AgentEvent.objects.get(agent="deadline_watcher")
    assert (event.subject_type, event.subject_id, event.level) == ("task", task.pk, "warning")
    task.refresh_from_db()
    assert task.escalated_at is not None


def test_what_the_reminders_escalated_is_left_alone(crew, sent_messages):
    late_task(crew, escalated_at=local(10))
    state = agents.state_of(crew["giver"].company, deadline_watcher.KEY)

    assert deadline_watcher.run(crew["giver"].company, state, local(12)) == 0
    assert sent_messages == []


def test_the_reminders_do_not_escalate_again_what_the_watcher_did(crew, sent_messages):
    task = late_task(crew)
    state = agents.state_of(crew["giver"].company, deadline_watcher.KEY)
    deadline_watcher.run(task.company, state, local(12))
    Task.objects.filter(pk=task.pk).update(reminders_sent=5, next_reminder_at=local(11))

    claim = engine._claim(task.pk, local(12, 5))

    assert claim is None or claim.escalate is False


def test_not_late_enough_quiet_hours_and_blocked_work_wait(crew, sent_messages):
    company = crew["giver"].company
    state = agents.state_of(company, deadline_watcher.KEY)
    late_task(crew, hours=1)  # under the 2 hours
    late_task(crew, blocked_at=local(9))  # "can't do it": its own flow

    assert deadline_watcher.run(company, state, local(12)) == 0
    late_task(crew)
    assert deadline_watcher.run(company, state, local(22)) == 0  # quiet from 21:00
    assert deadline_watcher.run(company, state, local(12)) == 1


def test_when_the_giver_is_gone_the_head_hears(crew, company, member, sent_messages):
    from apps.members.models import Department, Membership

    head = member.registered(company, "Manager", first_name="Dilnoza")
    head.user.telegram_id = 9_100_000
    head.user.save(update_fields=["telegram_id"])
    Department.objects.create(company=company, name="Chilonzor", head=head)
    department = Department.objects.get(company=company)
    Membership.objects.filter(pk=crew["worker"].pk).update(department=department)
    task = late_task(crew)
    Membership.objects.filter(pk=crew["giver"].pk).update(status=Membership.Status.LEFT)

    assert deadline_watcher.run(company, agents.state_of(company, deadline_watcher.KEY), local(12))
    assert AgentEvent.objects.get(subject_id=task.pk).params["to"] == str(head)


def test_an_hour_more(crew):
    task = late_task(crew)

    services.give_an_hour(task.pk, by=crew["giver"])

    task.refresh_from_db()
    assert (
        timezone.now() + timedelta(minutes=55)
        < task.due_at
        <= timezone.now() + timedelta(minutes=66)
    )
    with pytest.raises(PermissionDenied):  # the assignee can't move their own deadline
        services.give_an_hour(task.pk, by=crew["worker"])


def test_an_hour_more_is_only_for_tasks_the_tapper_may_see(crew, company, member):
    """The button's task id can be forged: someone who gives work in one branch must not move
    the deadline of a task in another branch they can't even open."""
    from apps.companies.models import Branch
    from apps.core.exceptions import DomainError
    from apps.members.models import AccessRole
    from apps.members.permissions import Perm

    here, there = (Branch.objects.create(company=company, name=name) for name in ("A", "B"))
    AccessRole.objects.create(company=company, name="Branch lead", permissions=[Perm.TASKS_ASSIGN])
    lead = member.registered(company, "Branch lead", home_branch=here)
    lead.branches.add(here)
    task = late_task(crew, branch=there)
    due = task.due_at

    with pytest.raises((DomainError, PermissionDenied)):
        services.give_an_hour(task.pk, by=lead)

    task.refresh_from_db()
    assert task.due_at == due


def test_a_head_who_cannot_change_the_task_gets_no_hour_button(
    crew, company, member, sent_messages, django_capture_on_commit_callbacks
):
    """When the giver is gone the assignee's head hears; a head without the right to change
    the task gets Open only, not a "+1 hour" that would answer "You can't change this task"."""
    from apps.members.models import Department, Membership

    head = member.registered(company, first_name="Dilnoza")  # a head, but an Employee's rights
    head.user.telegram_id = 9_100_000
    head.user.save(update_fields=["telegram_id"])
    department = Department.objects.create(company=company, name="Chilonzor", head=head)
    Membership.objects.filter(pk=crew["worker"].pk).update(department=department)
    late_task(crew)
    Membership.objects.filter(pk=crew["giver"].pk).update(status=Membership.Status.LEFT)

    with django_capture_on_commit_callbacks(execute=True):
        deadline_watcher.run(company, agents.state_of(company, deadline_watcher.KEY), local(12))

    [message] = sent_messages
    assert message["chat_id"] == head.user.telegram_id
    assert "ail:hour:" not in str(message["reply_markup"])


def test_the_morning_plan_says_the_teams_day(
    crew, sent_messages, django_capture_on_commit_callbacks
):
    company = crew["giver"].company
    late_task(crew, hours=27)  # yesterday 09:00
    TaskFactory(
        company=company,
        kind=Task.Kind.ASSIGNED,
        created_by=crew["giver"],
        assignee=crew["worker"],
        due_at=local(17),
        title="Kassani sanash",
    )
    state = agents.state_of(company, morning_plan.KEY)

    with django_capture_on_commit_callbacks(execute=True):
        sent = morning_plan.run(company, state, local(8, 35))
    with django_capture_on_commit_callbacks(execute=True):
        again = morning_plan.run(company, state, local(9))

    assert (sent, again) == (1, 0)
    [plan] = sent_messages
    assert plan["chat_id"] == crew["giver"].user.telegram_id
    assert "Due today: 1" in plan["text"] and "Late: 1" in plan["text"]
    assert "Muzlatgich haroratini tekshirish" in plan["text"]
    event = AgentEvent.objects.get(agent="morning_plan")
    assert event.params == {"to": "Bekzod Mirzayev", "due_today": 1, "late": 1, "to_check": 0}


def test_the_morning_plan_tells_only_what_the_reader_may_see(
    crew, company, member, sent_messages, django_capture_on_commit_callbacks
):
    """Someone's own personal tasks are theirs alone (tasks.queries.visible_tasks), and a
    manager who may give work but not see everyone's tasks hears only about work they can
    open: neither is counted or named in the plan."""
    from apps.members.models import AccessRole
    from apps.members.permissions import Perm

    TaskFactory(
        company=company,
        kind=Task.Kind.PERSONAL,
        created_by=crew["worker"],
        assignee=crew["worker"],
        due_at=local(12) - timedelta(hours=27),
        title="Shifokorga borish",
    )
    AccessRole.objects.create(company=company, name="Shift lead", permissions=[Perm.TASKS_ASSIGN])
    lead = member.registered(company, "Shift lead", first_name="Jasur")
    lead.user.telegram_id = 9_100_000 + lead.pk
    lead.user.save(update_fields=["telegram_id"])
    late_task(crew, hours=27)  # the giver's work, not the shift lead's to see

    with django_capture_on_commit_callbacks(execute=True):
        morning_plan.run(company, agents.state_of(company, morning_plan.KEY), local(8, 35))

    texts = {message["chat_id"]: message["text"] for message in sent_messages}
    for text in texts.values():
        assert "Shifokorga" not in text
    assert "Late: 1" in texts[crew["giver"].user.telegram_id]
    assert lead.user.telegram_id not in texts  # nothing he may see is late


def test_nothing_to_say_means_no_plan(crew, sent_messages):
    company = crew["giver"].company

    assert morning_plan.run(company, agents.state_of(company, morning_plan.KEY), local(8, 35)) == 0
    assert sent_messages == []


def test_with_claude_the_plan_has_a_summary(
    crew, fake_claude, sent_messages, django_capture_on_commit_callbacks
):
    company = crew["giver"].company
    late_task(crew, hours=27)
    fake_claude.script(fake_claude.json({"summary": "Bitta vazifa kechikmoqda. Tekshiring."}))

    with django_capture_on_commit_callbacks(execute=True):
        morning_plan.run(company, agents.state_of(company, morning_plan.KEY), local(8, 35))

    assert "Bitta vazifa kechikmoqda." in sent_messages[0]["text"]
    [request] = fake_claude.requests
    assert request["model"] == "claude-haiku-5-5"
    assert "fallbacks" not in request  # Haiku has none
    assert "temperature" not in request and "top_p" not in request
    assert request["output_config"]["effort"] == "low"


def test_the_next_plan_is_on_a_workday(crew):
    company = crew["giver"].company
    company.workdays = [0, 1, 2, 3, 4]  # Monday to Friday
    friday = datetime(2026, 11, 6, 9, 0, tzinfo=ZONE)

    moment = morning_plan.next_run({"at": "08:30"}, friday, company)

    assert moment == datetime(2026, 11, 9, 8, 30, tzinfo=ZONE)  # Monday


# The photo checker -----------------------------------------------------------------------------


@pytest.fixture
def photo_task(crew, settings):
    company = crew["giver"].company
    state = agents.state_of(company, photo_checker.KEY)
    state.enabled = True
    state.save()
    task = TaskFactory(
        company=company,
        kind=Task.Kind.ASSIGNED,
        created_by=crew["giver"],
        assignee=crew["worker"],
        proof="photo",
        title="Muzlatgich haroratini tekshirish",
    )
    return task


def finish_with_photo(task, worker):
    from io import BytesIO

    from PIL import Image

    data = BytesIO()
    Image.new("RGB", (40, 40), "white").save(data, "JPEG")
    return task_services.complete_task(
        task, by=worker, proof_photo=ContentFile(data.getvalue(), name="proof.jpg")
    )


def test_a_proof_photo_gets_a_note_with_fake_ai(photo_task, crew, settings):
    settings.AI_FAKE = True
    task = finish_with_photo(photo_task, crew["worker"])

    verdict = photo_checker.check(task.pk, task.completed_at.isoformat())

    assert verdict == "looks_right"
    [note] = TaskComment.objects.filter(task=task, author=None)
    assert note.text.startswith("AI: ")
    assert AgentEvent.objects.get(agent="photo_checker").level == "success"
    assert photo_checker.check(task.pk, task.completed_at.isoformat()) is None  # once


def test_an_undone_completion_is_not_checked(photo_task, crew, settings):
    settings.AI_FAKE = True
    task = finish_with_photo(photo_task, crew["worker"])
    stamp = task.completed_at.isoformat()
    task_services.reopen_task(task, by=crew["worker"])

    assert photo_checker.check(task.pk, stamp) is None


def test_claude_sees_the_photo_and_the_task(photo_task, crew, fake_claude):
    task = finish_with_photo(photo_task, crew["worker"])
    fake_claude.script(
        fake_claude.json({"verdict": "check", "note": "Termometr 11 °C ko‘rsatmoqda."})
    )

    assert photo_checker.check(task.pk, task.completed_at.isoformat()) == "check"

    [request] = fake_claude.requests
    content = request["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/jpeg"
    assert "Muzlatgich haroratini tekshirish" in content[1]["text"]
    assert request["fallbacks"] == "default"  # Opus
    assert TaskComment.objects.get(task=task).text == "AI: Termometr 11 °C ko‘rsatmoqda."


def test_the_photo_checker_sends_no_phone_numbers_or_usernames(photo_task, crew, fake_claude):
    """Task texts are written by staff: a phone number or a @username in the description or a
    step is hidden before the task goes to Claude (apps.ai.tools.scrub), as everywhere else."""
    from apps.tasks.models import ChecklistItem

    Task.objects.filter(pk=photo_task.pk).update(
        description="Yetkazib beruvchi: +998 90 123 45 67, @alisher_v ga yozing"
    )
    ChecklistItem.objects.create(task=photo_task, text="Natijani 998901234567 ga yuboring", order=0)
    photo_task.refresh_from_db()
    task = finish_with_photo(photo_task, crew["worker"])
    fake_claude.script(fake_claude.json({"verdict": "looks_right", "note": "5 °C."}))

    photo_checker.check(task.pk, task.completed_at.isoformat())

    [request] = fake_claude.requests
    text = request["messages"][0]["content"][1]["text"]
    assert "123 45 67" not in text and "@alisher_v" not in text and "998901234567" not in text
    assert "[hidden]" in text and "Yetkazib beruvchi" in text


def test_the_photo_checker_is_opt_in(crew, fake_claude):
    task = TaskFactory(company=crew["giver"].company, assignee=crew["worker"], proof="photo")
    finished = finish_with_photo(task, crew["worker"])

    assert photo_checker.check(finished.pk, finished.completed_at.isoformat()) is None
    assert fake_claude.requests == []


def test_finishing_with_a_photo_queues_the_check(
    photo_task, crew, settings, monkeypatch, django_capture_on_commit_callbacks
):
    queued = []
    monkeypatch.setattr(
        "apps.ai.tasks.check_proof_photo.apply_async",
        lambda args, countdown: queued.append((args, countdown)),
    )

    with django_capture_on_commit_callbacks(execute=True):
        task = finish_with_photo(photo_task, crew["worker"])

    assert queued == [((task.pk, task.completed_at.isoformat()), 65)]


# The runner ------------------------------------------------------------------------------------


def test_the_tick_runs_what_is_due_and_moves_it_on(crew, sent_messages):
    company = crew["giver"].company
    late_task(crew)
    AgentState.objects.filter(company=company).update(next_run_at=None)

    runner.tick(local(12))
    state = AgentState.objects.get(company=company, key="deadline_watcher")
    assert state.last_status == "ok" and state.last_run_at == local(12)
    assert state.next_run_at == local(12, 30)
    assert state.running_since is None

    runner.tick(local(12, 10))  # not due yet
    assert AgentState.objects.get(pk=state.pk).last_run_at == local(12)


def test_with_ai_off_no_agent_runs(crew, sent_messages):
    from apps.ai import conf

    company = crew["giver"].company
    late_task(crew)
    row = conf.get_settings(company)
    row.enabled = False
    row.save()

    assert runner.tick(local(12)) == 0
    assert not AgentEvent.objects.exists()


def test_a_failing_agent_is_recorded(crew, monkeypatch):
    import dataclasses

    from apps.ai.agents import registry

    company = crew["giver"].company
    state = AgentState.objects.get(company=company, key="deadline_watcher")

    def broken(*args):
        raise RuntimeError("boom")

    broken_agent = dataclasses.replace(deadline_watcher.AGENT, run=broken)
    monkeypatch.setitem(registry._agents, "deadline_watcher", broken_agent)
    runner.run_state(state.pk, local(12), forced=True)

    state.refresh_from_db()
    assert state.last_status == "error" and "boom" in state.last_error


def test_an_agent_that_cannot_even_be_scheduled_does_not_stop_the_tick(
    crew, company, member, ai_on, sent_messages, django_capture_on_commit_callbacks
):
    """A setting stored before it was checked (an old row, the Django admin) breaks the agent's
    next time: that agent is recorded as failed, and the other agents and companies still run."""
    from apps.companies.tests.factories import CompanyFactory

    late_task(crew)
    other = CompanyFactory(timezone="Asia/Tashkent")
    ai_on(other)
    for company_ in (company, other):
        AgentState.objects.filter(company=company_).update(next_run_at=None)
        state = agents.state_of(company_, morning_plan.KEY)
        state.enabled = True
        state.config = {"at": "half past eight", "who": "both"}
        state.next_run_at = None
        state.save()
    broken = AgentState.objects.filter(key=morning_plan.KEY)

    with django_capture_on_commit_callbacks(execute=True):
        runner.tick(local(12))

    watcher = AgentState.objects.get(company=company, key=deadline_watcher.KEY)
    assert watcher.last_status == "ok"
    assert len(sent_messages) == 1  # the late task still reached its giver
    assert set(broken.values_list("last_status", flat=True)) == {"error"}
    assert all(row.next_run_at is not None for row in broken)  # tried again later, not each tick


# Events in three languages ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("language", "text"),
    [
        ("en", "Told Bekzod Mirzayev that «Kassa» is late (Alisher Valiyev)"),
        ("uz", "Bekzod Mirzayev"),
        ("ru", "Bekzod Mirzayev"),
    ],
)
def test_events_read_in_the_readers_language(company, language, text):
    event = events.log(
        company,
        "deadline_watcher",
        "escalated",
        params={"task": "Kassa", "assignee": "Alisher Valiyev", "to": "Bekzod Mirzayev"},
    )

    rendered = events.render(event, language)

    assert text in rendered
    assert "Kassa" in rendered
    if language != "en":
        assert rendered != events.render(event, "en")


def test_plural_events_count_in_every_language(company):
    event = events.log(
        company, "voice_tasks", "draft_ready", params={"count": 3, "author": "Bekzod"}
    )

    assert events.render(event, "en") == "Understood 3 tasks from Bekzod"
    assert "3" in events.render(event, "ru") and "Bekzod" in events.render(event, "ru")
    assert "3 ta" in events.render(event, "uz")


# The owner endpoints ----------------------------------------------------------------------------


def owner_url(company, path):
    return f"/api/v1/owner/companies/{company.pk}/ai/{path}"


def test_the_agents_list(owner_api, crew, company, member):
    owner = member.registered(company, "Owner")

    rows = owner_api(owner).get(owner_url(company, "agents/")).json()

    assert [row["key"] for row in rows] == [
        "voice_tasks",
        "deadline_watcher",
        "morning_plan",
        "photo_checker",
    ]
    watcher = rows[1]
    assert set(watcher) == {
        "key",
        "name",
        "description",
        "icon",
        "enabled",
        "needs_claude",
        "available",
        "unavailable_reason",
        "schedule",
        "running",
        "last_run_at",
        "next_run_at",
        "stats",
        "config",
        "fields",
    }
    assert watcher["icon"] == "alarm-clock"
    assert watcher["config"] == {
        "escalate_after_hours": 2,
        "quiet_from": "21:00",
        "quiet_to": "08:00",
    }
    assert watcher["fields"][0] == {
        "key": "escalate_after_hours",
        "type": "int",
        "label": "Late by",
        "help": "How late a task is before its giver hears.",
        "min": 1,
        "max": 48,
        "unit": "hours",
    }
    assert rows[3]["unavailable_reason"] == "needs_claude"
    assert rows[0]["unavailable_reason"] == "needs_speech"
    assert rows[2]["fields"][1]["options"][2] == {"value": "both", "label": "Heads and managers"}


def test_changing_an_agent_needs_ai_configure(owner_api, crew, company, member):
    owner = member.registered(company, "Owner")
    url = owner_url(company, "agents/deadline_watcher/")

    assert owner_api(crew["giver"]).patch(url, {"enabled": False}, format="json").status_code == 403
    response = owner_api(owner).patch(url, {"config": {"escalate_after_hours": 4}}, format="json")
    assert response.status_code == 200
    assert response.json()["config"]["escalate_after_hours"] == 4
    bad = owner_api(owner).patch(url, {"config": {"escalate_after_hours": 99}}, format="json")
    assert bad.status_code == 400
    off = owner_api(owner).patch(url, {"enabled": False}, format="json")
    assert off.json()["enabled"] is False
    missing = owner_api(owner).patch(owner_url(company, "agents/nope/"), {}, format="json")
    assert missing.status_code == 404


def test_run_now(
    owner_api, crew, company, member, sent_messages, django_capture_on_commit_callbacks
):
    owner = member.registered(company, "Owner")
    late_task(crew)

    with django_capture_on_commit_callbacks(execute=True):
        response = owner_api(owner).post(owner_url(company, "agents/deadline_watcher/run/"))

    assert response.status_code == 202 and response.json() == {"queued": True}
    assert AgentState.objects.get(company=company, key="deadline_watcher").last_run_at
    voice = owner_api(owner).post(owner_url(company, "agents/voice_tasks/run/"))
    assert voice.status_code == 400  # not scheduled


def test_the_activity_feed(owner_api, crew, company, member):
    owner = member.registered(company, "Owner")
    for index in range(5):
        events.log(
            company,
            "deadline_watcher",
            "escalated",
            params={"task": f"Task {index}", "assignee": "Alisher", "to": "Bekzod"},
            subject=("task", late_task(crew).pk),
        )
    client = owner_api(owner)

    first = client.get(owner_url(company, "activity/?limit=3")).json()
    rest = client.get(owner_url(company, f"activity/?limit=3&before={first['next_before']}")).json()

    assert len(first["results"]) == 3 and first["next_before"] is not None
    assert len(rest["results"]) == 2 and rest["next_before"] is None
    item = first["results"][0]
    assert set(item) == {
        "id",
        "agent",
        "agent_name",
        "icon",
        "kind",
        "level",
        "text",
        "created_at",
        "actor",
        "subject",
    }
    assert item["text"] == "Told Bekzod that «Task 4» is late (Alisher)"
    assert item["subject"]["type"] == "task"
    assert item["subject"]["label"] == "Muzlatgich haroratini tekshirish"
    only = client.get(owner_url(company, "activity/?agent=morning_plan")).json()
    assert only["results"] == []


def test_the_activity_feed_keeps_to_the_readers_branches(owner_api, crew, company, member):
    """Someone who sees one branch reads the events about that branch: not those about another
    branch, nor those about company-wide work or people without a branch (apps.members.scope:
    rows without a branch are for those who see every branch)."""
    from apps.companies.models import Branch
    from apps.members.models import AccessRole
    from apps.members.permissions import Perm

    here, there = (Branch.objects.create(company=company, name=name) for name in ("A", "B"))
    AccessRole.objects.create(
        company=company, name="Branch view", permissions=[Perm.DASHBOARD_ACCESS]
    )
    reader = member.registered(company, "Branch view", home_branch=here)
    reader.branches.add(here)
    for title, branch in (("Here", here), ("There", there), ("Nowhere", None)):
        task = late_task(crew, branch=branch)
        events.log(
            company,
            "deadline_watcher",
            "escalated",
            params={"task": title, "assignee": "Alisher", "to": "Bekzod"},
            subject=("task", task.pk),
            branch_id=branch.pk if branch else None,
        )

    page = owner_api(reader).get(owner_url(company, "activity/")).json()

    assert [item["text"] for item in page["results"]] == [
        "Told Bekzod that «Here» is late (Alisher)"
    ]
