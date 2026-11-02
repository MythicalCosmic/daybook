"""Registrations with the shared registries and signal receivers of the people lifecycle.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.console import registry
from apps.console.perms import AnyOf
from apps.core.files import register_file_check
from apps.inbox.registry import register_kind
from apps.lifecycle import notify, providers
from apps.lifecycle.audit_actions import LifecycleAction
from apps.members.permissions import Perm

FEATURE = "hr"

audit_registry.register(LifecycleAction)

register_file_check("lifecycle.evidence", providers.may_open_evidence)

registry.register_pulse(
    "lifecycle.discipline",
    perm=AnyOf(Perm.HR_DISCIPLINE, Perm.HR_VIEW),
    count=None,
    feature=FEATURE,
)

# The person hears a record was given (the employee bot, into "My record"); whoever gave it
# hears the explanation.
register_kind(
    notify.RECORD,
    label=_("Warnings and reprimands"),
    audience="employee",
    default_telegram=True,
    severity="warning",
)
register_kind(
    notify.EXPLANATION,
    label=_("Explanations to records"),
    audience="owner",
    default_telegram=True,
)
