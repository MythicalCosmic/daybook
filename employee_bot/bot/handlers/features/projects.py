"""Employee bot, Package T. Projects: "you were added to project X" and the weekly nudge
to post an update.

Registered inside the member router, after the state-bound tasks and announcements routers
and before the home router (docs/PLAN-OWNER.md §10.2, rule 20).
"""

from aiogram import Router

router = Router(name="feature_projects")
