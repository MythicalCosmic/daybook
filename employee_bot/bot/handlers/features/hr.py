"""Employee bot, Package G. HR for members: policies to accept, documents about to expire,
probation and contract endings. Applicants aren't members: register `/start job_…` with
`bot.deeplinks.register_start_param` and keep their conversation in `features/applicants.py`.

Registered inside the member router, after the state-bound tasks and announcements routers
and before the home router (docs/PLAN-OWNER.md §10.2, rule 20).
"""

from aiogram import Router

from bot.filters.membership import IsRegistered

router = Router(name="feature_hr")
# Members who finished registering; home asks the others to register first.
router.message.filter(IsRegistered())
router.callback_query.filter(IsRegistered())
