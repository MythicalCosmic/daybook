"""`call_tool` for the people, time-off and announcements tests.

The AI registry's own test (`test_every_installed_tool_follows_the_rules`) discovers every app's
`ai_tools` module into a throwaway registry; when it runs first, these apps' tools are imported
there and never reach the real one. This wrapper registers them again when that happened.
"""

import importlib

from apps.ai.tools import registry
from apps.ai.tools.testing import call_tool as run


def call_tool(name: str, member, **kwargs) -> dict:
    if registry.get_tool(name) is None:
        module = importlib.import_module(f"apps.{name.split('_')[0]}.ai_tools")
        for key in [
            k for k, tool in registry._tools.items() if tool.fn.__module__ == module.__name__
        ]:
            registry._tools.pop(key)
        importlib.reload(module)
    return run(name, member, **kwargs)
