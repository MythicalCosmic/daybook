"""The agents an owner makes in their own words (apps.ai.agents.custom, briefs/v6-k.md): their
schedules, the cap, a run (Claude's tool loop with the owner's rights, one message per person in
their language), pausing, the budget, deleting, and the owner endpoints.

The reference moment is Tuesday 3 November 2026, 10:00 in Tashkent (UTC+5, no DST); the
pharmacy works Monday to Friday and has two branches, Chilonzor and Yunusobod.
"""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import translation

from apps.ai import agents, events, queries, services
from apps.ai.agents import custom, custom_templates, runner
from apps.ai.audit_actions import AIAction
from apps.ai.models import AgentEvent, AgentRun, AgentState, AIUsage, CustomAgent
from apps.audit.models import AuditLog
from apps.companies.models import Branch
from apps.core.exceptions import DomainError
from apps.groups.models import TelegramGroup
from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm
from apps.notifications.telegram import BotName
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory

pytestmark = pytest.mark.django_db

TZ = ZoneInfo("Asia/Tashkent")
NOW = datetime(2026, 11, 3, 10, 0, tzinfo=TZ)  # a Tuesday
JOB = "Har ish kuni kechqurun kunni xulosa qil: nechta vazifa bajarildi va qaysilari kechikdi."
REPORT_UZ = "Bugun 1 ta vazifa kechikdi: Muzlatgich haroratini tekshirish (Alisher Valiyev)."
REPORT_RU = "Сегодня просрочена 1 задача: Проверить температуру холодильника (Алишер Валиев)."


def at(day: int, hour: int, minute: int = 0, month: int = 11, zone=TZ) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=zone)


@pytest.fixture(autouse=True)
def _default_language_after():
    """The owner endpoints answer in the reader's language and leave it active: these tests'
    readers speak Uzbek and Russian, so the tests after them get the default back."""
    yield
    translation.deactivate()


@pytest.fixture
def crew(company, member, ai_on, freeze, fake_claude):
    """AI on (Claude answered by the script), at NOW: the owner Dilnoza (Uzbek), the manager
    Bekzod (Russian, no AI rights), Alisher who works at Chilonzor, and Madina, who may set up
    AI but sees only Chilonzor."""
    freeze(NOW)
    company.timezone = "Asia/Tashkent"
    company.workdays = [0, 1, 2, 3, 4]
    company.save()
    ai_on(company)
    chilonzor = company.branches.order_by("order", "pk").first() or Branch.objects.create(
        company=company, name="Chilonzor"
    )
    yunusobod = Branch.objects.create(company=company, name="Yunusobod", code="YNS", order=1)
    AccessRole.objects.create(
        company=company,
        name="Branch lead",
        permissions=[
            Perm.DASHBOARD_ACCESS,
            Perm.AI_USE,
            Perm.AI_CONFIGURE,
            Perm.TASKS_VIEW_ALL,
            Perm.REPORTS_VIEW,
        ],
    )
    people = SimpleNamespace(
        company=company,
        chilonzor=chilonzor,
        yunusobod=yunusobod,
        owner=member.registered(company, "Owner", first_name="Dilnoza", last_name="Karimova"),
        manager=member.registered(company, "Manager", first_name="Bekzod", last_name="Mirzayev"),
        worker=member.registered(company, first_name="Alisher", last_name="Valiyev"),
        lead=member.registered(company, "Branch lead", first_name="Madina", last_name="Saidova"),
    )
    for person, language in (
        (people.owner, "uz"),
        (people.manager, "ru"),
        (people.worker, "uz"),
        (people.lead, "uz"),
    ):
        person.user.telegram_id = 9_200_000 + person.pk
        person.user.language = language
        person.user.save(update_fields=["telegram_id", "language"])
    for person in (people.worker, people.lead):
        person.branches.set([chilonzor])
        person.home_branch = chilonzor
        person.save(update_fields=["home_branch"])
    return people


def english(person) -> None:
    """`person` reads the dashboard in English (its answers don't change with the .po files)."""
    person.user.language = "en"
    person.user.save(update_fields=["language"])


def make(crew, by=None, **data) -> CustomAgent:
    data = {
        "name": "Kechki hisobot",
        "job": JOB,
        "frequency": "weekdays",
        "at": "20:00",
        "recipients": "me",
        "domains": ["tasks"],
    } | data
    return services.create_custom_agent(crew.company, by=by or crew.owner, data=data)


def late_task(crew, branch=None, title="Muzlatgich haroratini tekshirish") -> Task:
    return TaskFactory(
        company=crew.company,
        kind=Task.Kind.ASSIGNED,
        created_by=crew.owner,
        assignee=crew.worker,
        branch=branch or crew.chilonzor,
        due_at=NOW - timedelta(hours=3),
        title=title,
    )


