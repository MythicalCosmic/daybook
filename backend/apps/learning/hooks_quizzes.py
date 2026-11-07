"""Registrations of package Q2 (quizzes, the daily question, checks, skills, the tutor).

Imported by `hooks.py`; register a function only once it exists (inbox kinds and actions,
pulse keys, search, streams, file checks, setup steps, company facts, signal receivers).
"""

from apps.audit import registry as audit_registry
from apps.console import registry
from apps.console.perms import AnyOf
from apps.core.files import register_file_check
from apps.learning import quizzes
from apps.members.permissions import Perm

FEATURE = "learning"
READ = AnyOf(Perm.LEARNING_VIEW, Perm.LEARNING_MANAGE)

register_file_check(quizzes.IMAGE_CHECK, quizzes.may_open_image)

# Version keys: open dashboards refetch the bank, the quizzes and their results.
registry.register_pulse(quizzes.PULSE_KEY, perm=READ, count=None, feature=FEATURE)

for model_name in ("question", "quiz"):
    audit_registry.register_target(model_name, Perm.LEARNING_MANAGE)
