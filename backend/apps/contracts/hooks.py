"""Registrations of business contracts with the shared registries.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.console import registry
from apps.contracts import notify, providers, queries
from apps.contracts.audit_actions import ContractsAction
from apps.core.files import register_file_check
from apps.inbox.registry import register_action, register_kind
from apps.insights import decisions, detectors, texts
from apps.insights.models import Insight

READ, MANAGE = providers.READ, providers.MANAGE

audit_registry.register(ContractsAction)
audit_registry.register_target(
    "businesscontract",
    READ,
    check=lambda member, target_id: queries.visible(member).filter(pk=target_id).exists(),
)
audit_registry.register_target("contractsettings", READ)

register_file_check("contracts.file", providers.may_open_file)

# The sidebar badge: contracts ending soon or due for a renewal decision, in the caller's scope.
registry.register_pulse("contracts", perm=READ, count=queries.attention_count)

register_kind(
    notify.KIND,
    label=_("Contracts that end or renew: leases, suppliers, services"),
    audience="owner",
    default_telegram=True,
)
register_action(notify.KIND, notify.KEEP, notify.keep)
register_action(notify.KIND, notify.STOP, notify.stop)

registry.register_search("contracts.contract", perm=READ, search=providers.search)
registry.register_calendar_source(
    "contracts.dates",
    label=_("Contracts"),
    perm=READ,
    events=providers.calendar_events,
)

# Egasi paneli: renewals to decide before their notice deadline, and leases ending soon.
decisions.register_source(
    "contracts.renewals",
    group="other",
    order=90,
    label=_("Contract renewals"),
    perm=MANAGE,
    count=providers.decision_count,
    items=providers.decision_items,
)
detectors.detector(providers.LEASE_KIND, domain=Insight.Domain.FINANCE, feature=None)(
    providers.lease_ending
)
# The insight's words: `apps.insights.texts` renders a kind through this table.
texts.WRITERS[providers.LEASE_KIND] = providers.lease_ending_texts