def tool_use(name: str, payload: dict, call_id: str = "toolu_1", **kwargs):
    from apps.ai.fakes import FakeAnthropic

    block = {"type": "tool_use", "id": call_id, "name": name, "input": payload}
    return FakeAnthropic.message([block], stop_reason="tool_use", **kwargs)


def run_due(row: CustomAgent, moment: datetime, *, forced: bool = False, due=None) -> int:
    """Its scheduled run at `moment` (due then, unless `due` says otherwise), as a tick runs it."""
    state = AgentState.objects.get(company=row.company, key=row.key)
    AgentState.objects.filter(pk=state.pk).update(next_run_at=due or moment)
    return runner.run_state(state.pk, moment, forced=forced)


def system_text(request) -> str:
    system = request["system"]
    return system if isinstance(system, str) else "".join(block["text"] for block in system)


def tool_results(request) -> list[dict]:
    blocks = [
        block
        for message in request["messages"]
        if message["role"] == "user"
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    return [json.loads(block["content"]) for block in blocks]


# Schedules ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "now", "expected"),
    [
        # Every day: today's 20:00 while it is ahead, else tomorrow's.
        ({"frequency": "daily", "at": "20:00"}, at(3, 10), at(3, 20)),
        ({"frequency": "daily", "at": "20:00"}, at(3, 20), at(4, 20)),
        # Workdays (Monday to Friday here): Friday evening goes on to Monday.
        ({"frequency": "weekdays", "at": "20:00"}, at(6, 21), at(9, 20)),
        ({"frequency": "weekdays", "at": "08:30"}, at(7, 9), at(9, 8, 30)),
        # Once a week, on Mondays.
        ({"frequency": "weekly", "weekday": 0, "at": "09:00"}, at(3, 10), at(9, 9)),
        ({"frequency": "weekly", "weekday": 1, "at": "11:00"}, at(3, 10), at(3, 11)),
        # Once a month, on the 1st.
        ({"frequency": "monthly", "month_day": 1, "at": "09:00"}, at(3, 10), at(1, 9, month=12)),
        ({"frequency": "monthly", "month_day": 28, "at": "18:00"}, at(3, 10), at(28, 18)),
    ],
)
def test_it_runs_on_its_schedule_in_the_company_timezone(crew, data, now, expected):
    row = make(crew, **data)

    moment = custom.next_run(row, now, crew.company)

    assert moment == expected
    assert moment.utcoffset() == timedelta(hours=5)  # Tashkent keeps no summer time


def test_the_workdays_are_the_companys_own(crew):
    crew.company.workdays = [0, 1, 2, 3, 4, 5]  # Monday to Saturday
    crew.company.save(update_fields=["workdays"])
    row = make(crew)

    assert custom.next_run(row, at(6, 21), crew.company) == at(7, 20)  # Saturday


def test_a_summer_time_change_keeps_the_local_hour(crew):
    berlin = ZoneInfo("Europe/Berlin")  # summer time ends on 25 October 2026
    crew.company.timezone = "Europe/Berlin"
    crew.company.save(update_fields=["timezone"])
    row = make(crew, frequency="daily", at="20:00")

    before = custom.next_run(row, datetime(2026, 10, 24, 12, 0, tzinfo=berlin), crew.company)
    after = custom.next_run(row, before, crew.company)

    assert (before.hour, before.utcoffset()) == (20, timedelta(hours=2))
    assert (after.day, after.hour, after.utcoffset()) == (25, 20, timedelta(hours=1))


def test_its_schedule_reads_in_the_readers_language(crew):
    weekly = make(crew, name="Dushanba", frequency="weekly", weekday=0, at="09:00")
    monthly = make(crew, name="Oy", frequency="monthly", month_day=1, at="09:00")

    with translation.override("en"):
        assert custom.schedule_text(make(crew)) == "Workdays at 20:00"
        assert custom.schedule_text(weekly) == "Every week: Monday at 09:00"
        assert custom.schedule_text(monthly) == "Every month: day 1 at 09:00"


def test_it_is_switched_on_at_its_first_time(crew, fake_claude):
    row = make(crew)

    state = AgentState.objects.get(company=crew.company, key=row.key)
    assert state.enabled
    assert state.next_run_at == at(3, 20)


# Making one --------------------------------------------------------------------------------------


def test_a_company_has_at_most_ten(crew):
    for number in range(10):
        make(crew, name=f"Agent {number}")

    with pytest.raises(DomainError):
        make(crew, name="The eleventh")
    services.delete_custom_agent(CustomAgent.objects.first(), by=crew.owner)
    assert make(crew, name="The eleventh again").name == "The eleventh again"
    assert custom.live(crew.company).count() == 10


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"name": "  "}, "name"),
        ({"name": "x" * 61}, "name"),
        ({"job": "short"}, "job"),
        ({"job": "x" * 2001}, "job"),
        ({"frequency": "hourly"}, "frequency"),
        ({"at": "25:00"}, "at"),
        ({"frequency": "weekly", "weekday": None}, "weekday"),
        ({"frequency": "weekly", "weekday": 7}, "weekday"),
        ({"frequency": "monthly", "month_day": 31}, "month_day"),
        ({"recipients": "everyone"}, "recipients"),
        ({"recipients": "people", "people": []}, "people"),
        ({"recipients": "group", "group": None}, "group"),
        ({"domains": []}, "domains"),
        ({"domains": ["weather"]}, "domains"),
        ({"color": "gold"}, "color"),
    ],
)
def test_what_it_needs_is_checked(crew, changes, field):
    with pytest.raises(ValidationError) as raised:
        make(crew, **changes)

    assert field in raised.value.message_dict


