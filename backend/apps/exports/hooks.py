"""Registrations with the shared registries and signal receivers of exports.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from apps.console import compat, registry
from apps.exports import files
from apps.exports.audit_actions import ExportAction
from apps.members.permissions import Perm

# Bumped when an export is asked for and when it is ready or failed.
registry.register_pulse("exports.exports", perm=Perm.DATA_EXPORT, count=None)

compat.register_file_check("exports.export", files.can_download)
compat.register_audit_actions(ExportAction)
