"""Registrations of memberships with the shared registries. Imported by AppConfig.ready()."""

from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.console import registry
from apps.console.perms import AnyOf
from apps.exports.registry import register_exporter
from apps.inbox.registry import register_action, register_kind
from apps.members import providers
from apps.members.audit_actions import MemberAction
from apps.members.permissions import Perm
from apps.members.queries import suspended_ids
from apps.tasks import offdays

audit_registry.register(MemberAction)
audit_registry.register_target("membership", Perm.MEMBERS_VIEW, check=providers.history_check)
audit_registry.register_target("accessrole", Perm.ROLES_MANAGE, check=providers.role_history_check)
audit_registry.register_target(
    "position", Perm.POSITIONS_MANAGE, check=providers.position_history_check
)

# Suspended people get no routine tasks while the suspension lasts.
offdays.register(suspended_ids)

# Join requests: in "Needs you", and a Telegram copy for every approver. The employee bot
# answers its Approve button itself (it asks for branches when there are several).
register_kind(
    "members.join",
    label=_("Join request"),
    audience="employee",
    default_telegram=True,
    queue_kind="members.join",
)
register_action("members.join", "approve", providers.approve_from_inbox)
register_action("members.join", "reject", providers.reject_from_inbox)
registry.register_queue(
    "members.join",
    perm=Perm.MEMBERS_APPROVE,
    label=_("Join requests"),
    count=providers.queue_count,
    items=providers.queue_items,
)

registry.register_pulse("members.pending", perm=Perm.MEMBERS_APPROVE, count=providers.queue_count)
registry.register_pulse("members.people", perm=Perm.MEMBERS_VIEW, count=None)
registry.register_pulse(
    "members.roles", perm=AnyOf(Perm.ROLES_MANAGE, Perm.MEMBERS_VIEW), count=None
)
registry.register_pulse(
    "members.positions", perm=AnyOf(Perm.POSITIONS_MANAGE, Perm.MEMBERS_VIEW), count=None
)

registry.register_search("members.person", perm=Perm.MEMBERS_VIEW, search=providers.search)
registry.register_stream("members.joined", perm=Perm.MEMBERS_VIEW, fetch=providers.stream_joined)
registry.register_brief_section(
    "members.people", perm=Perm.MEMBERS_VIEW, order=40, build=providers.brief_section
)
registry.register_offboard_step(
    "members",
    perm=Perm.MEMBERS_MANAGE,
    order=10,
    label=_("Access and work"),
    preview=providers.offboard_step,
)
registry.register_setup_step(
    "members.positions",
    perm=Perm.POSITIONS_MANAGE,
    order=30,
    label=_("Positions"),
    description=_("The jobs people pick when they join: Cashier, Cook, Courier…"),
    url="people/positions",
    done=providers.positions_done,
)
registry.register_copy_part(
    "members.positions",
    label=_("Positions"),
    perm=Perm.POSITIONS_MANAGE,
    copy=providers.copy_positions,
)
registry.register_copy_part(
    "members.roles", label=_("Roles"), perm=Perm.ROLES_MANAGE, copy=providers.copy_roles
)

register_exporter(
    "members.people",
    perm=Perm.MEMBERS_VIEW,
    label=_("Team"),
    columns=providers.EXPORT_COLUMNS,
    rows=providers.export_rows,
)
