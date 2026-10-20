"""Writing the audit log. Call `record` inside the change's transaction, so both or neither stay."""

from datetime import date, datetime, time

from django.db import models

from apps.audit.models import AuditLog

# Bookkeeping fields that say nothing about what someone changed.
UNTRACKED = {"id", "company", "created_at", "updated_at"}


def record(
    action: AuditLog.Action,
    *,
    company_id: int,
    actor,
    target: models.Model,
    **details,
) -> AuditLog:
    return AuditLog.objects.create(
        company_id=company_id,
        actor=actor,
        action=action,
        target_type=target._meta.model_name,
        target_id=target.pk,
        target=str(target)[:255],
        details=details,
    )


def snapshot(instance: models.Model) -> dict:
    """The instance's editable values as plain JSON, many-to-many links included."""
    values = {
        field.name: plain(getattr(instance, field.attname))
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
