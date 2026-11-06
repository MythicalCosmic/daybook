"""The registry of AI agents (v0.2 AI contract §3).

An agent is a module in `apps/ai/agents/` that registers one `Agent`: what it is called, what
it does, whether it needs Claude, its settings (`fields`, rendered by the dashboard), how its
schedule reads, its `run(company, state)` when it works on a schedule, and the templates of the
events it logs (worded at read time in the reader's language, apps.ai.events). Its page (the
dashboard's agent page) also sums the Claude calls of its `usage_features` and lists what its
`upcoming(company, state, now)` expects.

    state = state_of(company, "voice_tasks")         # the AgentState row, made on first read
    config = config_of(get("voice_tasks"), state)     # the settings, defaults filled in

Built-in agents are code; the agents an owner makes in their own words are rows
(apps.ai.agents.custom, keys `custom_<id>`). `resolve(company, key)` finds either (a custom one
is built from its row), and `agents_for(company)` lists the built-in ones, then the company's
own; `get` and `all_agents` stay the built-in ones only.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import time
from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.functional import Promise
from django.utils.translation import gettext as _

FIELD_TYPES = ("bool", "int", "time", "choice")


@dataclass(frozen=True)
class Field:
    key: str
    type: str
    label: str | Promise
    default: Any
    help: str | Promise = ""
    min: int | None = None
    max: int | None = None
    unit: str | Promise | None = None
    options: tuple[tuple[str, str | Promise], ...] = ()

    def clean(self, value):
        """The value as stored, or ValidationError with a message for the person."""
        if self.type == "bool":
            if not isinstance(value, bool):
                raise ValidationError(_("Choose on or off."))
            return value
        if self.type == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValidationError(_("Enter a whole number."))
            if self.min is not None and value < self.min:
                raise ValidationError(_("At least %(min)s.") % {"min": self.min})
            if self.max is not None and value > self.max:
                raise ValidationError(_("At most %(max)s.") % {"max": self.max})
            return value
        if self.type == "time":
            try:
                parsed = time.fromisoformat(str(value))
            except ValueError:
                raise ValidationError(_("Enter a time as HH:MM.")) from None
            return parsed.strftime("%H:%M")
        if self.type == "choice":
            if value not in {option for option, _label in self.options}:
                raise ValidationError(_("Pick one of the options."))
            return value
        raise ValueError(f"Unknown field type {self.type!r}.")


@dataclass(frozen=True)
class EventTemplate:
    """An event's words, translated when an event is read: a `gettext_lazy` text, or an
    `ngettext_lazy(singular, plural, "count")` one when it counts something, with %(name)s
    placeholders filled from the event's params."""

    text: str | Promise
    level: str = "info"


@dataclass(frozen=True)
class Prompt:
    """What an agent asks Claude, shown on its page: a name for the job in the active language,
    and the system prompt as Claude reads it (English)."""

    label: str | Promise
    text: str


@dataclass(frozen=True)
class Agent:
    key: str
    name: str | Promise
    description: str | Promise
    icon: str  # a lucide icon name
    needs_claude: bool
    default_enabled: bool
    fields: tuple[Field, ...]
    schedule: Callable[[dict], str]
    events: dict[str, EventTemplate] = field(default_factory=dict)
    # For agents that work on a schedule: run(company, state, now) -> how many things it
    # did, and next_run(config, now, company) -> when it runs again.
    run: Callable | None = None
    next_run: Callable | None = None
    # Whether it needs a speech service to do all it says (voice tasks).
    needs_speech: bool = False
    # Where the dashboard lists it (lowest first).
    order: int = 100
    # What a scheduled run does, for its page's upcoming list ("Sends the morning plans").
    run_label: str | Promise = ""
    # The company modules it works for ("hr", "payroll"): listed, and switched on with AI, only
    # where the company has at least one of them.
    features: tuple[str, ...] = ()
    # The `feature` its Claude calls record in AIUsage (apps.ai.client): its key unless said.
    usage_features: tuple[str, ...] = ()
    # upcoming(company, state, now) -> [(when or None, label)]: what it expects next, for its
    # page. Counts only, never a name or a text, about what its own messages are about; the
    # labels in the active language.
    upcoming: Callable | None = None
    # What it asks Claude (none: it works by fixed rules); the owner's instructions follow each.
    prompts: tuple[Prompt, ...] = ()
    # The CustomAgent row a custom agent was built from (None for the built-in ones).
    custom: Any = None

    def __post_init__(self):
        if not self.usage_features:
            object.__setattr__(self, "usage_features", (self.key,))

    @property
    def scheduled(self) -> bool:
        return self.run is not None

    def defaults(self) -> dict:
        return {item.key: item.default for item in self.fields}

    def works_in(self, company) -> bool:
        return not self.features or any(company.has_feature(feature) for feature in self.features)


