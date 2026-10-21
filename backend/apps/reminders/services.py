"""Reminder policies from the owner console (docs/PLAN-OWNER.md §1.3): create, change, delete,
make one the company's default, and copy them into another company. Every change is audited
and takes `by: Membership`. Owner texts per step live in `ReminderText` rows, replaced as a set."""

import re
from datetime import time

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.reminders.models import ReminderPolicy, ReminderText

FIELDS = frozenset(
    {
        "name",
        "heads_up_minutes",
        "repeat_every_minutes",
        "max_reminders",
        "escalate_after",
        "quiet_from",
        "quiet_until",
        "quiet_days",
        "snooze_minutes",
        "max_snoozes",
        "replace_previous",
    }
)
PLACEHOLDERS = frozenset({"{name}", "{task}", "{due}", "{late}"})
LIMITS = {
    "heads_up_minutes": (0, 24 * 60),
    "repeat_every_minutes": (5, 24 * 60),
    "max_reminders": (0, 100),
    "escalate_after": (0, 100),
    "snooze_minutes": (5, 24 * 60),
    "max_snoozes": (0, 10),
}
MAX_TEXTS = 12
MAX_TEXT_LENGTH = 1000


@transaction.atomic
def create_policy(*, by: Membership, texts=None, **fields) -> ReminderPolicy:
    _ensure_may_configure(by)
    policy = ReminderPolicy(company_id=by.company_id, is_default=False)
    _apply(policy, fields)
    policy.save()
    if texts is not None:
        _set_texts(policy, texts)
    _audit(AuditLog.Action.POLICY_CREATED, policy, by)
    return policy


@transaction.atomic
def update_policy(
    policy: ReminderPolicy, *, by: Membership, texts=None, **fields
) -> ReminderPolicy:
    _ensure_may_configure(by)
    policy = ReminderPolicy.objects.select_for_update().get(pk=policy.pk)
    before = audit.snapshot(policy) | {"texts": _texts_of(policy)}
    _apply(policy, fields)
    policy.save()
    if texts is not None:
        _set_texts(policy, texts)
    if changes := audit.diff(before, audit.snapshot(policy) | {"texts": _texts_of(policy)}):
        _audit(AuditLog.Action.POLICY_CHANGED, policy, by, changes=changes)
    return policy


@transaction.atomic
def delete_policy(policy: ReminderPolicy, *, by: Membership) -> None:
    """Routines and tasks that used it fall back to the company's default."""
    _ensure_may_configure(by)
    if policy.is_default:
        raise DomainError(_("The company's default policy can't be deleted."))
    _audit(AuditLog.Action.POLICY_DELETED, policy, by)
    policy.delete()


@transaction.atomic
def make_default(policy: ReminderPolicy, *, by: Membership) -> ReminderPolicy:
    """Make `policy` the one every routine and task without its own uses."""
    _ensure_may_configure(by)
    policies = list(
        ReminderPolicy.objects.select_for_update()
        .filter(company_id=policy.company_id)
        .order_by("pk")
    )
    current = next((p for p in policies if p.is_default), None)
    target = next(p for p in policies if p.pk == policy.pk)
    if current is not None and current.pk == target.pk:
        return target
    if current is not None:
        current.is_default = False
        current.save(update_fields=["is_default", "updated_at"])
    target.is_default = True
    target.save(update_fields=["is_default", "updated_at"])
    _audit(AuditLog.Action.POLICY_CHANGED, target, by, changes={"is_default": [False, True]})
    return target