def test_it_writes_only_to_people_who_can_get_telegram(crew, member):
    newcomer = member.registered(crew.company, first_name="Jasur", last_name="Tursunov")
    newcomer.user.telegram_id = None  # never started the bot
    newcomer.user.save(update_fields=["telegram_id"])
    other = member.registered(crew.company, first_name="Nigora", last_name="Azimova")
    other.user.telegram_id = 9_299_999
    other.user.save(update_fields=["telegram_id"])
    other.status = Membership.Status.LEFT
    other.save(update_fields=["status"])

    with pytest.raises(ValidationError) as no_bot:
        make(crew, recipients="people", people=[newcomer.pk])
    with pytest.raises(ValidationError) as gone:
        make(crew, recipients="people", people=[other.pk])

    assert "people" in no_bot.value.message_dict and "people" in gone.value.message_dict


def test_it_can_read_only_what_its_maker_may_read(crew):
    # Madina has no sales or finance rights: she can't have an agent read them for her.
    crew.company.features = [*crew.company.features, "finance"]
    crew.company.save(update_fields=["features"])

    with pytest.raises(ValidationError) as raised:
        make(crew, by=crew.lead, domains=["tasks", "finance"])

    assert "domains" in raised.value.message_dict
    options = {option["key"]: option for option in custom.domain_options(crew.company, crew.lead)}
    assert options["tasks"]["available"]
    assert options["finance"] == options["finance"] | {"available": False, "reason": "no_access"}
    assert "sales" not in options  # its module is off: not offered at all


def test_making_one_needs_the_rights_and_ai_on(crew):
    with pytest.raises(PermissionDenied):
        make(crew, by=crew.manager)
    row = services.disable_ai(crew.company, by=crew.owner)
    assert not row.enabled
    with pytest.raises(DomainError):
        make(crew)


# A run -------------------------------------------------------------------------------------------


def test_a_run_sends_one_message_to_each_person_in_their_language(
    crew, fake_claude, sent_messages, django_capture_on_commit_callbacks
):
    row = make(crew, recipients="people", people=[crew.owner.pk, crew.manager.pk])
    late_task(crew)
    fake_claude.script(
        tool_use("tasks_search", {"overdue": True}),
        fake_claude.text(f"**Kechki xulosa**\n\n{REPORT_UZ}"),
        fake_claude.json({"text": REPORT_RU}),
    )

    with django_capture_on_commit_callbacks(execute=True):
        done = run_due(row, at(3, 20))

    assert done == 2
    texts = {message["chat_id"]: message["text"] for message in sent_messages}
    assert texts == {
        crew.owner.user.telegram_id: f"<b>Kechki hisobot</b>\n\nKechki xulosa\n\n{REPORT_UZ}",
        crew.manager.user.telegram_id: f"<b>Kechki hisobot</b>\n\n{REPORT_RU}",
    }
    assert {message["bot"] for message in sent_messages} == {BotName.EMPLOYEE}
    sent = AgentEvent.objects.filter(agent=row.key, kind="sent").order_by("pk")
    assert [event.params["to"] for event in sent] == ["Dilnoza Karimova", "Bekzod Mirzayev"]
    # The run is logged with its three calls (two of the loop, one translation).
    [record] = AgentRun.objects.filter(key=row.key)
    assert (record.status, record.done, record.calls) == ("ok", 2, 3)
    assert record.output_tokens == 900
    assert AIUsage.objects.filter(feature=row.key).count() == 3


def test_its_requests_follow_the_rules(crew, fake_claude, sent_messages):
    row = make(crew)
    late_task(crew)
    fake_claude.script(tool_use("tasks_search", {"overdue": True}), fake_claude.text(REPORT_UZ))

    run_due(row, at(3, 20))

    first, second = fake_claude.requests
    assert first["model"] == "claude-haiku-5-5"
    assert first["output_config"] == {"effort": "low"}
    assert first["max_tokens"] == custom.MAX_OUTPUT_TOKENS
    assert "fallbacks" not in first and "temperature" not in first
    assert "tool_choice" not in first
    assert {tool["name"] for tool in first["tools"]} == {
        "tasks_search",
        "tasks_get",
        "tasks_readings",
    }
    system = system_text(first)
    assert system.startswith(custom.SYSTEM)
    assert system.index(custom.SYSTEM) < system.index(f"<company_instructions>\n{JOB}\n")
    assert "language=Uzbek (Latin script)" in first["messages"][0]["content"][0]["text"]
    assert "now=Tuesday 2026-11-03 20:00" in first["messages"][0]["content"][0]["text"]
    [result] = tool_results(second)
    assert result["total"] == 1
    assert "+998" not in json.dumps(second)  # never a phone number


