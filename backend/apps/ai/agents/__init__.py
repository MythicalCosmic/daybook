"""The AI agents (v0.2 AI contract §3): one module per agent, each registering itself.

from apps.ai import agents
agents.get("voice_tasks")
"""

from apps.ai.agents import voice_tasks  # noqa: F401  (registers itself)
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
