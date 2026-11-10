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
from apps.faceid import conf, providers
from apps.faceid.audit_actions import FaceIdAction
from apps.faceid.models import FaceDevice
from apps.inbox.registry import register_kind
from apps.members.permissions import Perm

VIEW, MANAGE = Perm.ATTENDANCE_VIEW, Perm.ATTENDANCE_MANAGE
FEATURE = "face_id"

audit_registry.register(FaceIdAction)

# Where people scan only when they come, the terminals' check-ins close quietly.
attendance.register_arrivals_only(conf.arrivals_only)
audit_registry.register_sensitive(FaceDevice, {"token": SECRET})

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