def test_its_tools_are_the_owners_own(crew, fake_claude, sent_messages):
    # Madina reads tasks for Chilonzor only: a late task at Yunusobod is never read.
    row = make(crew, by=crew.lead)
    here = late_task(crew)
    late_task(crew, branch=crew.yunusobod, title="Javonlarni tartibga keltirish")
    fake_claude.script(
        tool_use("tasks_search", {"overdue": True}),
        tool_use("finance_summary", {"start": "2026-11-01", "end": "2026-11-03"}, "toolu_2"),
        fake_claude.text(REPORT_UZ),
    )

    run_due(row, at(3, 20))

    first, second, third = fake_claude.requests
    assert {tool["name"] for tool in first["tools"]} == {
        "tasks_search",
        "tasks_get",
        "tasks_readings",
    }
    [found] = tool_results(second)
    assert [task["id"] for task in found["rows"]] == [here.pk]
    # A tool outside its own is refused, whatever Claude asks for.
    assert tool_results(third)[-1] == {"error": "not_allowed"}


def test_a_tool_its_owner_lost_is_not_offered(crew, fake_claude, sent_messages):
    crew.company.features = [*crew.company.features, "finance"]
    crew.company.save(update_fields=["features"])
    row = make(crew, domains=["tasks", "finance"])
    # Dilnoza hands it to Madina, who may not read finance.
    CustomAgent.objects.filter(pk=row.pk).update(run_as=crew.lead)
    fake_claude.script(fake_claude.text(REPORT_UZ))

    run_due(row, at(3, 20))

    [request] = fake_claude.requests
    assert not [tool for tool in request["tools"] if tool["name"].startswith("finance_")]


def test_at_most_six_tool_calls_then_it_answers(crew, fake_claude, sent_messages):
    row = make(crew)
    calls = [
        tool_use("tasks_search", {"overdue": True}, f"toolu_{n}", output_tokens=60)
        for n in range(6)
    ]
    fake_claude.script(*calls, fake_claude.text(REPORT_UZ))

    run_due(row, at(3, 20))

    assert len(fake_claude.requests) == 7
    assert fake_claude.requests[-1]["tool_choice"] == {"type": "none"}
    assert all("tool_choice" not in request for request in fake_claude.requests[:-1])


def test_once_it_wrote_enough_it_answers_with_what_it_has(crew, fake_claude, sent_messages):
    row = make(crew)
    calls = [
        tool_use("tasks_search", {"overdue": True}, f"toolu_{n}", output_tokens=400)
        for n in range(3)
    ]
    fake_claude.script(*calls, fake_claude.text(REPORT_UZ))

    run_due(row, at(3, 20))

    assert len(fake_claude.requests) == 4  # three calls of 400 output tokens: the 4th answers
    assert fake_claude.requests[-1]["tool_choice"] == {"type": "none"}


def test_an_empty_answer_is_never_sent(crew, fake_claude, sent_messages):
    row = make(crew)
    fake_claude.script(fake_claude.text("  "))

    assert run_due(row, at(3, 20)) == 0

    assert sent_messages == []
    assert AgentRun.objects.get(key=row.key).status == "error"


def test_the_group_gets_it_in_the_companys_language(
    crew, fake_claude, monkeypatch, django_capture_on_commit_callbacks
):
    group = TelegramGroup.objects.create(company=crew.company, chat_id=-100500, title="Dorixona")
    posts = []
    monkeypatch.setattr(
        "apps.groups.tasks.queue_post", lambda group_id, message, *a: posts.append(message)
    )
    row = make(crew, recipients="group", group=group.pk)
    fake_claude.script(fake_claude.text(REPORT_UZ))

    with django_capture_on_commit_callbacks(execute=True):
        assert run_due(row, at(3, 20)) == 1

    assert posts == [(f"<b>Kechki hisobot</b>\n\n{REPORT_UZ}", None)]
    assert AgentEvent.objects.get(agent=row.key, kind="posted").params == {"group": "Dorixona"}


def test_the_owner_sees_the_report_it_wrote_others_dont(
    crew, fake_claude, sent_messages, owner_api
):
    row = make(crew)
    fake_claude.script(fake_claude.text(REPORT_UZ))
    run_due(row, at(3, 20))
    viewer = crew.manager

    mine = owner_api(crew.owner).get(
        f"/api/v1/owner/companies/{crew.company.pk}/ai/agents/{row.key}/"
    )
    theirs = owner_api(viewer).get(
        f"/api/v1/owner/companies/{crew.company.pk}/ai/agents/{row.key}/"
    )

    assert mine.data["custom"]["last_report"] == REPORT_UZ
    assert theirs.status_code == 200 and theirs.data["custom"]["last_report"] is None


