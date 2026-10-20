"""Employee bot, Package F. Attendance: `/checkin` and the "📍 Keldim / Ketdim" button
(a location share as the fallback), shift-start nudges, "still working?", swap and cover
requests.

Registered inside the member router, after the state-bound tasks and announcements routers
and before the home router (docs/PLAN-OWNER.md §10.2, rule 20).
"""

from aiogram import Router

router = Router(name="feature_attendance")
