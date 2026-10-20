"""Employee bot, Package U. CRM: deal reminders for their owners.

Registered inside the member router, after the state-bound tasks and announcements routers
and before the home router (docs/PLAN-OWNER.md §10.2, rule 20).
"""

from aiogram import Router

router = Router(name="feature_crm")