# When it does not write -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"status": Membership.Status.LEFT}, "left"),
        ({"status": Membership.Status.SUSPENDED}, "no_access"),
        ({"role": "Manager"}, "no_access"),  # no ai.use
    ],
)
def test_it_pauses_itself_when_its_owner_cant_run_it(
    crew, fake_claude, sent_messages, change, reason
):
    row = make(crew, by=crew.lead)
    lead = crew.lead
    if "role" in change:
        lead.role = AccessRole.objects.get(company=crew.company, name=change["role"])
    else:
        lead.status = change["status"]
    lead.save()

    assert run_due(row, at(3, 20)) == 0

    state = AgentState.objects.get(company=crew.company, key=row.key)
    row.refresh_from_db()
    assert (state.enabled, state.next_run_at, row.paused_reason) == (False, None, reason)
    event = AgentEvent.objects.get(agent=row.key, kind=f"paused_{reason}")
    assert events.render(event, "en").startswith("Paused itself: Madina Saidova")
    assert fake_claude.requests == [] and sent_messages == []


def test_switched_back_on_it_reads_with_the_rights_of_who_did(crew, fake_claude, sent_messages):
    row = make(crew, by=crew.lead)
    crew.lead.status = Membership.Status.LEFT
    crew.lead.save(update_fields=["status"])
    run_due(row, at(3, 20))

    services.update_agent(crew.company, row.key, by=crew.owner, enabled=True)

    row.refresh_from_db()
    state = AgentState.objects.get(company=crew.company, key=row.key)
    assert (row.run_as, row.paused_reason, state.enabled) == (crew.owner, "", True)
    assert state.next_run_at == at(3, 20)


@pytest.mark.parametrize("state", ["budget", "no_claude"])
def test_without_claude_nothing_is_sent_and_it_says_why_once_a_day(
    crew, fake_claude, sent_messages, monkeypatch, state
):
    row = make(crew)
    if state == "budget":
        AIUsage.objects.create(
            company=crew.company,
            feature="chat",
            model="claude-sonnet-5-5",
            cost_micro_usd=21_000_000,
        )
        kind = "skipped_budget"
    else:  # Anthropic keeps failing: the circuit breaker is open
        monkeypatch.setattr("apps.ai.availability.breaker_open", lambda: True)
        kind = "skipped_ai"

    assert run_due(row, at(3, 20)) == 0
    assert run_due(row, at(3, 20, 30)) == 0

    assert fake_claude.requests == [] and sent_messages == []
    assert AgentEvent.objects.filter(agent=row.key, kind=kind).count() == 1
    assert AgentState.objects.get(key=row.key).enabled  # it waits; it doesn't pause


def test_a_run_hours_late_is_skipped(crew, fake_claude, sent_messages):
    row = make(crew)

    assert run_due(row, at(3, 23), due=at(3, 20)) == 0

    assert fake_claude.requests == []
    assert AgentEvent.objects.get(agent=row.key, kind="missed").params == {"time": "20:00"}


def test_a_workday_agent_rests_on_a_holiday(crew, fake_claude, sent_messages):
    from apps.timeoff.models import Holiday

    Holiday.objects.create(company=crew.company, date=at(3, 0).date(), name="Bayram")
    row = make(crew)

    assert run_due(row, at(3, 20)) == 0
    assert fake_claude.requests == []


def test_nobody_to_write_to_means_no_call(crew, fake_claude, sent_messages):
    row = make(crew)
    crew.owner.user.telegram_id = None
    crew.owner.user.save(update_fields=["telegram_id"])

    assert run_due(row, at(3, 20)) == 0

    assert fake_claude.requests == []
    assert AgentEvent.objects.filter(agent=row.key, kind="skipped_nobody").exists()


def test_deleted_it_never_runs_again(crew, fake_claude, sent_messages):
    row = make(crew)

    services.delete_custom_agent(row, by=crew.owner)

    state = AgentState.objects.get(company=crew.company, key=row.key)
    assert (state.enabled, state.next_run_at) == (False, None)
    assert agents.resolve(crew.company, row.key) is None
    assert runner.tick(at(3, 20, 5)) == 0
    assert runner.run_state(state.pk, at(3, 20, 5), forced=True) == 0
    assert fake_claude.requests == []
    assert row.key not in [item["key"] for item in queries.agent_rows(crew.company)]


def test_with_ai_fake_a_sample_report_reads_a_real_tool(
    crew, settings, sent_messages, django_capture_on_commit_callbacks
):
    settings.AI_FAKE = True
    english(crew.owner)
    row = make(crew)
    late_task(crew)

    with django_capture_on_commit_callbacks(execute=True):
        assert run_due(row, at(3, 20)) == 1

    [message] = sent_messages
    assert "1 task is late right now." in message["text"]


