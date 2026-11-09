"""The AI agents (v0.2 AI contract §3): one module per agent, each registering itself, in the
order the dashboard shows them.

    from apps.ai import agents
    agents.get("voice_tasks")
    agents.resolve(company, "custom_12")      # an agent an owner made (apps.ai.agents.custom)
"""

from apps.ai.agents import (  # noqa: F401  (each registers itself)
    deadline_watcher,
    hr_assistant,
    morning_plan,
    photo_checker,
    tutor,
    voice_tasks,
)
from apps.ai.agents.registry import (
    Agent,
    EventTemplate,
    Field,
    agents_for,
    all_agents,
    clean_config,
    config_of,
    get,
    is_custom,
    resolve,
    state_of,
)

__all__ = [
    "Agent",
    "EventTemplate",
    "Field",
    "agents_for",
    "all_agents",
    "clean_config",
    "config_of",
    "get",
    "is_custom",
    "resolve",
    "state_of",
]
