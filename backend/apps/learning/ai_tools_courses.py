"""Read-only AI tools of package Q1 (courses, lessons, videos, who watched what), imported
by `ai_tools.py`.

Each wraps a query and registers with `apps.ai.tools.registry.ai_tool` (domain "learning",
feature "learning", perm `learning.view`; names start with `learning_`).
"""
