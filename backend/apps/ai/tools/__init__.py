"""Read-only AI assistant tools (docs/PLAN-OWNER.md §8.3).

Each module writes its own tools in `apps/<app>/ai_tools.py` with
`apps.ai.tools.registry.ai_tool`; one runner (`registry.run_tool`) checks permissions, caps
rows and scrubs text for every tool, and `apps.ai.tools.testing.call_tool` runs exactly that
path in tests.
"""
