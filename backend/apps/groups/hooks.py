"""Registrations of Telegram groups with the shared registries.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.console import registry
from apps.groups.models import TelegramGroup
from apps.inbox.registry import register_kind
from apps.members.permissions import Perm

audit_registry.register_target("telegramgroup", Perm.GROUPS_MANAGE)

register_kind(
    "groups.removed",
    label=_("The bot was removed from a group"),
    audience="owner",
    default_telegram=True,
    severity="warning",
)

registry.register_pulse("groups.groups", perm=Perm.GROUPS_MANAGE, count=None)


def group_connected(company) -> bool:
    return TelegramGroup.objects.filter(company=company, is_active=True).exists()


registry.register_setup_step(
    "groups.connect",
    perm=Perm.GROUPS_MANAGE,
    order=30,
    label=_("Connect a Telegram group"),
    description=_("The bot posts finished tasks, late ones and the evening summary there."),
    url="groups",
    done=group_connected,
)
