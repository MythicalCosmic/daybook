"""Demo data of the people lifecycle (the story is apps/core/demo_plan.py).

Demo Dorixona: Jasur, the courier who is often a little late, got a verbal warning last week,
confirmed it and explained himself; Alisher got a written warning two days ago for a fridge
left too warm, with a fine proposed to payroll (when payroll is there), and hasn't opened it
yet. Bobur's suspension comes from the members demo.
"""

from datetime import time
from decimal import Decimal

from apps.core import demo_plan as plan
from apps.core.demo_time import moment
from apps.core.exceptions import DomainError
from apps.lifecycle import notify, services

NBSP = " "
LATE = (
    "Oxirgi ikki haftada ishga besh marta kechikib keldi (15–40 daqiqa), buyurtmalar "
    "kechroq yetkazildi."
)
LATE_ANSWER = "Mashinam ta’mirda edi, avtobusda yurdim. Endi o‘z vaqtida kelaman."
FRIDGE = (
    f"Muzlatgich harorati +9{NBSP}°C gacha ko‘tarildi, ikki soat jurnalga yozilmadi va "
    "insulinlar boshqa muzlatgichga o‘tkazilmadi."
)
FINE = Decimal("150000")


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    story = plan.Plan(company, people, now)
    head = people["manager"]
    jasur, alisher = people["jasur"], people["worker"]

    with moment(story.at(story.day(-6), time(18, 10))):
        late = services.issue(
            jasur,
            by=head,
            kind="verbal_warning",
            category="lateness",
            description=LATE,
            incident_on=story.day(-7),
        )
        notify.record_issued(late.pk)
    with moment(story.at(story.day(-5), time(9, 20))):
        services.acknowledge(late, by=jasur)
        services.explain(late, by=jasur, text=LATE_ANSWER)
        notify.explanation(late.pk)

    with moment(story.at(story.day(-2), time(19, 5))):
        fridge = {
            "kind": "written_warning",
            "category": "storage_breach",
            "description": FRIDGE,
            "incident_on": story.day(-3),
        }
        try:
            record = services.issue(alisher, by=head, fine_amount=FINE, **fridge)
        except DomainError:  # payroll isn't in (or is off): the warning alone
            record = services.issue(alisher, by=head, **fridge)
        notify.record_issued(record.pk)
