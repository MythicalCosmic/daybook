"""Registrations with the shared registries and signal receivers of exports.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from apps.audit import registry as audit_registry
from apps.console import registry
from apps.core.files import register_file_check
from apps.exports import files
from apps.exports.audit_actions import ExportAction
from apps.members.permissions import Perm

# Bumped when an export is asked for and when it is ready or failed.
registry.register_pulse("exports.exports", perm=Perm.DATA_EXPORT, count=None)

register_file_check("exports.export", files.can_download)
audit_registry.register(ExportAction)
