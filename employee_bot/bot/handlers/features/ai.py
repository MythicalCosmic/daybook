"""Employee bot, Package K. AI: "Polish with AI" for `/announce` drafts and receipt-reading
replies.

Registered inside the member router, after the state-bound tasks and announcements routers
and before the home router (docs/PLAN-OWNER.md §10.2, rule 20).
"""

from aiogram import Router

router = Router(name="feature_ai")
