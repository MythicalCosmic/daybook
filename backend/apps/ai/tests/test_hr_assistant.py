"""The HR assistant (v0.4): the morning HR digest, payroll readiness before pay day and bonus
suggestions; its schedule, Claude's short texts, the branch scope, its events in three
languages, and how it comes on with AI and the HR module.

HR's pharmacy (apps/hr/tests/conftest.py): Chilonzor and Yunusobod; the owner Dilnoza and the
accountant Aziza hold hr.manage and payroll.manage everywhere, Lola holds hr.manage at Chilonzor
only, the manager Bekzod reads HR and gives warnings; Ali and Vali work at Chilonzor, Sara at
Yunusobod. The reference day is Wednesday 21 October 2026, Asia/Tashkent.
"""

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import translation

from apps.ai import agents, events, services
from apps.ai.agents import hr_assistant, runner
from apps.ai.agents.hr_assistant import KEY
from apps.ai.models import AgentEvent, AgentState
from apps.companies import services as companies
from apps.hr import services as hr
from apps.hr import watch
from apps.hr.tests.conftest import DAY, local
from apps.hr.tests.factories import EmployeeDocumentFactory
from apps.inbox.models import Notification
from apps.lifecycle import services as lifecycle
from apps.members.models import AccessRole
from apps.members.permissions import Perm
from apps.payroll import services as payroll
from apps.payroll.models import Adjustment, PayrollRun

pytestmark = pytest.mark.django_db

MORNING = local(DAY, 9)  # Wednesday 21 October 2026, 09:00


@pytest.fixture
def team(shop, staff, ai_on, freeze):
    """HR's pharmacy with AI on (the owner's consent leaves the HR assistant on), at 09:00."""
    ai_on(shop)
    services.enable_ai(shop, by=staff.owner)
    freeze(MORNING)
    return staff


def config(company, **changes) -> dict:
    state = agents.state_of(company, KEY)
    return agents.config_of(hr_assistant.AGENT, state) | changes


def digests(company, moment=MORNING) -> int:
    return hr_assistant.send_digests(company, config(company), moment)


def texts(sent_messages) -> dict[int, str]:
    return {message["chat_id"]: message["text"] for message in sent_messages}


def contract(person, *, by, **fields):
    made = hr.create_contract(person, by=by, starts_on=DAY - timedelta(days=200), **fields)
    return hr.activate_contract(made, by=by)


def born_today(person):
    profile = hr.ensure_profile(person)
    profile.birth_date = date(1996, DAY.month, DAY.day)
    profile.save()


@pytest.fixture
def due(team, shop):
    """This morning's HR work, every item already announced by the HR watch on earlier days:
    Ali's medical book expired three days ago, Vali's expires in 12 days and Sara's certificate
    in 20 (Yunusobod); Vali's fixed-term contract ends in 21 days and Ali's probation in 5; Ali
    owes an explanation for a written warning; it is Sara's birthday."""
    EmployeeDocumentFactory(
        membership=team.ali, expires_on=DAY - timedelta(days=3), expiry_notified=[30, 7, 0]
    )
    EmployeeDocumentFactory(
        membership=team.vali, expires_on=DAY + timedelta(days=12), expiry_notified=[30]
    )
    EmployeeDocumentFactory(
        membership=team.sara,
        kind="pharmacist_certificate",
        expires_on=DAY + timedelta(days=20),
        expiry_notified=[30],
    )
    ending = contract(team.vali, by=team.owner, kind="fixed_term", ends_on=DAY + timedelta(21))
    probation = contract(team.ali, by=team.owner, probation_until=DAY + timedelta(days=5))
    type(ending).objects.filter(pk=ending.pk).update(end_notified=[30])
    type(probation).objects.filter(pk=probation.pk).update(probation_notified=[7])
    lifecycle.issue(
        team.ali,
        by=team.manager,
        kind="written_warning",
        category="storage_breach",
        description="Muzlatgich eshigi ochiq qoldi, harorat +9 °C",
    )
    born_today(team.sara)
    return team


# Registration, schedule ------------------------------------------------------------------------