# Next to the built-in agents ---------------------------------------------------------------------


def test_it_is_listed_after_the_built_in_agents(crew):
    row = make(crew)

    rows = queries.agent_rows(crew.company)

    assert [item["key"] for item in rows][-1] == row.key
    assert all(item["custom"] is None for item in rows[:-1])
    assert rows[-1]["custom"]["job"] == JOB
    assert [agent.key for agent in agents.all_agents()] == [
        "voice_tasks",
        "deadline_watcher",
        "morning_plan",
        "photo_checker",
        "hr_assistant",
    ]


def test_its_page_shows_its_prompt_and_its_job(crew, owner_api):
    english(crew.owner)
    row = make(crew)

    page = owner_api(crew.owner).get(
        f"/api/v1/owner/companies/{crew.company.pk}/ai/agents/{row.key}/"
    )

    assert page.status_code == 200
    data = page.data
    assert (data["name"], data["schedule"], data["needs_claude"]) == (
        "Kechki hisobot",
        "Workdays at 20:00",
        True,
    )
    assert data["description"] == JOB
    assert JOB in data["prompts"][0]["text"]
    assert data["custom"]["run_as"] == {"id": crew.owner.pk, "name": "Dilnoza Karimova"}
    assert data["custom"]["domains"] == [{"key": "tasks", "label": "Tasks"}]
    assert data["upcoming"][0]["at"] == at(3, 20).isoformat()
    assert {"kind": "item", "at": at(3, 20).isoformat(), "label": "The report for 1 person"} in [
        dict(item) for item in data["upcoming"]
    ]


def test_its_events_carry_its_name_in_the_activity(crew, fake_claude, sent_messages, owner_api):
    row = make(crew)
    fake_claude.script(fake_claude.text(REPORT_UZ))
    run_due(row, at(3, 20))

    feed = owner_api(crew.owner).get(f"/api/v1/owner/companies/{crew.company.pk}/ai/activity/")

    [item] = [item for item in feed.data["results"] if item["agent"] == row.key]
    assert (item["agent_name"], item["icon"], item["kind"]) == ("Kechki hisobot", "bot", "sent")
    assert "Dilnoza Karimova" in item["text"]
    assert item["subject"] == {"type": "member", "id": crew.owner.pk, "label": "Dilnoza Karimova"}


def test_it_takes_no_instructions_its_job_says_it(crew):
    row = make(crew)

    with pytest.raises(DomainError):
        services.update_agent(crew.company, row.key, by=crew.owner, instructions="Qisqa yoz.")


# The owner endpoints -----------------------------------------------------------------------------


def url(crew, rest: str = "", company=None) -> str:
    return f"/api/v1/owner/companies/{(company or crew.company).pk}/ai/custom-agents/{rest}"


FORM = {
    "name": "Kechki hisobot",
    "job": JOB,
    "frequency": "weekdays",
    "at": "20:00",
    "recipients": "me",
    "domains": ["tasks"],
    "color": "indigo",
    "template": "evening_report",
}