def copy_policies(source, target, by: Membership) -> int:
    """For "Copy setup" (§13.2): the source company's policies, with their texts, as new policies
    of `target` (names already taken are skipped). Returns how many were created."""
    taken = set(ReminderPolicy.objects.filter(company=target).values_list("name", flat=True))
    created = 0
    for policy in ReminderPolicy.objects.filter(company=source).prefetch_related("texts"):
        name = (
            policy.name if not policy.is_default else _("%(name)s (copied)") % {"name": policy.name}
        )
        if name in taken:
            continue
        copy = ReminderPolicy.objects.create(
            company=target,
            name=name[:100],
            is_default=False,
            **{field: getattr(policy, field) for field in FIELDS - {"name"}},
        )
        ReminderText.objects.bulk_create(
            ReminderText(policy=copy, from_step=text.from_step, text=text.text)
            for text in policy.texts.all()
        )
        _audit(AuditLog.Action.POLICY_CREATED, copy, by)
        taken.add(name)
        created += 1
    return created


def _ensure_may_configure(by: Membership) -> None:
    if not by.has_perm(Perm.REMINDERS_CONFIGURE):
        raise PermissionDenied(_("You can't change reminder settings."))


def _apply(policy: ReminderPolicy, fields: dict) -> None:
    if unknown := fields.keys() - FIELDS:
        raise ValueError(f"Not a policy field: {sorted(unknown)}")
    if "name" in fields:
        name = (fields.pop("name") or "").strip()
        if not name:
            raise DomainError(_("Give the policy a name."))
        policy.name = name[:100]
    for name, (low, high) in LIMITS.items():
        if name in fields:
            value = int(fields.pop(name))
            if not low <= value <= high:
                raise DomainError(
                    _("%(value)d is out of range: use %(low)d to %(high)d.")
                    % {"value": value, "low": low, "high": high}
                )
            setattr(policy, name, value)
    if "quiet_days" in fields:
        days = sorted({int(day) for day in fields.pop("quiet_days") or ()})
        if any(not 0 <= day <= 6 for day in days):
            raise DomainError(_("Quiet days are 0 (Monday) to 6 (Sunday)."))
        if len(days) == 7:
            raise DomainError(_("Leave at least one day for reminders."))
        policy.quiet_days = days
    for name in ("quiet_from", "quiet_until"):
        if name in fields:
            value = fields.pop(name)
            if value is not None and not isinstance(value, time):
                raise DomainError(_("Pick a time."))
            setattr(policy, name, value)
    if (policy.quiet_from is None) != (policy.quiet_until is None):
        raise DomainError(_("Give both ends of the quiet hours, or neither."))
    if "replace_previous" in fields:
        policy.replace_previous = bool(fields.pop("replace_previous"))


def _set_texts(policy: ReminderPolicy, texts) -> None:
    rows = []
    steps = set()
    for item in texts:
        step, text = int(item["from_step"]), (item.get("text") or "").strip()
        if step < 1 or step > 100:
            raise DomainError(_("Steps start at 1."))
        if step in steps:
            raise DomainError(_("Each step can have one text."))
        if not text:
            raise DomainError(_("A reminder text can't be empty."))
        if len(text) > MAX_TEXT_LENGTH:
            raise DomainError(
                _("Keep a reminder text under %(max)d characters.") % {"max": MAX_TEXT_LENGTH}
            )
        unknown = set(re.findall(r"\{[a-z_]+\}", text)) - PLACEHOLDERS
        if unknown:
            raise DomainError(
                _("Unknown placeholder %(names)s. Use {name}, {task}, {due} or {late}.")
                % {"names": ", ".join(sorted(unknown))}
            )
        steps.add(step)
        rows.append(ReminderText(policy=policy, from_step=step, text=text))
    if len(rows) > MAX_TEXTS:
        raise DomainError(_("At most %(max)d texts per policy.") % {"max": MAX_TEXTS})
    policy.texts.all().delete()
    ReminderText.objects.bulk_create(sorted(rows, key=lambda row: row.from_step))


def _texts_of(policy: ReminderPolicy) -> list[list]:
    return [[text.from_step, text.text] for text in policy.texts.order_by("from_step")]


def _audit(action, policy: ReminderPolicy, by: Membership, **details) -> None:
    audit.record(action, company_id=policy.company_id, actor=by.user, target=policy, **details)
