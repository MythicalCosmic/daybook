"""Registrations with the shared registries and signal receivers of learning.

Imported by `AppConfig.ready()`. Each package registers in its own module, so the two never
edit the same file: `hooks_courses.py` (Q1: courses, lessons, videos) and `hooks_quizzes.py`
(Q2: quizzes, the daily question, checks, the tutor).
"""

from apps.audit import registry as audit_registry
from apps.learning import hooks_courses, hooks_quizzes  # noqa: F401  (they register on import)
from apps.learning.audit_actions import CourseAction, QuizAction

audit_registry.register(CourseAction)
audit_registry.register(QuizAction)
