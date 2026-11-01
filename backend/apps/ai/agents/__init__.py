"""The AI agents (v0.2 AI contract §3): one module per agent, each registering itself, in the
order the dashboard shows them.

    from apps.ai import agents
    agents.get("voice_tasks")
"""

from apps.ai.agents import (  # noqa: F401  (each registers itself)
    deadline_watcher,
    morning_plan,
    photo_checker,
    voice_tasks,
)
from apps.ai.agents.registry import (
    Agent,
    EventTemplate,
    Field,
    all_agents,
    clean_config,
    config_of,
    get,
    state_of,
)

__all__ = [
    "Agent",
    "EventTemplate",
    "Field",
    "all_agents",
    "clean_config",
    "config_of",
    "get",
    "state_of",
]
