"""Registrations of Davomat with the shared registries. Imported by `AppConfig.ready()`.

Everything here is inert in the Daybook edition: the pulse keys are only ever bumped by
Davomat's own endpoints, and the Face ID hook answers None unless `EDITION=davomat`.
"""

from apps.audit import registry as audit_registry
from apps.audit.redaction import SECRET
from apps.console import registry
from apps.davomat import services
from apps.davomat.audit_actions import DavomatAction
from apps.davomat.models import DavomatSettings
from apps.faceid import services as faceid
from apps.members.permissions import Perm

audit_registry.register(DavomatAction)
audit_registry.register_sensitive(DavomatSettings, {"bot_token": SECRET})

# Version keys only (no badges): the dashboard refetches what changed.
registry.register_pulse(services.PULSE_EMPLOYEES, perm=Perm.MEMBERS_VIEW, count=None)
registry.register_pulse(services.PULSE_USERS, perm=Perm.ROLES_MANAGE, count=None)
registry.register_pulse(services.PULSE_TELEGRAM, perm=Perm.COMPANY_SETTINGS, count=None)
registry.register_pulse(services.PULSE_SETTINGS, perm=None, count=None)

# A terminal's unknown number becomes an employee (`auto_create_employees`).
faceid.register_unknown_number(services.auto_create_employee)
