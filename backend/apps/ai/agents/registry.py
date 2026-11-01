"""The registry of AI agents (v0.2 AI contract §3).

An agent is a module in `apps/ai/agents/` that registers one `Agent`: what it is called, what
it does, whether it needs Claude, its settings (`fields`, rendered by the dashboard), how its
schedule reads, its `run(company, state)` when it works on a schedule, and the templates of the
events it logs (worded at read time in the reader's language, apps.ai.events).

    state = state_of(company, "voice_tasks")         # the AgentState row, made on first read
    config = config_of(get("voice_tasks"), state)     # the settings, defaults filled in
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
    # For agents that work on a schedule: run(company, state) -> number of things done.
    run: Callable | None = None
    # Whether it needs a speech service to do all it says (voice tasks).
    needs_speech: bool = False

    @property
    def scheduled(self) -> bool:
        return self.run is not None

    def defaults(self) -> dict:
        return {item.key: item.default for item in self.fields}


_agents: dict[str, Agent] = {}


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
    """In the order they were registered (the dashboard's order)."""
    return list(_agents.values())


def state_of(company, key: str):
    """The company's AgentState row of agent `key` (off, with its defaults, until switched on)."""
    from apps.ai.models import AgentState

    state = AgentState.objects.filter(company=company, key=key).first()
    if state is not None:
        return state
    agent = _agents[key]
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