def test_an_owner_makes_one_and_it_is_audited(crew, owner_api, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        made = owner_api(crew.owner).post(url(crew), FORM, format="json")

    assert made.status_code == 201
    assert made.data["key"].startswith("custom_") and made.data["enabled"]
    assert made.data["custom"]["color"] == "indigo"
    row = CustomAgent.objects.get()
    log = AuditLog.objects.get(action=AIAction.AGENT_CREATED)
    assert (log.actor, log.details["agent"]) == (crew.owner.user, row.key)


def test_changing_it_is_audited_with_what_changed(crew, owner_api):
    row = make(crew)

    changed = owner_api(crew.owner).patch(
        url(crew, f"{row.pk}/"), {"at": "21:00", "name": "Kech"}, format="json"
    )

    assert changed.status_code == 200 and changed.data["custom"]["at"] == "21:00"
    log = AuditLog.objects.get(action=AIAction.AGENT_CHANGED)
    assert log.details["changes"] == {"name": ["Kechki hisobot", "Kech"], "at": ["20:00", "21:00"]}
    assert AgentState.objects.get(key=row.key).next_run_at == at(3, 21)


def test_who_changes_what_it_reads_becomes_its_owner(crew, owner_api):
    row = make(crew, by=crew.lead)

    owner_api(crew.owner).patch(url(crew, f"{row.pk}/"), {"color": "rose"}, format="json")
    row.refresh_from_db()
    assert row.run_as == crew.lead  # a colour changes nothing it reads
    owner_api(crew.owner).patch(url(crew, f"{row.pk}/"), {"job": f"{JOB} Qisqa."}, format="json")
    row.refresh_from_db()
    assert row.run_as == crew.owner


def test_a_change_that_keeps_what_it_reads_is_not_checked_again(crew, owner_api):
    crew.company.features = [*crew.company.features, "finance"]
    crew.company.save(update_fields=["features"])
    row = make(crew, domains=["tasks", "finance"])
    crew.company.features = [name for name in crew.company.features if name != "finance"]
    crew.company.save(update_fields=["features"])
    api = owner_api(crew.owner)

    # The whole form back, a new name: finance is off now, but what it reads didn't change.
    kept = api.patch(
        url(crew, f"{row.pk}/"),
        {"name": "Kech", "domains": ["finance", "tasks"], "recipients": "me", "people": []},
        format="json",
    )
    assert kept.status_code == 200
    # Changing what it reads checks all of it again.
    refused = api.patch(
        url(crew, f"{row.pk}/"), {"domains": ["tasks", "finance", "reports"]}, format="json"
    )
    assert refused.status_code == 400 and "domains" in refused.data
    taken_away = api.patch(url(crew, f"{row.pk}/"), {"domains": ["tasks"]}, format="json")
    assert taken_away.status_code == 200
    row.refresh_from_db()
    assert (row.name, row.domains) == ("Kech", ["tasks"])


def test_deleting_it_is_a_soft_delete(crew, owner_api):
    row = make(crew)

    gone = owner_api(crew.owner).delete(url(crew, f"{row.pk}/"))

    assert gone.status_code == 204
    row.refresh_from_db()
    assert row.deleted_at is not None
    assert AuditLog.objects.filter(action=AIAction.AGENT_DELETED).exists()
    page = owner_api(crew.owner).get(
        f"/api/v1/owner/companies/{crew.company.pk}/ai/agents/{row.key}/"
    )
    assert page.status_code == 404


def test_validation_messages_name_the_field(crew, owner_api):
    refused = owner_api(crew.owner).post(
        url(crew), FORM | {"name": "", "domains": []}, format="json"
    )

    assert refused.status_code == 400
    assert set(refused.data) >= {"name", "domains"}


def test_the_eleventh_is_refused(crew, owner_api):
    for number in range(10):
        make(crew, name=f"Agent {number}")

    refused = owner_api(crew.owner).post(url(crew), FORM, format="json")

    assert refused.status_code == 400


def test_a_manager_without_ai_configure_sees_them_but_cant_change_them(crew, owner_api):
    row = make(crew)
    api = owner_api(crew.manager)

    assert api.get(url(crew)).status_code == 200
    assert [item["key"] for item in api.get(url(crew)).data] == [row.key]
    assert api.post(url(crew), FORM, format="json").status_code == 403
    assert api.patch(url(crew, f"{row.pk}/"), {"name": "X"}, format="json").status_code == 403
    assert api.delete(url(crew, f"{row.pk}/")).status_code == 403
    assert api.get(url(crew, "templates/")).status_code == 403
    assert api.get(url(crew, "options/")).status_code == 403
    run = api.post(f"/api/v1/owner/companies/{crew.company.pk}/ai/agents/{row.key}/run/")
    assert run.status_code == 403


def test_another_companys_agents_are_not_found(crew, owner_api, other_company, member, ai_on):
    ai_on(other_company)
    stranger = member.registered(other_company, "Owner")
    stranger.user.telegram_id = 9_300_001
    stranger.user.save(update_fields=["telegram_id"])
    theirs = services.create_custom_agent(other_company, by=stranger, data=FORM)
    api = owner_api(crew.owner)

    assert api.patch(url(crew, f"{theirs.pk}/"), {"name": "X"}, format="json").status_code == 404
    assert api.delete(url(crew, f"{theirs.pk}/")).status_code == 404
    base = f"/api/v1/owner/companies/{crew.company.pk}/ai/agents/{theirs.key}/"
    assert api.get(base).status_code == 404
    assert api.patch(base, {"enabled": False}, format="json").status_code == 404
    assert api.post(f"{base}run/").status_code == 404
    # Nor through their company's URL.
    assert api.get(url(crew, company=other_company)).status_code == 404


def test_templates_follow_the_modules(crew, owner_api):
    keys = [item["key"] for item in owner_api(crew.owner).get(url(crew, "templates/")).data]
    crew.company.features = [*crew.company.features, "attendance", "sales", "finance", "hr"]
    crew.company.save(update_fields=["features"])
    more = owner_api(crew.owner).get(url(crew, "templates/")).data

    assert "evening_report" in keys and "attendance_morning" not in keys
    assert {item["key"] for item in more} == {
        template.key for template in custom_templates.TEMPLATES
    }
    evening = next(item for item in more if item["key"] == "evening_report")
    assert (evening["frequency"], evening["at"]) == ("weekdays", "20:00")
    assert evening["domains"] == ["tasks", "reports", "attendance", "sales"]


def test_the_options_offer_what_may_be_chosen(crew, owner_api):
    TelegramGroup.objects.create(company=crew.company, chat_id=-100501, title="Filial")
    TelegramGroup.objects.create(
        company=crew.company, chat_id=-100502, title="Old", is_active=False
    )

    options = owner_api(crew.owner).get(url(crew, "options/")).data

    assert [group["title"] for group in options["groups"]] == ["Filial"]
    assert {person["name"] for person in options["people"]} >= {
        "Dilnoza Karimova",
        "Bekzod Mirzayev",
    }
    assert (options["max_agents"], options["live"], options["run_now_left"]) == (10, 0, 10)
    assert "phone" not in json.dumps(options)


def test_run_now_works_ten_times_a_day(
    crew, owner_api, fake_claude, sent_messages, django_capture_on_commit_callbacks
):
    row = make(crew)
    fake_claude.script(fake_claude.text(REPORT_UZ))
    run = f"/api/v1/owner/companies/{crew.company.pk}/ai/agents/{row.key}/run/"

    with django_capture_on_commit_callbacks(execute=True):
        started = owner_api(crew.owner).post(run)

    assert started.status_code == 202
    [message] = sent_messages
    assert message["chat_id"] == crew.owner.user.telegram_id
    assert AgentRun.objects.get(key=row.key).forced
    for _ in range(custom.RUN_NOW_PER_DAY - 1):
        AgentRun.objects.create(company=crew.company, key=row.key, started_at=NOW, forced=True)
    refused = owner_api(crew.owner).post(run)
    assert refused.status_code == 400


def test_switching_it_off_and_on_goes_through_the_agents_endpoint(crew, owner_api, fake_claude):
    row = make(crew)
    base = f"/api/v1/owner/companies/{crew.company.pk}/ai/agents/{row.key}/"

    off = owner_api(crew.owner).patch(base, {"enabled": False}, format="json")
    assert off.status_code == 200 and not off.data["enabled"]
    assert runner.tick(at(3, 20, 5)) == 0
    on = owner_api(crew.owner).patch(base, {"enabled": True}, format="json")
    assert on.data["enabled"] and on.data["next_run_at"] is not None


def test_the_evening_report_from_its_template_reaches_the_owner_at_eight_on_workdays(
    crew, fake_claude, sent_messages, owner_api, django_capture_on_commit_callbacks
):
    templates = owner_api(crew.owner).get(url(crew, "templates/")).data
    evening = next(item for item in templates if item["key"] == "evening_report")
    form = {
        key: evening[key]
        for key in ("job", "frequency", "at", "weekday", "month_day", "domains", "color")
    }
    made = owner_api(crew.owner).post(
        url(crew),
        form | {"name": "Kechki hisobot", "recipients": "me", "template": "evening_report"},
        format="json",
    )
    key = made.data["key"]
    state = AgentState.objects.get(company=crew.company, key=key)
    assert state.next_run_at == at(3, 20)
    late_task(crew)
    fake_claude.script(tool_use("tasks_search", {"overdue": True}), fake_claude.text(REPORT_UZ))

    assert runner.tick(at(3, 19, 55)) == 0  # not yet
    with django_capture_on_commit_callbacks(execute=True):
        assert runner.tick(at(3, 20, 0)) == 1

    [message] = sent_messages
    assert message["chat_id"] == crew.owner.user.telegram_id
    assert message["text"] == f"<b>Kechki hisobot</b>\n\n{REPORT_UZ}"
    context = fake_claude.requests[0]["messages"][0]["content"][0]["text"]
    assert "language=Uzbek (Latin script)" in context and "this run=on schedule" in context
    state.refresh_from_db()
    assert (state.next_run_at, state.last_status) == (at(4, 20), "ok")
    row = CustomAgent.objects.get(pk=int(key.removeprefix("custom_")))
    assert custom.next_run(row, at(6, 20), crew.company) == at(9, 20)  # Friday, then Monday


# The demo ---------------------------------------------------------------------------------------


def test_the_demo_has_two_agents_of_the_owners_own(
    company, demo_people, ai_on, freeze, fake_claude
):
    from apps.ai import demo

    freeze(NOW)
    company.timezone = "Asia/Tashkent"
    company.workdays = [0, 1, 2, 3, 4]
    company.save()
    ai_on(company)
    people = demo_people(company)

    evening, monday = demo.custom_agents(company, people, NOW)

    assert (evening.template, evening.recipients) == ("evening_report", "me")
    assert (monday.template, monday.recipients) == ("monday_best", "people")
    runs = AgentRun.objects.filter(key=evening.key).order_by("started_at")
    assert [run.started_at for run in runs] == [
        at(27, 20, month=10),
        at(28, 20, month=10),
        at(29, 20, month=10),
        at(30, 20, month=10),
        at(2, 20),  # the weekend is off
    ]
    assert [run.started_at for run in AgentRun.objects.filter(key=monday.key)] == [at(2, 9)]
    assert AgentEvent.objects.filter(agent=monday.key, kind="sent").count() == 2
    assert not AIUsage.objects.filter(feature__startswith="custom_", created_at__gte=NOW).exists()
    evening.refresh_from_db()
    assert evening.last_report and evening.last_report_at == runs.last().finished_at
