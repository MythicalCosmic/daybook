"""Employee bot, Package I. Finance: `/expense` and receipt photos captioned `#xarajat`,
`#расход` or `#expense`, claim approvals and bill reminders. Photo handlers here are
caption-filtered, never a bare `F.photo`, so they can't take task proof photos.

Registered inside the member router, after the state-bound tasks and announcements routers
and before the home router (docs/PLAN-OWNER.md §10.2, rule 20).
"""

from aiogram import Router

router = Router(name="feature_finance")
