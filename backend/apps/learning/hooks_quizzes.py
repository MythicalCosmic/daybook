"""Registrations of package Q2 (quizzes, the daily question, checks, skills, the tutor).

Imported by `hooks.py`; register a function only once it exists (inbox kinds and actions,
pulse keys, search, streams, file checks, setup steps, company facts, signal receivers).
"""

from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.console import registry
from apps.console.perms import AnyOf
from apps.core.files import register_file_check
from apps.inbox.registry import register_kind
from apps.learning import daily, quizzes
from apps.members.permissions import Perm

FEATURE = "learning"
READ = AnyOf(Perm.LEARNING_VIEW, Perm.LEARNING_MANAGE)

register_file_check(quizzes.IMAGE_CHECK, quizzes.may_open_image)

# Version keys: open dashboards refetch the bank, the quizzes and their results.
registry.register_pulse(quizzes.PULSE_KEY, perm=READ, count=None, feature=FEATURE)

for model_name in ("question", "quiz"):
    audit_registry.register_target(model_name, Perm.LEARNING_MANAGE)

# The bot's own message (apps.learning.daily): no notification row; the kind lets a person turn
# the Telegram copy off in their notification settings (the app's card stays).
register_kind(
    daily.KIND,
    label=_("The question of the day"),
    audience="employee",
    default_telegram=True,
)
