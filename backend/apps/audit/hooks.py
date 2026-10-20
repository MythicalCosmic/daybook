"""Registrations of the audit log itself: the original action codes (AuditLog.Action)."""

from apps.audit import registry
from apps.audit.models import AuditLog

registry.register(AuditLog.Action)