def test_the_hr_assistant_is_an_agent_with_its_settings():
    agent = agents.get(KEY)

    assert [item.key for item in agents.all_agents()][-1] == KEY
    assert (agent.icon, agent.feature, agent.needs_claude, agent.default_enabled) == (
        "briefcase",
        "hr",
        False,
        True,
    )
    assert agent.defaults() == {
        "at": "09:00",
        "days_before_pay_day": 3,
        "change_alert_percent": 30,
        "suggest_bonuses": False,
        "top_n": 3,
        "bonus_amount": 300000,
    }
    assert agent.schedule(agent.defaults()) == "Workdays at 09:00"
    assert set(agent.events) == {
        "digest_sent",
        "payroll_ready",
        "payroll_blocked",
        "bonuses_suggested",
    }


def test_it_runs_on_workdays_at_its_time(shop):
    shop.workdays = [0, 1, 2, 3, 4]  # Monday to Friday
    friday = local(date(2026, 10, 23), 10)

    assert hr_assistant.AGENT.next_run({"at": "09:00"}, friday, shop) == local(
        date(2026, 10, 26), 9
    )
    assert hr_assistant.AGENT.next_run({"at": "09:00"}, local(DAY, 8), shop) == MORNING


def test_ai_on_switches_it_on_only_where_the_company_has_hr(shop, staff, member):
    from apps.companies.tests.factories import CompanyFactory

    services.enable_ai(shop, by=staff.owner)
    other = CompanyFactory()
    services.enable_ai(other, by=member.registered(other, "Owner"))

    assert agents.state_of(shop, KEY).enabled
    assert not AgentState.objects.filter(company=other, key=KEY).exists()


def test_the_card_shows_only_with_the_hr_module(owner_api, team, shop):
    url = f"/api/v1/owner/companies/{shop.pk}/ai/agents/"

    rows = owner_api(team.owner).get(url).json()
    card = next(row for row in rows if row["key"] == KEY)
    assert (card["enabled"], card["icon"], card["schedule"]) == (
        True,
        "briefcase",
        "Workdays at 09:00",
    )
    assert card["next_run_at"] is not None

    companies.set_features(shop, by=team.owner, features=["payroll", "attendance", "ai"])
    assert KEY not in [row["key"] for row in owner_api(team.owner).get(url).json()]


def test_switching_hr_on_brings_the_assistant_where_ai_is_on(shop, staff, ai_on):
    shop.features = ["payroll", "attendance"]
    shop.save(update_fields=["features"])
    ai_on(shop)

    companies.set_features(shop, by=staff.owner, features=[*shop.features, "hr"])

    state = AgentState.objects.get(company=shop, key=KEY)
    assert state.enabled and state.next_run_at is not None


def test_a_new_agent_comes_on_after_a_deploy_but_a_switched_off_one_stays_off(team, shop):
    from apps.ai import defaults

    AgentState.objects.filter(company=shop, key=KEY).delete()
    defaults.ensure(shop)
    assert AgentState.objects.get(company=shop, key=KEY).enabled  # never set up: on

    AgentState.objects.filter(company=shop, key=KEY).update(enabled=False)
    defaults.ensure(shop)
    assert not AgentState.objects.get(company=shop, key=KEY).enabled  # the owner's choice stays


# The morning HR digest -------------------------------------------------------------------------


