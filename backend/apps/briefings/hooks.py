"""Registrations with the shared registries and signal receivers of briefings.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.briefings import reviews
from apps.briefings.audit_actions import BriefingAction
from apps.briefings.models import Briefing
from apps.console import registry
from apps.inbox.registry import register_kind
from apps.members.permissions import Perm

audit_registry.register(BriefingAction)
audit_registry.register_target("briefingsettings", Perm.COMPANY_SETTINGS)

# A version key only: the Maslahatchi page refreshes when a review is written or its settings
# change.
registry.register_pulse(reviews.PULSE, perm=Perm.REPORTS_VIEW, count=None)

register_kind(
    reviews.NOTIFY_KIND[Briefing.Kind.WEEKLY],
    label=_("The weekly business review"),
    audience="owner",
    default_telegram=True,
)
register_kind(
    reviews.NOTIFY_KIND[Briefing.Kind.MONTHLY],
    label=_("The monthly business review"),
    audience="owner",
    default_telegram=True,
)
