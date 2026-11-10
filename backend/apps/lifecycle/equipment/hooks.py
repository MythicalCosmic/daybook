"""Equipment's registrations (imported by `apps/lifecycle/hooks.py`): its audit actions on the
person and the pulse key its page refreshes on (the assets services bump it too, so the page
moves when someone confirms in the app)."""

from apps.audit import registry as audit_registry
from apps.console import registry
from apps.lifecycle.equipment import services
from apps.lifecycle.equipment.audit_actions import EquipmentAction

audit_registry.register(EquipmentAction)
registry.register_pulse(services.PULSE, perm=services.MANAGE, count=None, feature="hr")