_agents: dict[str, Agent] = {}

# Custom agents (apps.ai.agents.custom): `custom_<id>`.
CUSTOM_PREFIX = "custom_"


class DuplicateAgent(ValueError):
    pass


def register(agent: Agent) -> Agent:
    if agent.key in _agents:
        raise DuplicateAgent(f"An agent {agent.key!r} is already registered.")
    for item in agent.fields:
        if item.type not in FIELD_TYPES:
            raise ValueError(f"{agent.key}.{item.key}: unknown field type {item.type!r}.")
    _agents[agent.key] = agent
    return agent


def get(key: str) -> Agent | None:
    return _agents.get(key)


def all_agents() -> list[Agent]:
    """In the dashboard's order."""
    return sorted(_agents.values(), key=lambda agent: (agent.order, agent.key))


def is_custom(key: str) -> bool:
    """Whether `key` names an agent an owner made (`custom_12`)."""
    return key.startswith(CUSTOM_PREFIX) and key[len(CUSTOM_PREFIX) :].isdigit()


def resolve(company, key: str) -> Agent | None:
    """The agent `key` of `company`: a built-in one, or one of the company's own (not deleted),
    built from its row. None when there is no such agent."""
    agent = _agents.get(key)
    if agent is None and is_custom(key):
        from apps.ai.agents import custom

        return custom.agent_of(company, key)
    return agent


def agents_for(company) -> list[Agent]:
    """The built-in agents in the dashboard's order, then the company's own, oldest first."""
    from apps.ai.agents import custom

    return all_agents() + custom.agents_of(company)


def event_template(key: str, kind: str) -> EventTemplate | None:
    """The words of event `kind` of agent `key` (every custom agent shares the same ones)."""
    if is_custom(key):
        from apps.ai.agents import custom

        return custom.EVENTS.get(kind)
    agent = _agents.get(key)
    return agent.events.get(kind) if agent else None


def state_of(company, key: str):
    """The company's AgentState row of agent `key` (off, with its defaults, until switched on)."""
    from apps.ai.models import AgentState

    state = AgentState.objects.filter(company=company, key=key).first()
    if state is not None:
        return state
    agent = resolve(company, key)
    if agent is None:
        raise KeyError(key)
    try:
        with transaction.atomic():
            return AgentState.objects.create(company=company, key=key, config=agent.defaults())
    except IntegrityError:
        return AgentState.objects.get(company=company, key=key)


def config_of(agent: Agent, state) -> dict:
    """The agent's settings: the stored values over the defaults (a field added later reads its
    default)."""
    stored = state.config if state is not None and isinstance(state.config, dict) else {}
    return agent.defaults() | {key: stored[key] for key in agent.defaults() if key in stored}


def clean_config(agent: Agent, changes: dict, current: dict) -> dict:
    """`current` with `changes` applied, each checked against its field; unknown keys and bad
    values raise ValidationError({key: [message]})."""
    fields = {item.key: item for item in agent.fields}
    errors = {}
    merged = dict(current)
    for key, value in changes.items():
        if key not in fields:
            errors[key] = [_("Unknown setting.")]
            continue
        try:
            merged[key] = fields[key].clean(value)
        except ValidationError as exc:
            errors[key] = exc.messages
    if errors:
        raise ValidationError(errors)
    return merged
