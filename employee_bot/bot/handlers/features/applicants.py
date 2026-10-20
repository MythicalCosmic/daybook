"""Employee bot, Package G. Vacancy applicants, who are not members of the company: the
conversation after `/start job_…` (questions, then the contact share).

Registered outside the member gate, right after the start router and before the contact router,
so an applicant's answers and contact reach the application instead of the join flow. Handlers
here are bound to the applicant's conversation states, so they never take members' messages.
"""

from aiogram import F, Router
from aiogram.enums import ChatType

router = Router(name="feature_applicants")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)
