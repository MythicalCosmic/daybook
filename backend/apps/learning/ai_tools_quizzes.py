"""Read-only AI tools of package Q2 (quizzes, the daily question, checks, skills, the tutor),
imported by `ai_tools.py`.

Each wraps a query and registers with `apps.ai.tools.registry.ai_tool` (domain "learning",
feature "learning", perm `learning.view`; names start with `learning_`).
"""
