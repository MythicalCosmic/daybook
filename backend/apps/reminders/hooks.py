"""Registrations of reminders with the shared registries (docs/PLAN-OWNER.md §11.3, Package B).
Imported by `AppConfig.ready()`."""

from django.db.models.signals import post_delete, post_save
from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.console import pulse, registry
from apps.members.permissions import Perm
from apps.reminders import services
from apps.reminders.models import ReminderPolicy


def _policy_exists(member, policy_id: int) -> bool:
    return ReminderPolicy.objects.for_company(member.company_id).filter(pk=policy_id).exists()


# The History tab of a reminder policy for those who configure reminders.
audit_registry.register_target("reminderpolicy", Perm.REMINDERS_CONFIGURE, check=_policy_exists)

# Version key: a policy changed, so the reminders pages refetch.
registry.register_pulse("reminders.policies", perm=Perm.REMINDERS_CONFIGURE, count=None)
registry.register_copy_part(
    "reminders.policies",
    label=_("Reminder policies"),
    perm=Perm.REMINDERS_CONFIGURE,
    copy=services.copy_policies,
)


def _policy_saved(sender, instance, **kwargs):
    pulse.bump(instance.company_id, "reminders.policies")  # a rolled-back bump costs a refetch


post_save.connect(_policy_saved, sender=ReminderPolicy, dispatch_uid="reminders.pulse.saved")
post_delete.connect(_policy_saved, sender=ReminderPolicy, dispatch_uid="reminders.pulse.deleted")
