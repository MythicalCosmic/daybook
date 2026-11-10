"""Maslahatchi ("Советник", the advisor): the owner's business advisor.

Every week (BriefingSettings: Monday 08:00 in the company's time by default) it writes the
weekly business review, and on the first of the month the monthly one (apps.briefings): what
went well, what went wrong, and three concrete suggestions, each tied to a number of the facts
and opening the page that shows it. The facts come first and alone hold the numbers
(apps.briefings.facts); Claude (`AI_MODEL_FAST`, Haiku by default, effort low) only words them,
and its draft is checked against them (apps.briefings.writing.checked): a point or a suggestion
that cites no signal of the facts, or says a number that isn't one of them, is dropped and the
template fills the gap. Without Claude (no key, the budget spent, a refusal) the template writes
it all. Where AI is off, or Maslahatchi is, the reviews still go out from the templates (the
briefings beat): they are the company's, not the agent's.

"Maslahatchidan so‘rang" (Ask the advisor) is an Ask AI conversation with `agent` "advisor"
(apps.ai.chat): `CHAT_SYSTEM` after Ask AI's rules, the read-only finance, sales, stock, people,
attendance, payroll and HR tools the asker may use, plus `briefings_advisor_facts` (the latest
weekly facts) and `briefings_advisor_scenario` (what if a monthly cost or income changes from a
date: the forecast's new low point and how long the money lasts), on `AI_MODEL_FAST` at low
effort. It changes nothing.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext, ngettext_lazy
from pydantic import BaseModel
from pydantic import Field as PydanticField

from apps.ai import availability, client, events, instructions
from apps.ai.agents import registry
from apps.ai.agents.registry import Agent, EventTemplate, Prompt
from apps.ai.tools.scrub import scrub_data
from apps.companies.models import Feature

logger = logging.getLogger(__name__)

KEY = "advisor"
CHAT_FEATURE = "advisor_chat"
# Enough for adaptive thinking and the answer (the Claude API notes: don't lowball a review).
MAX_TOKENS = 8000
LANGUAGES = (
    "uz is Uzbek in Latin script with o‘ and g‘ (the polite siz form), ru is Russian (вы), "
    "en is English"
)

REVIEW_SYSTEM = f"""You are Maslahatchi, the business advisor of a pharmacy company in \
Uzbekistan. Write the owner's business review of the period from the facts given as JSON: \
revenue, gross margin and profit against the period before and the average of the periods \
before, each pharmacy's numbers, cash and the forecast's lowest point, expenses that jumped, \
overdue debts, the payroll share, slow-moving stock, the team's lateness, and `signals`: the \
findings that matter, heaviest first, each with a `key`.
Write in the language asked ({LANGUAGES}), in plain words a busy owner reads in a minute.
Return a headline (one sentence: the most important change), what went well and what went \
wrong (up to four short points each), and exactly three suggestions: concrete things to do \
this week, each about one signal (call, check, move, order less, collect, agree new dates).
Rules:
- Use only numbers that appear in the facts, as they are written there; you may shorten money \
to millions with one decimal ("48,1 mln so‘m") or round a percentage to one decimal. Never \
calculate a new number, never invent a name, a date or a cause the facts don't show.
- Every point and every suggestion names the signal it is about: put the signal's `key` in \
`fact`. What went well uses signals whose tone is good, what went wrong those whose tone is bad.
- Suggestions are for the owner running the business, never advice to patients; never \
recommend a medicine, a dose or a treatment.
- No greeting, no emoji, no markdown, no links."""

CHAT_SYSTEM = """You are also Maslahatchi, the company's business advisor. The owner asks \
about the business in plain words: can I afford a second pharmacy, where is my money going, \
which pharmacy earns most, what if the rent goes up. Answer like a calm, practical advisor: the \
answer first in one or two sentences, then the few numbers behind it, then what to do.
- Every number comes from a tool. Use the finance, sales, stock and people tools; \
`briefings_advisor_facts` for the latest weekly review's facts and signals; and \
`briefings_advisor_scenario` for every "what if" about money (a new monthly cost or income \
from a date, a one-time outlay): it gives the forecast's new lowest balance and how long the \
money lasts. Never work out a forecast yourself.
- Say plainly what the data doesn't show; never guess a number, a name or a date.
- Money in the company's currency, shortened to millions ("48,1 mln so‘m"). Never give advice \
to patients about medicines or doses. You can't change anything: say where in the dashboard \
to do it."""

CHAT_DOMAINS = frozenset(
    {"advisor", "finance", "sales", "inventory", "people", "attendance", "payroll", "hr", "assets"}
)


class ReviewItem(BaseModel):
    text: str = PydanticField(description="One short sentence in the language asked.")
    fact: str = PydanticField(description="The key of the signal it is about.")


class ReviewDraft(BaseModel):
    headline: str = PydanticField(description="One sentence: the most important change.")
    went_well: list[ReviewItem] = PydanticField(description="Up to four points, good signals.")
    went_wrong: list[ReviewItem] = PydanticField(description="Up to four points, bad signals.")
    suggestions: list[ReviewItem] = PydanticField(
        description="Exactly three concrete things to do, each about one signal."
    )


# Whether it works here ------------------------------------------------------------------------


def is_on(company) -> bool:
    """Listed for the company (finance, sales, stock or attendance on) and switched on."""
    from apps.ai.models import AgentState

    return AGENT.works_in(company) and (
        AgentState.objects.filter(company=company, key=KEY, enabled=True).exists()
    )


def reschedule(company) -> None:
    """Its next run follows the briefing settings (after an owner changed them)."""
    from apps.ai.models import AgentState

    state = AgentState.objects.filter(company=company, key=KEY, enabled=True).first()
    if state is None:
        return
    state.next_run_at = next_run(registry.config_of(AGENT, state), timezone.now(), company)
    state.save(update_fields=["next_run_at", "updated_at"])


# Writing the review ----------------------------------------------------------------------------


def for_prompt(value):
    """The facts as Claude reads them: without links and ranking weights (the page and the
    order are the server's business), scrubbed."""
    if isinstance(value, dict):
        return {
            key: for_prompt(item) for key, item in value.items() if key not in ("url", "weight")
        }
    if isinstance(value, list):
        return [for_prompt(item) for item in value]
    return value


def write_review(company, facts: dict, *, language: str) -> tuple[dict, str] | None:
    """The review in `language` worded by Claude over `facts`, checked (apps.briefings.writing
    .checked), with the model that wrote it; None without Claude, on any failure, or when
    nothing of the draft held."""
    from apps.briefings import writing

    if not availability.status(company).available or availability.fake():
        return None
    data = scrub_data(for_prompt(facts))
    try:
        result, call = client.structured(
            KEY,
            company=company,
            model=settings.AI_MODEL_FAST,
            schema=ReviewDraft,
            effort="low",
            max_tokens=MAX_TOKENS,
            system=instructions.system_for(company, KEY, REVIEW_SYSTEM),
            user=[
                {
                    "type": "text",
                    "text": f"<language>{language}</language>\n"
                    f"<facts>\n{json.dumps(data, ensure_ascii=False, sort_keys=True)}\n</facts>",
                }
            ],
        )
    except client.ClaudeError as exc:
        logger.info("Advisor review of company %s fell back: %s", company.pk, exc.code)
        return None
    content, kept = writing.checked(result.model_dump(), facts, language)
    if not kept:
        return None
    return content, call.model


# Its schedule ---------------------------------------------------------------------------------


def _schedule(config: dict) -> str:
    return _("Writes the weekly and monthly business reviews; answers questions any time")


def next_run(config: dict, now: datetime, company) -> datetime:
    """The next review's time (the briefing settings), or a day later while both are off."""
    from apps.briefings import conf, periods, reviews

    row = conf.get_settings(company)
    moment = reviews.local(company, now)
    found = [
        when for kind in reviews.KINDS if (when := periods.next_send(row, kind, moment)) is not None
    ]
    return min(found) if found else now + timedelta(days=1)


def run(company, state, now: datetime) -> int:
    """The reviews that are due (written with Claude where it may), or, on "Run now", last
    week's review written again for everyone. How many people they went to."""
    from apps.briefings import periods, reviews

    if getattr(state, "forced", False):
        outcome = reviews.rewrite_latest(company, now, use_ai=True)
        if outcome.reviews:
            events.log(company, KEY, "review_rewritten", params={"count": outcome.reviews})
        return outcome.sent
    sent = 0
    for kind in reviews.KINDS:
        outcome = reviews.run_scheduled(company, kind, now, use_ai=True)
        if outcome.reviews or outcome.sent:
            period = periods.latest(kind, reviews.local(company, now).date())
            events.log(
                company,
                KEY,
                f"{kind}_sent",
                params={"count": outcome.sent},
                dedupe_key=f"advisor:{kind}:{period.start.isoformat()}",
                level="success" if outcome.sent else None,
            )
        sent += outcome.sent
    return sent


def upcoming(company, state, now: datetime) -> list[tuple[datetime | None, str]]:
    """When the next reviews go out, and how many it has written. Counts only."""
    from apps.briefings import conf, periods, reviews
    from apps.briefings.models import Briefing

    row = conf.get_settings(company)
    moment = reviews.local(company, now)
    found = []
    labels = {
        Briefing.Kind.WEEKLY: _("Weekly business review"),
        Briefing.Kind.MONTHLY: _("Monthly business review"),
    }
    for kind in reviews.KINDS:
        if (when := periods.next_send(row, kind, moment)) is not None:
            found.append((when, labels[kind]))
    written = Briefing.objects.filter(company=company).count()
    found.append(
        (
            None,
            ngettext(
                "Reviews written so far: %(count)s",
                "Reviews written so far: %(count)s",
                written,
            )
            % {"count": written},
        )
    )
    return found


# Ask the advisor without Claude (AI_FAKE) -----------------------------------------------------

WHAT_IF = re.compile(
    r"\b(agar|filial|ikkinchi|ochsam|ochish|если|филиал|втор|открыть|what if|branch|second|afford)",
    re.IGNORECASE,
)


def fake_answer(ctx, question: str) -> tuple[str, list[dict]]:
    """A canned answer for AI_FAKE that calls the real advisor tools: the latest review's
    headline, what went wrong and what to do; for a "what if" question, the scenario of one
    more pharmacy that costs what an average one does."""
    import time

    from apps.ai.tools import registry as tools

    steps: list[dict] = []

    def call(name: str, args: dict) -> dict:
        tool = tools.get_tool(name)
        if tool is None or not tool.allowed(ctx):
            return {}
        started = time.monotonic()
        result = tools.run_tool(name, ctx, args)
        steps.append(
            {
                "label": str(tool.label),
                "status": "error" if "error" in result else "done",
                "ms": int((time.monotonic() - started) * 1000),
            }
        )
        return result.get("data") or {}

    data = call("briefings_advisor_facts", {})
    review = data.get("review") or {}
    finance = (data.get("facts") or {}).get("finance")
    lines: list[str] = []
    if WHAT_IF.search(question or "") and finance:
        lines += _what_if_lines(finance, call, ctx.language)
    else:
        if review.get("headline"):
            lines.append(f"**{review['headline']}**")
        lines += [f"- {text}" for text in review.get("went_wrong", [])[:3]]
        lines += [f"{n}. {text}" for n, text in enumerate(review.get("suggestions", []), 1)]
    if not lines:
        lines.append(_("There is no business review yet: the first one comes on Monday morning."))
    return "\n".join(lines), steps


def _what_if_lines(finance: dict, call, language: str) -> list[str]:
    """One more pharmacy that costs what an average one costs to run (its gross profit less its
    profit: rent, salaries, bills), a month of it, on the cash forecast."""
    from apps.briefings import display

    branches = max(len(finance.get("branches") or []), 1)
    gross = finance["gross_profit"]["average"] or finance["gross_profit"]["value"]
    profit = finance["profit"]["average"] or finance["profit"]["value"]
    weekly = max(float(gross or 0) - float(profit or 0), 0.0)
    monthly_cost = round(weekly * 52 / 12 / branches, -5)
    scenario = call(
        "briefings_advisor_scenario",
        {"monthly_change": f"{-monthly_cost:.2f}", "label": "second pharmacy"},
    )
    if not scenario:
        return []
    currency = scenario.get("currency") or "UZS"
    found = scenario["scenario"]
    lines = [
        _(
            "One more pharmacy that costs about %(cost)s a month to run: the lowest balance "
            "would be %(low)s (%(date)s)."
        )
        % {
            "cost": display.money(monthly_cost, currency, language),
            "low": display.money(found["low"]["balance"], currency, language),
            "date": display.day(found["low"]["date"], language),
        }
    ]
    if found["below_zero_on"]:
        lines.append(
            _("On %(date)s the money would run out: not yet, or only with a loan or a partner.")
            % {"date": display.day(found["below_zero_on"], language)}
        )
    else:
        days = scenario["days"]
        lines.append(
            ngettext(
                "Even then the money lasts the next %(days)s day: it fits, as long as the new "
                "pharmacy starts selling soon.",
                "Even then the money lasts the next %(days)s days: it fits, as long as the new "
                "pharmacy starts selling soon.",
                days,
            )
            % {"days": days}
        )
    return lines


AGENT = registry.register(
    Agent(
        key=KEY,
        order=5,
        features=(Feature.FINANCE, Feature.SALES, Feature.STOCK, Feature.ATTENDANCE),
        name=gettext_lazy("Advisor"),
        description=gettext_lazy(
            "Your business advisor: every Monday morning the weekly review of the business "
            "(what went well, what went wrong and three concrete suggestions, each tied to a "
            "number), the monthly one on the first, and answers about the business any time: "
            "can I afford a second pharmacy, where is my money going."
        ),
        icon="trending-up",
        needs_claude=False,
        default_enabled=True,
        prompts=(
            Prompt(gettext_lazy("The business review"), REVIEW_SYSTEM),
            Prompt(gettext_lazy("Ask the advisor"), CHAT_SYSTEM),
        ),
        fields=(),
        schedule=_schedule,
        run_label=gettext_lazy("The business review"),
        run=run,
        next_run=next_run,
        upcoming=upcoming,
        usage_features=(KEY, CHAT_FEATURE),
        events={
            "weekly_sent": EventTemplate(
                ngettext_lazy(
                    "Sent the weekly business review to %(count)s person",
                    "Sent the weekly business review to %(count)s people",
                    "count",
                )
            ),
            "monthly_sent": EventTemplate(
                ngettext_lazy(
                    "Sent the monthly business review to %(count)s person",
                    "Sent the monthly business review to %(count)s people",
                    "count",
                )
            ),
            "review_rewritten": EventTemplate(
                ngettext_lazy(
                    "Wrote last week's business review again (%(count)s copy)",
                    "Wrote last week's business review again (%(count)s copies)",
                    "count",
                ),
                level="success",
            ),
        },
    )
)
