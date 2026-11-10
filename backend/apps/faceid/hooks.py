"""Registrations of Face ID with the shared registries. Imported by `AppConfig.ready()`.

Face ID reuses the attendance permissions: `attendance.view` sees the scans and their
snapshots, `attendance.manage` runs the terminals, numbers and settings.
"""

from django.utils.translation import gettext_lazy as _

from apps.attendance import services as attendance
from apps.audit import registry as audit_registry
from apps.audit.redaction import SECRET
from apps.console import registry
from apps.core.files import register_file_check
from apps.faceid import bot, conf, providers
from apps.faceid.audit_actions import FaceIdAction
from apps.faceid.models import FaceDevice, FaceIdSettings
from apps.inbox.registry import register_kind
from apps.members.permissions import Perm
from apps.notifications import routes

VIEW, MANAGE = Perm.ATTENDANCE_VIEW, Perm.ATTENDANCE_MANAGE
FEATURE = "face_id"

audit_registry.register(FaceIdAction)

# Where people scan only when they come, the terminals' check-ins close quietly.
attendance.register_arrivals_only(conf.arrivals_only)
audit_registry.register_sensitive(FaceDevice, {"token": SECRET})
audit_registry.register_sensitive(FaceIdSettings, {"bot_token": SECRET})

# Everything Face ID sends to Telegram goes through the company's Face ID bot when it has one.
routes.register("faceid", bot.route, active=bot.has_bot)

# The live feed (any scan), the numbers nobody is linked to (the nav badge), the settings.
registry.register_pulse("faceid.feed", perm=VIEW, count=None, feature=FEATURE)
registry.register_pulse(
    "faceid.unlinked", perm=MANAGE, count=providers.unlinked_count, feature=FEATURE
)
registry.register_pulse("faceid.settings", perm=MANAGE, count=None, feature=FEATURE)

register_file_check("faceid.photo", providers.photo_check)

register_kind(
    "faceid.scan",
    label=_("Who came (Face ID terminals)"),
    audience="owner",
    default_telegram=True,
)
register_kind(
    "faceid.unlinked",
    label=_("Face ID numbers nobody is linked to"),
    audience="owner",
    default_telegram=True,
)
register_kind(
    "faceid.stranger",
    label=_("Unknown faces at a Face ID terminal"),
    audience="owner",
    default_telegram=True,
    severity="warning",
)
