"""Registrations of Ko‘z with the shared registries. Imported by `AppConfig.ready()`."""

from apps.audit import registry as audit_registry
from apps.audit.redaction import SECRET
from apps.core.files import register_file_check
from apps.vision import providers
from apps.vision.audit_actions import VisionAction
from apps.vision.models import Agent

audit_registry.register(VisionAction)
# A box's token and pairing code are kept as hashes; even those never show in the audit log.
audit_registry.register_sensitive(Agent, {"token_hash": SECRET, "pairing_hash": SECRET})

register_file_check("vision.snapshot", providers.snapshot_check)
register_file_check("vision.photo", providers.photo_check)
register_file_check("vision.clip", providers.clip_check)