def test_each_hr_manager_hears_what_needs_them(
    due, shop, sent_messages, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        assert digests(shop) == 3  # the owner, the accountant and Lola

    owner = texts(sent_messages)[due.owner.user.telegram_id]
    assert owner == "\n".join(
        [
            "<b>HR today</b>",
            "",
            "Documents: 3",
            "    · Ali Valiyev — Medical book (expired: 18.10.2026)",
            "    · Vali Aliyev — Medical book (expires: 02.11.2026)",
            "    · Sara Tosheva — Specialist certificate (expires: 10.11.2026)",
            "",
            "Contracts ending: 1",
            "    · Vali Aliyev (ends: 11.11.2026)",
            "",
            "Probation ending: 1",
            "    · Ali Valiyev (ends: 26.10.2026)",
            "",
            "Waiting for an explanation: 1",
            "    · Ali Valiyev — Written warning, 21.10.2026",
            "",
            "Birthday today: Sara Tosheva",
        ]
    )
    lola = texts(sent_messages)[due.lead.user.telegram_id]
    assert "Sara" not in lola  # Yunusobod isn't hers
    assert "Documents: 2" in lola and "Waiting for an explanation: 1" in lola
    assert due.manager.user.telegram_id not in texts(sent_messages)  # reads HR, doesn't run it
    event = AgentEvent.objects.get(agent=KEY, subject_id=due.owner.pk)
    assert (event.kind, event.params) == ("digest_sent", {"to": "Dilnoza Karimova", "count": 7})


def test_the_digest_opens_hr_in_the_dashboard(
    due, shop, settings, sent_messages, django_capture_on_commit_callbacks
):
    settings.DASHBOARD_URL = "https://app.example.uz"
    settings.OWNER_BOT_TOKEN = "123:owner"
    due.owner.user.owner_bot_started_at = MORNING
    due.owner.user.save(update_fields=["owner_bot_started_at"])

    with django_capture_on_commit_callbacks(execute=True):
        digests(shop)

    by_chat = {message["chat_id"]: message for message in sent_messages}
    owner = by_chat[due.owner.user.telegram_id]
    assert owner["bot"] == "owner"  # where HR's own notices reach the owner
    assert by_chat[due.lead.user.telegram_id]["bot"] == "employee"
    [[button]] = owner["reply_markup"]["inline_keyboard"]
    assert button["web_app"]["url"] == f"https://app.example.uz/c/{shop.pk}/hr"


def test_nobody_hears_it_twice_a_day(due, shop, sent_messages, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        digests(shop)
        assert digests(shop, local(DAY, 15)) == 0

    assert len(sent_messages) == 3
    with django_capture_on_commit_callbacks(execute=True):
        assert digests(shop, local(DAY + timedelta(days=1), 9)) == 3  # the next morning


def test_a_quiet_day_sends_nothing(team, shop, sent_messages):
    EmployeeDocumentFactory(membership=team.ali, expires_on=DAY + timedelta(days=90))

    assert digests(shop) == 0
    assert sent_messages == [] and not AgentEvent.objects.filter(agent=KEY).exists()


def test_the_digest_names_nothing_the_watch_announces_today(
    team, shop, freeze, sent_messages, django_capture_on_commit_callbacks
):
    """The watch tells HR about Vali's medical book this morning (its 30-day step): the digest
    counts it with the rest and doesn't name it again, whether the watch ran before it or
    still has to."""
    EmployeeDocumentFactory(
        membership=team.ali, expires_on=DAY - timedelta(days=3), expiry_notified=[30, 7, 0]
    )
    EmployeeDocumentFactory(membership=team.vali, expires_on=DAY + timedelta(days=20))

    with django_capture_on_commit_callbacks(execute=True):
        digests(shop)  # 09:00: the watch's step is still to come
    before = texts(sent_messages)[team.owner.user.telegram_id]
    assert "Documents: 2" in before and "In today's separate notices: 1" in before
    assert "Ali Valiyev" in before and "Vali Aliyev" not in before

    # A week before its day the watch speaks first (its 7-day step), then the digest.
    sent_messages.clear()
    week_before = DAY + timedelta(days=13)
    watch.watch_company(shop, freeze(local(week_before, 9, 7)))
    assert Notification.objects.filter(recipient=team.owner, kind="hr.document_expiring").exists()
    with django_capture_on_commit_callbacks(execute=True):
        digests(shop, local(week_before, 9, 30))
    owner = texts(sent_messages)[team.owner.user.telegram_id]
    assert "In today's separate notices: 1" in owner and "Vali Aliyev" not in owner


def test_a_digest_with_only_what_the_watch_says_today_is_not_sent(team, shop, sent_messages):
    EmployeeDocumentFactory(membership=team.vali, expires_on=DAY + timedelta(days=20))
    watch.watch_company(shop, MORNING)

    assert digests(shop, local(DAY, 9, 30)) == 0


def test_nobody_hears_about_themselves(
    team, shop, sent_messages, django_capture_on_commit_callbacks
):
    EmployeeDocumentFactory(
        membership=team.accountant, expires_on=DAY + timedelta(days=12), expiry_notified=[30]
    )
    born_today(team.accountant)

    with django_capture_on_commit_callbacks(execute=True):
        digests(shop)

    assert team.accountant.user.telegram_id not in texts(sent_messages)
    owner = texts(sent_messages)[team.owner.user.telegram_id]
    assert "Aziza Rasulova" in owner and "Birthday today: Aziza Rasulova" in owner


def test_explanations_only_for_those_who_may_read_the_records(
    due, shop, member, chilonzor, sent_messages, django_capture_on_commit_callbacks
):
    AccessRole.objects.create(company=shop, name="Documents", permissions=[Perm.HR_MANAGE])
    clerk = member.registered(shop, "Documents", first_name="Nodira", last_name="Usmonova")
    clerk.branches.add(chilonzor)

    with django_capture_on_commit_callbacks(execute=True):
        digests(shop)

    text = texts(sent_messages)[clerk.user.telegram_id]
    assert "Documents: 2" in text and "explanation" not in text


def test_the_digest_in_uzbek_and_russian(
    due, shop, sent_messages, django_capture_on_commit_callbacks
):
    for person, language in ((due.owner, "uz"), (due.accountant, "ru")):
        person.user.language = language
        person.user.save(update_fields=["language"])

    with django_capture_on_commit_callbacks(execute=True):
        digests(shop)

    uz = texts(sent_messages)[due.owner.user.telegram_id]
    ru = texts(sent_messages)[due.accountant.user.telegram_id]
    for text in (uz, ru):
        assert "Documents" not in text and "Probation" not in text and "Birthday" not in text
        assert "18.10.2026" in text and "Sara Tosheva" in text
    assert "Hujjatlar: 3" in uz and "Bugun tug‘ilgan kun: Sara Tosheva" in uz
    assert "Документы: 3" in ru


def test_days_off_and_holidays_are_quiet(due, shop, sent_messages):
    from apps.timeoff.models import Holiday

    state = agents.state_of(shop, KEY)
    assert hr_assistant.run(shop, state, local(date(2026, 10, 25), 9)) == 0  # a Sunday
    Holiday.objects.create(company=shop, date=DAY, name="Kun")
    assert hr_assistant.run(shop, state, MORNING) == 0


def test_the_tick_runs_it_and_it_moves_on(
    due, shop, sent_messages, django_capture_on_commit_callbacks
):
    AgentState.objects.filter(company=shop).update(next_run_at=None)

    with django_capture_on_commit_callbacks(execute=True):
        runner.tick(MORNING)

    state = AgentState.objects.get(company=shop, key=KEY)
    assert state.last_status == "ok" and state.next_run_at == local(DAY + timedelta(days=1), 9)
    assert len([m for m in sent_messages if m["text"].startswith("<b>HR today")]) == 3


def test_a_failing_part_never_stops_the_others(due, shop, monkeypatch, sent_messages):
    def broken(*args):
        raise RuntimeError("payroll is down")

    monkeypatch.setattr(hr_assistant, "check_payroll", broken)

    assert hr_assistant.run(shop, agents.state_of(shop, KEY), MORNING) == 3


# With Claude -----------------------------------------------------------------------------------


def opening(fake_claude, text):
    return fake_claude.json({"text": text})


def test_with_claude_the_digest_opens_with_two_sentences(
    due, shop, fake_claude, sent_messages, django_capture_on_commit_callbacks
):
    line = "Ali Valiyevning tibbiy daftarchasi 3 kun oldin tugagan. Sinov muddati 5 kunda tugaydi."
    fake_claude.script(*(opening(fake_claude, line) for _ in range(3)))

    with django_capture_on_commit_callbacks(execute=True):
        digests(shop)

    owner = texts(sent_messages)[due.owner.user.telegram_id]
    assert owner.startswith(f"<b>HR today</b>\n\n{line}\n\nDocuments: 3")
    request = fake_claude.requests[0]
    assert request["model"] == "claude-haiku-5-5"
    assert request["output_config"]["effort"] == "low"
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert "fallbacks" not in request  # Haiku has none
    assert not {"temperature", "top_p", "top_k"} & set(request)
    body = json.dumps(request, ensure_ascii=False)
    assert "Ali Valiyev" in body and "Medical book" in body  # names and kinds: what she may see
    for person in (due.ali, due.vali, due.sara, due.owner):
        assert str(person.user.telegram_id) not in body
    assert "998901234567" not in body and "+9 °C" not in body  # no phones, no record texts
    assert "<facts>" in request["messages"][0]["content"][0]["text"]


def test_a_number_claude_made_up_keeps_the_template(
    due, shop, fake_claude, sent_messages, django_capture_on_commit_callbacks
):
    fake_claude.script(*(opening(fake_claude, "9 ta hujjat muddati tugagan.") for _ in range(3)))

    with django_capture_on_commit_callbacks(execute=True):
        digests(shop)

    assert texts(sent_messages)[due.owner.user.telegram_id].startswith(
        "<b>HR today</b>\n\nDocuments: 3"
    )


def test_when_claude_fails_the_digest_still_goes(
    due, shop, fake_claude, sent_messages, django_capture_on_commit_callbacks
):
    fake_claude.script(*(fake_claude.status_error(529) for _ in range(3)))

    with django_capture_on_commit_callbacks(execute=True):
        assert digests(shop) == 3

    assert all(m["text"].startswith("<b>HR today</b>\n\nDocuments") for m in sent_messages)


def test_without_budget_claude_isnt_asked(due, shop, fake_claude, sent_messages):
    from apps.ai import conf

    row = conf.get_settings(shop)
    row.monthly_budget_usd = Decimal("0")
    row.save()

    assert digests(shop) == 3
    assert fake_claude.requests == []


# Payroll readiness -----------------------------------------------------------------------------

OCTOBER = date(2026, 10, 1)
CHECK_DAY = local(date(2026, 11, 2), 9)  # Monday, three days before pay day (the 5th)


@pytest.fixture
def pay(team, shop, freeze, monkeypatch):
    """Everyone is paid 5 200 000 so‘m a month (and has worked here since June 2025), except
    the owner and Vali, who have no pay setup; the clock at 09:00 on Monday 2 November 2026.
    The owner and the accountant hold payroll.manage."""
    monkeypatch.setattr(
        "apps.hr.queries.employment_dates",
        lambda company, member_ids: {pk: (date(2025, 6, 1), None) for pk in member_ids},
    )
    for person in (team.manager, team.accountant, team.lead, team.ali, team.sara):
        payroll.set_pay(person, by=None, effective_from=date(2026, 1, 1), amount="5200000")
    freeze(CHECK_DAY)
    return team


def check(company, moment=CHECK_DAY, **changes) -> int:
    return hr_assistant.check_payroll(company, config(company, **changes), moment)


@pytest.fixture
def blocked(pay, shop, freeze):
    """September's draft paid everyone in full; in October Ali got a 2 600 000 bonus (+50%),
    Lola disputes a fine and Sara's fine waits for a decision."""
    freeze(local(date(2026, 10, 5), 10))
    payroll.create_run(shop, by=None, period=date(2026, 9, 1))
    payroll.propose(
        pay.ali,
        by=pay.owner,
        kind="bonus",
        amount="2600000",
        reason="Inventarizatsiya",
        period=OCTOBER,
        approve=True,
    )
    fine = payroll.propose(
        pay.lead, by=pay.owner, kind="fine", amount="100000", reason="Kechikish", approve=True
    )
    payroll.dispute(fine, by=pay.lead, text="Men kechikmadim")
    payroll.propose(pay.sara, by=pay.manager, kind="fine", amount="50000", reason="Kechikish")
    freeze(CHECK_DAY)
    return pay


def test_before_pay_day_the_draft_is_made_and_checked(
    pay, shop, sent_messages, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        assert check(shop) == 2  # the owner and the accountant

    run = PayrollRun.objects.get(company=shop)
    assert (run.period, run.status, run.finalized_at) == (OCTOBER, "draft", None)
    assert run.payslips.count() == 5 and run.calculated_at is not None
    assert not run.payslips.exclude(status="draft").exists()  # never published, never paid
    owner = texts(sent_messages)[pay.owner.user.telegram_id]
    assert owner == "\n".join(
        [
            "<b>Payroll: October 2026</b>",
            "",
            "The draft is calculated: 5 payslips.",
            "Pay day: 05.11.2026",
            "",
            "<b>Settle before pay day:</b>",
            "    · No pay setup: Vali Aliyev",
        ]
    )
    accountant = texts(sent_messages)[pay.accountant.user.telegram_id]
    assert "The draft is calculated: 4 payslips." in accountant  # hers isn't hers to check
    event = AgentEvent.objects.get(agent=KEY)
    assert (event.kind, event.params) == ("payroll_blocked", {"month": "10.2026", "count": 1})


def test_it_names_what_holds_the_payroll_up(
    blocked, shop, sent_messages, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        check(shop)

    owner = texts(sent_messages)[blocked.owner.user.telegram_id]
    assert owner.endswith(
        "\n".join(
            [
                "<b>Settle before pay day:</b>",
                "    · No pay setup: Vali Aliyev",
                "    · 1 disputed fine has no answer yet.",
                "    · 1 bonus or fine still waits for a decision.",
                "    · Big change against last month: Ali Valiyev +50%",
            ]
        )
    )
    for amount in ("2 600 000", "2600000", "7 800 000", "5 200 000"):
        assert amount not in owner
    assert AgentEvent.objects.get(agent=KEY).params == {"month": "10.2026", "count": 4}


def test_each_payroll_manager_hears_about_their_branches(
    blocked, shop, member, yunusobod, sent_messages, django_capture_on_commit_callbacks
):
    AccessRole.objects.create(
        company=shop, name="Branch payroll", permissions=[Perm.PAYROLL_MANAGE]
    )
    clerk = member.registered(shop, "Branch payroll", first_name="Malika", last_name="Ergasheva")
    clerk.branches.add(yunusobod)

    with django_capture_on_commit_callbacks(execute=True):
        assert check(shop) == 3

    text = texts(sent_messages)[clerk.user.telegram_id]
    assert "1 bonus or fine still waits for a decision." in text  # Sara's
    for other in ("Vali", "Ali Valiyev", "disputed", "Big change"):
        assert other not in text


def test_nothing_in_the_way_says_so(pay, shop, sent_messages, django_capture_on_commit_callbacks):
    payroll.set_pay(pay.vali, by=None, effective_from=date(2026, 1, 1), amount="5200000")

    with django_capture_on_commit_callbacks(execute=True):
        check(shop)

    owner = texts(sent_messages)[pay.owner.user.telegram_id]
    assert owner.endswith("Pay day: 05.11.2026\n\nNothing holds it up: check it and finalize it.")
    assert AgentEvent.objects.get(agent=KEY).kind == "payroll_ready"


def test_once_a_month_and_only_before_pay_day(pay, shop, sent_messages):
    assert check(shop, local(date(2026, 10, 30), 9)) == 0  # October's pay day is long gone
    assert check(shop, local(date(2026, 11, 1), 9), days_before_pay_day=3) == 0  # the 2nd
    assert check(shop, local(date(2026, 11, 5), 9)) == 0  # pay day itself: payroll's own reminder
    assert not PayrollRun.objects.exists()

    assert check(shop) == 2
    assert check(shop, local(date(2026, 11, 3), 9)) == 0
    assert check(shop, local(date(2026, 11, 1), 9), days_before_pay_day=4) == 0  # done for October
    assert PayrollRun.objects.count() == 1


def test_a_draft_is_calculated_again_and_a_finalized_or_cancelled_month_left_alone(
    pay, shop, freeze, sent_messages
):
    freeze(local(date(2026, 11, 1), 7))
    run = payroll.create_run(shop, by=None, period=OCTOBER)
    stamp = run.calculated_at
    freeze(CHECK_DAY)

    assert check(shop) == 2
    run.refresh_from_db()
    assert run.calculated_at > stamp and run.status == "draft"

    AgentEvent.objects.all().delete()
    PayrollRun.objects.filter(pk=run.pk).update(status="finalized")
    assert check(shop) == 0
    PayrollRun.objects.filter(pk=run.pk).update(status="cancelled")
    assert check(shop) == 0
    assert PayrollRun.objects.count() == 1  # cancelled by hand: no new one


def test_a_company_not_using_payroll_gets_no_run(team, shop, freeze):
    freeze(CHECK_DAY)

    assert check(shop) == 0
    assert not PayrollRun.objects.exists()


def test_with_claude_the_payroll_note_opens_with_a_summary_and_no_money(
    blocked, shop, fake_claude, sent_messages, django_capture_on_commit_callbacks
):
    line = "Vali Aliyevda ish haqi sozlamasi yo‘q, Ali Valiyevning puli 50% oshgan."
    fake_claude.script(*(opening(fake_claude, line) for _ in range(2)))

    with django_capture_on_commit_callbacks(execute=True):
        check(shop)

    assert (
        f"<b>Payroll: October 2026</b>\n\n{line}\n\n"
        in texts(sent_messages)[blocked.owner.user.telegram_id]
    )
    request = fake_claude.requests[0]
    facts = request["messages"][0]["content"][0]["text"]
    assert '"change_percent": 50' in facts and "Vali Aliyev" in facts
    body = json.dumps(request, ensure_ascii=False)
    for amount in ("5200000", "2600000", "7800000", "100000", "50000"):
        assert amount not in body
    assert request["output_config"]["effort"] == "low"


# Bonus suggestions -----------------------------------------------------------------------------

LAST_WORKDAY = local(date(2026, 10, 31), 9)  # a Saturday, a workday at this pharmacy


def work(person, *, by, on_time: int, late: int = 0):
    """`on_time` tasks finished before their deadline and `late` ones after it, in October."""
    from apps.tasks.models import Task
    from apps.tasks.tests.factories import TaskFactory

    for index in range(on_time + late):
        due = local(date(2026, 10, 1 + index), 18)
        finished = due + (timedelta(hours=-2) if index < on_time else timedelta(hours=2))
        TaskFactory(
            assignee=person,
            created_by=by,
            due_at=due,
            status=Task.Status.DONE,
            completed_at=finished,
        )


@pytest.fixture
def month(pay, shop, freeze):
    """October's work: Ali 12 tasks all on time, Sara 11 of 12, Lola 9 of 12, the accountant 5
    (below the rules' minimum of 10); bonuses switched on, two people a month."""
    work(pay.ali, by=pay.manager, on_time=12)
    work(pay.sara, by=pay.manager, on_time=11, late=1)
    work(pay.lead, by=pay.manager, on_time=9, late=3)
    work(pay.accountant, by=pay.manager, on_time=5)
    freeze(LAST_WORKDAY)
    return pay


def suggest(company, moment=LAST_WORKDAY, **changes) -> int:
    changes = {"suggest_bonuses": True, "top_n": 2, **changes}
    return hr_assistant.suggest_bonuses(company, config(company, **changes), moment)


def bonuses():
    return Adjustment.objects.filter(rule_key__startswith="ai:bonus:").order_by("pk")


def test_the_best_on_time_people_get_a_proposed_bonus(
    month, shop, sent_messages, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        assert suggest(shop) == 2

    ali, sara = bonuses()
    assert (ali.membership, sara.membership) == (month.ali, month.sara)
    assert {row.status for row in (ali, sara)} == {"proposed"}  # a person decides
    assert (ali.kind, ali.amount, ali.source, ali.period) == (
        "bonus",
        Decimal("300000"),
        "rule",
        OCTOBER,
    )
    assert ali.rule_key == f"ai:bonus:m{month.ali.pk}:2026-10" and ali.rule is None
    assert ali.reason == "October 2026: 100% of 12 tasks done on time, no lateness fine."
    assert sara.reason == "October 2026: 92% of 12 tasks done on time, no lateness fine."
    deciders = Notification.objects.filter(kind="payroll.adjustment", target_id=ali.pk)
    assert {row.recipient for row in deciders} == {month.owner, month.accountant}
    event = AgentEvent.objects.get(agent=KEY)
    assert (event.kind, event.params) == ("bonuses_suggested", {"count": 2, "month": "10.2026"})


def test_running_again_never_doubles_a_bonus(month, shop):
    assert suggest(shop) == 2
    assert suggest(shop) == 0
    AgentEvent.objects.all().delete()
    assert suggest(shop) == 1  # the next best (Lola), never Ali or Sara again
    assert bonuses().count() == 3
    assert bonuses().filter(membership=month.ali).count() == 1


def test_a_lateness_fine_keeps_a_bonus_away(month, shop):
    late_rule = payroll.save_rule(
        shop,
        by=None,
        name="Kechikish",
        kind="fine",
        metric="attendance.late_arrivals",
        mode="per_unit",
        amount="20000",
    )
    payroll.propose(
        month.ali, by=None, kind="fine", amount="20000", reason="Kechikish", period=OCTOBER
    )
    Adjustment.objects.filter(membership=month.ali).update(rule=late_rule)
    record = lifecycle.issue(
        month.sara,
        by=month.manager,
        kind="verbal_warning",
        category="lateness",
        description="Uch marta kechikdi",
        fine_amount=Decimal("50000"),
    )
    assert record.fine_id

    assert suggest(shop, top_n=3) == 1
    assert [row.membership for row in bonuses()] == [month.lead]  # 75%, the only one left


def test_bonuses_wait_for_the_last_workday_and_need_switching_on(month, shop):
    state = agents.state_of(shop, KEY)

    assert suggest(shop, local(date(2026, 10, 30), 9)) == 0  # Friday: not the last workday
    assert hr_assistant.run(shop, state, LAST_WORKDAY) == 0  # off by default
    assert not bonuses().exists()
    state.config = {**state.config, "suggest_bonuses": True}
    state.save()
    assert hr_assistant.run(shop, state, LAST_WORKDAY) == 3  # Ali, Sara and Lola


def test_the_last_workday_skips_days_off_and_holidays(shop):
    from apps.timeoff.models import Holiday

    shop.workdays = [0, 1, 2, 3, 4]
    assert hr_assistant.last_workday(shop, date(2026, 10, 12)) == date(2026, 10, 30)
    Holiday.objects.create(company=shop, date=date(2026, 10, 30), name="Kun")
    assert hr_assistant.last_workday(shop, date(2026, 10, 12)) == date(2026, 10, 29)


def test_a_finalized_month_gets_no_suggestions(month, shop):
    run = payroll.create_run(shop, by=None, period=OCTOBER)
    PayrollRun.objects.filter(pk=run.pk).update(status="finalized")

    assert suggest(shop) == 0 and not bonuses().exists()


def test_with_claude_the_reasons_come_in_one_call_in_each_persons_language(
    month, shop, fake_claude
):
    month.ali.user.language = "uz"
    month.ali.user.save(update_fields=["language"])
    month.sara.user.language = "ru"
    month.sara.user.save(update_fields=["language"])
    fake_claude.script(
        fake_claude.json(
            {
                "reasons": [
                    {
                        "number": 1,
                        "reason": "Oktabrda 12 ta vazifaning 100 foizini o‘z vaqtida bajardingiz.",
                    },
                    {"number": 2, "reason": "В октябре 99 задач вовремя."},  # not her numbers
                ]
            }
        )
    )

    assert suggest(shop) == 2

    ali, sara = bonuses()
    assert ali.reason == "Oktabrda 12 ta vazifaning 100 foizini o‘z vaqtida bajardingiz."
    assert sara.reason.startswith("Октябрь 2026: вовремя выполнено 92% из 12 задач")
    [request] = fake_claude.requests
    assert request["model"] == "claude-haiku-5-5" and "fallbacks" not in request
    assert request["output_config"]["effort"] == "low"
    people = request["messages"][0]["content"][0]["text"]
    assert '"language": "uz"' in people and '"language": "ru"' in people
    assert '"on_time_percent": 100' in people and '"tasks": 12' in people
    for private in ("Ali Valiyev", "Sara Tosheva", "300000", "5200000", '"id"', "member"):
        assert private not in json.dumps(request, ensure_ascii=False)


# Events ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "params", "english"),
    [
        (
            "digest_sent",
            {"to": "Dilnoza Karimova", "count": 7},
            "HR digest for Dilnoza Karimova: 7 items",
        ),
        (
            "payroll_ready",
            {"month": "10.2026", "count": 0},
            "Payroll 10.2026 is calculated: nothing holds it up",
        ),
        (
            "payroll_blocked",
            {"month": "10.2026", "count": 4},
            "Payroll 10.2026 is calculated: 4 things to settle before pay day",
        ),
        (
            "bonuses_suggested",
            {"month": "10.2026", "count": 1},
            "Suggested 1 bonus for 10.2026: it waits for approval",
        ),
    ],
)
def test_the_events_read_in_three_languages(company, kind, params, english):
    event = events.log(company, KEY, kind, params=params)

    assert events.render(event, "en") == english
    for language in ("uz", "ru"):
        text = events.render(event, language)
        assert text != english and str(params["count"] or params["month"]) in text
        for value in params.values():
            if isinstance(value, str):
                assert value in text


def test_the_agent_speaks_uzbek_and_russian():
    agent = agents.get(KEY)

    def words() -> list[str]:
        found = [str(agent.description)]
        for item in agent.fields:
            found += [str(item.label), str(item.help)]
            if item.unit and item.unit != "%":
                found.append(str(item.unit))
        return [text for text in found if text]

    with translation.override("en"):
        english = words()
    for language, name in (("uz", "HR yordamchisi"), ("ru", "HR-помощник")):
        with translation.override(language):
            assert str(agent.name) == name
            assert agent.schedule(agent.defaults()) != "Workdays at 09:00"
            translated = words()
        assert len(translated) == len(english)
        assert all(ours != theirs for ours, theirs in zip(translated, english, strict=True))
