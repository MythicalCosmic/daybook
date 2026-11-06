"""Registrations of fixed assets with the shared registries, and its signal receivers.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from django.utils.translation import gettext_lazy as _

from apps.assets import notify, posting, providers
from apps.assets.audit_actions import AssetAction
from apps.audit import registry as audit_registry
from apps.console import registry
from apps.core.files import register_file_check
from apps.exports.registry import register_exporter
from apps.finance import sources
from apps.inbox.registry import register_kind
from apps.members.signals import member_left

FEATURE = "assets"
READ, MANAGE = providers.READ, providers.MANAGE

audit_registry.register(AssetAction)
audit_registry.register_target("asset", MANAGE)
audit_registry.register_target("assetsettings", MANAGE)

# Ledger rows link back here: the monthly depreciation to its report, an asset's own rows
# (written off, written down, sold) to its page.
sources.register(
    posting.SOURCE_RUN,
    label=_("Depreciation"),
    url_template="/c/{company_id}/assets/depreciation",
)
sources.register(
    posting.SOURCE_ASSET, label=_("Fixed asset"), url_template="/c/{company_id}/assets/items/{id}"
)

register_file_check("assets.file", providers.may_open_file)

registry.register_pulse("assets", perm=READ, count=None, feature=FEATURE)

register_kind(
    notify.UPKEEP,
    label=_("Equipment upkeep: services, instrument checks, warranties, insurance"),
    audience="owner",
    default_telegram=True,
)
register_kind(
    notify.ISSUED,
    label=_("Equipment given to you"),
    audience="employee",
    default_telegram=True,
)

registry.register_search("assets.asset", perm=READ, search=providers.search, feature=FEATURE)
registry.register_calendar_source(
    "assets.upkeep",
    label=_("Equipment upkeep"),
    perm=READ,
    events=providers.calendar_events,
    feature=FEATURE,
)
registry.register_brief_section(
    "assets", perm=READ, order=65, build=providers.brief_section, feature=FEATURE
)
registry.register_offboard_step(
    "assets",
    perm=MANAGE,
    order=45,
    label=_("Equipment they hold"),
    preview=providers.offboard_preview,
    feature=FEATURE,
)
registry.register_setup_step(
    "assets.register",
    perm=MANAGE,
    order=70,
    label=_("Add your equipment"),
    description=_(
        "Fridges, air conditioners, computers, the courier's car: what you own, what it is worth "
        "today, and its depreciation every month."
    ),
    url="assets/items?new=1",
    done=providers.register_done,
    feature=FEATURE,
)
register_exporter(
    "assets.register",
    perm=READ,
    label=_("Fixed asset register"),
    columns=providers.REGISTER_COLUMNS,
    rows=providers.register_rows,
    feature=FEATURE,
)


def on_member_left(sender, membership, reason=None, by=None, details=None, **kwargs) -> None:
    if not membership.company.has_feature(FEATURE):
        return
    providers.on_member_left(
        membership, terminated_on=kwargs.get("terminated_on"), details=details or {}, by=by
    )


member_left.connect(on_member_left, dispatch_uid="assets.member_left")
