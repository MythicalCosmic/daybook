"""Employee bot, Package H. Payroll: `/pay` (opens the wallet), payslips with the PDF,
"I received it", bonus, fine and advance messages.

Registered inside the member router, after the state-bound tasks and announcements routers
and before the home router (docs/PLAN-OWNER.md §10.2, rule 20).
"""

from aiogram import Router

router = Router(name="feature_payroll")
