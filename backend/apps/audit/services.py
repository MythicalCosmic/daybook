"""Writing the audit log. Call `record` inside the change's transaction, so both or neither stay.

Secret fields (apps.audit.redaction) never reach a row: `snapshot()` hides their values and
`record()` masks them in whatever details it gets, then stamps the row with the strictest
permission among the fields it touched (`required_perm`), so the audit API, the History tab,
exports and the AI only show it to people holding that permission.
"""

from datetime import date, datetime, time

from django.db import models

from apps.audit import redaction
from apps.audit.models import AuditLog

# Bookkeeping fields that say nothing about what someone changed.
UNTRACKED = {"id", "company", "created_at", "updated_at"}


def record(
    action: str,
    *,
    company_id: int,
    actor,
    target: models.Model,
    required_perm: str = "",
    **details,
) -> AuditLog:
    """Log `action` on `target`. `required_perm` (a Perm codename) hides the row from people
    without it; the fields' own registered permissions are added on top, strictest wins."""
    model = type(target)
    details = redaction.scrub(model, details)
    perm = redaction.strictest(
        [required_perm, redaction.required_perm(model, redaction.touched_fields(details))]
    )
    return AuditLog.objects.create(
        company_id=company_id,
        actor=actor,
        action=action,
        target_type=target._meta.model_name,
        target_id=target.pk,
        target=str(target)[:255],
        details=details,
        required_perm=perm,
    )


def snapshot(instance: models.Model) -> dict:
    """The instance's editable values as plain JSON, many-to-many links included. Secret
    fields hold a marker that shows as "•••" but still tells `diff()` whether they changed."""
    model = type(instance)
    values = {
        field.name: redaction.redact(model, field.name, plain(getattr(instance, field.attname)))
        for field in instance._meta.concrete_fields
        if field.name not in UNTRACKED
    }
    for field in instance._meta.many_to_many:
        values[field.name] = sorted(getattr(instance, field.name).values_list("pk", flat=True))
    return values


def diff(before: dict, after: dict) -> dict:
    """{field: [old, new]} for what changed."""
    return {
        name: [before.get(name), value]
        for name, value in after.items()
        if before.get(name) != value
    }


def plain(value):
    """A value as JSON can hold it."""
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return [plain(item) for item in value]
    if value is None or isinstance(value, bool | int | float | str | dict):
        return value
    return str(value)
