"""Employee bot, Package G. HR: applicants from `/start job_…` (registered with
`bot.deeplinks.register_start_param`), policies to accept, documents about to expire,
probation and contract endings.

Registered inside the member router, after the state-bound tasks and announcements routers
and before the home router (docs/PLAN-OWNER.md §10.2, rule 20).
"""

from aiogram import Router

router = Router(name="feature_hr")
