"""Registrations of policies with the shared registries, and their signal receivers.

Imported by apps/hr/hooks.py (so by `AppConfig.ready()`); everything here belongs to app `hr`.
"""

from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.console import registry
from apps.core.files import register_file_check
from apps.exports.registry import register_exporter
from apps.hr import tasks
from apps.hr.policies import exporters, notify, providers, queries
from apps.hr.policies.audit_actions import PolicyAction
from apps.inbox.registry import register_kind
from apps.members.permissions import Perm
from apps.members.signals import member_approved, member_reinstated

FEATURE = "hr"

audit_registry.register(PolicyAction)
audit_registry.register_target("policy", Perm.HR_VIEW, check=providers.may_see_history)

# A version's file: HR in scope, or the people the policy applies to (the version in force).
register_file_check("hr.policy", providers.may_open_file, allow_suspended=True)

# The sidebar badge (people late with a signature) and the key the pages refetch on.
registry.register_pulse("hr.policies", perm=Perm.HR_VIEW, count=queries.late_count, feature=FEATURE)
registry.register_search("hr.policy", perm=Perm.HR_VIEW, search=queries.search, feature=FEATURE)
register_exporter(
    "hr.policy_signatures",
    perm=Perm.HR_VIEW,
    label=_("Policy signatures"),
    columns=exporters.COLUMNS,
    rows=exporters.rows,
    params=exporters.Params,
    feature=FEATURE,
)

# What people hear (the employee bot, with "Open in app"), and what their managers hear.
register_kind(
    notify.POLICY,
    label=_("Rules to read and sign"),
    audience="employee",
    default_telegram=True,
)
register_kind(
    notify.POLICY_LATE,
    label=_("Rules not signed in time"),
    audience="owner",
    default_telegram=True,
    severity="warning",
)


def on_joined(sender, membership, **kwargs) -> None:
    """Someone approved (or back from a suspension) owes the rules of their position now."""
    if membership.company.has_feature(FEATURE):
        tasks.policies_after_joining.delay(membership.company_id)


member_approved.connect(on_joined, dispatch_uid="hr.policies.member_approved")
member_reinstated.connect(on_joined, dispatch_uid="hr.policies.member_reinstated")
