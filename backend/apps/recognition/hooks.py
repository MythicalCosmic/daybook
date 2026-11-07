"""Registrations with the shared registries and signal receivers of recognition.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.console import registry
from apps.inbox.registry import register_kind
from apps.members.permissions import Perm
from apps.recognition import notify, providers
from apps.recognition.audit_actions import RecognitionAction

FEATURE = providers.FEATURE

audit_registry.register(RecognitionAction)
audit_registry.register_target("recognitionsettings", Perm.RECOGNITION_MANAGE)
audit_registry.register_target("kudos", Perm.RECOGNITION_MANAGE)

# A version key: the dashboard's leaderboard, kudos and badges refetch after a change.
registry.register_pulse("recognition", perm=providers.READ, count=None, feature=FEATURE)
registry.register_stream(
    "recognition.kudos", perm=providers.READ, fetch=providers.stream, feature=FEATURE
)

# The bot message with "Say thanks back" goes out on its own (notify.kudos), like the tasks
# app's "can't do it": the inbox keeps the entry in the app and sends no second copy.
register_kind(
    notify.KUDOS,
    label=_("Thanks from a colleague"),
    audience="employee",
    default_telegram=False,
)
register_kind(
    notify.LEVEL,
    label=_("A new level reached"),
    audience="employee",
    default_telegram=True,
)
register_kind(
    notify.BADGE,
    label=_("A new badge earned"),
    audience="employee",
    default_telegram=True,
)
