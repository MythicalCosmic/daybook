"""Employee bot, Package E. Sales and cash: "your till is still open", handover
confirmations ([Received] [Not received]) and shift results for cashiers.

Registered inside the member router, after the state-bound tasks and announcements routers
and before the home router (docs/PLAN-OWNER.md §10.2, rule 20).
"""

from aiogram import Router

router = Router(name="feature_sales")
