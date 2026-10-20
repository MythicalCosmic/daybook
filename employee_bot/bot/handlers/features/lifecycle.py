"""Employee bot, Package S. People lifecycle: warnings to read and acknowledge,
suspensions, resignations and equipment hand-overs.

Registered inside the member router, after the state-bound tasks and announcements routers
and before the home router (docs/PLAN-OWNER.md §10.2, rule 20).
"""

from aiogram import Router

router = Router(name="feature_lifecycle")
