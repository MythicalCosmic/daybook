"""Demo data of the people lifecycle (the story is apps/core/demo_plan.py).

Demo Dorixona: Jasur, the courier who is often a little late, got a verbal warning last week,
confirmed it and explained himself; Alisher got a written warning two days ago for a fridge
left too warm, with a fine proposed to payroll (when payroll is there), and hasn't opened it
yet. Bobur's suspension comes from the members demo.

Leaving and job changes (`finish`, once the equipment and pay of the other demos are there):
- Nodira resigned last month: her request, the day Dilnoza agreed, the handover she finished and
  her answers before she went; her final payslip is the payroll demo's.
- Jasur found courier work closer to home: he asked in the app three days ago, Dilnoza agreed his
  last day for Friday next week; he still has the scooter, the keys are handed back.
- Gulnora became a senior pharmacist (Provizor) on the 1st of this month, and her pay follows on
  the 1st of next month (approved, waiting for its day). Aziza proposed moving Shahzoda to
  Chilonzor from the same day; it waits for Dilnoza's approval.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.core import demo_plan as plan
from apps.core.demo_time import moment
from apps.core.exceptions import DomainError
from apps.lifecycle import job_changes, notify, services, terminations
from apps.lifecycle.equipment import demo as equipment_demo
from apps.lifecycle.models import HandoverItem, Termination
from apps.members.models import Membership, Position

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

    # Who holds which uniforms, keys and devices (before the leaving story lists Jasur's).
    equipment_demo.seed(company, people, now)


# Leaving and job changes ---------------------------------------------------------------------

NODIRA_REASON = "Oilaviy sabab: turmush o‘rtog‘im bilan Samarqandga ko‘chib ketyapmiz."
NODIRA_EXIT = {
    "reason": "moving",
    "better": "Kunduzgi smenalar ko‘proq bo‘lsa, yaxshi bo‘lardi. Jamoaga rahmat!",
    "recommend": "yes",
}
NODIRA_NOTES = "Ishonchli farmatsevt, Yunusobodda tungi smenalarni ko‘p olgan. Qaytsa, olamiz."
NODIRA_ITEM = "Kunduzgi smena kassasi kaliti va smena jurnali"
JASUR_REASON = (
    "Uyimga yaqinroq joyda kuryerlik ishini topdim, har kuni ikki soat yo‘lda o‘tyapti. "
    "Ikki hafta oldin ogohlantiryapman."
)
JASUR_EXIT = {
    "reason": "schedule",
    "better": "Yetkazib berish manzillari bir hududda bo‘lsa, yo‘lga kamroq vaqt ketardi.",
    "recommend": "maybe",
}
JASUR_ITEM = "Yetkazib berish jurnali va doimiy mijozlar ro‘yxati"
KEYS_NOTE = "Dorixona kaliti Otabekka topshirildi"
GULNORA_REASON = "Ikki yillik tajriba va oliy farmatsevtika ma’lumoti: provizor lavozimiga."
GULNORA_PAY_REASON = "Provizor lavozimiga o‘tgani uchun maosh provizor stavkasiga ko‘tariladi."
GULNORA_PAY = Decimal("6500000")
SHAHZODA_REASON = (
    "Chilonzorda ertalabki smenaga farmatsevt kerak; Shahzodaning uyi Chilonzorga yaqin."
)


def finish(company, people, now) -> None:
    """Leaving and job changes, once every demo has made its rows (the equipment people hold,
    their pay, Nodira's final payslip)."""
    story = plan.Plan(company, people, now)
    owner = people["owner"]
    _nodira_left(company, story, owner)
    _jasur_leaving(story, owner, people["jasur"])
    _job_changes(company, story, owner)


def _nodira_left(company, story, owner) -> None:
    """Her leaving as it happened: she was gone before this demo runs (the members demo makes
    her a former member), so the record is written as the services left it."""
    nodira = story.member("nodira")
    if nodira is None or nodira.status != Membership.Status.LEFT:
        return
    left_on = story.day(-plan.LEFT_DAYS_AGO)
    asked = story.at(left_on - timedelta(days=16), time(9, 30))
    agreed = story.at(left_on - timedelta(days=15), time(11, 0))
    left = story.at(left_on, time(20, 0))
    with moment(asked):
        termination = Termination.objects.create(
            company=company,
            membership=nodira,
            kind=Termination.Kind.RESIGNATION,
            status=Termination.Status.COMPLETED,
            reason=NODIRA_REASON,
            requested_by=nodira,
            requested_at=asked,
            wished_last_day=left_on,
            last_day=left_on,
            agreed_by=owner,
            agreed_at=agreed,
            completed_at=left,
            left_on=left_on,
            leave_days=Decimal("9"),
            rehire=Termination.Rehire.YES,
            notes=NODIRA_NOTES,
            exit_interview={**NODIRA_EXIT, "answered_at": (agreed + timedelta(days=9)).isoformat()},
            events=[
                _event("requested", asked, nodira, left_on),
                _event("agreed", agreed, owner, left_on),
                _event("completed", left, None, left_on),
            ],
        )
    done_at = story.at(left_on, time(18, 30))
    with moment(done_at):
        for order, kind in enumerate(terminations.STANDARD_ITEMS, start=1):
            HandoverItem.objects.create(
                company=company,
                termination=termination,
                kind=kind,
                order=order,
                done=True,
                done_at=done_at,
                done_by=None if kind == HandoverItem.Kind.TASKS else owner,
            )
        HandoverItem.objects.create(
            company=company,
            termination=termination,
            kind=HandoverItem.Kind.OTHER,
            title=NODIRA_ITEM,
            order=len(terminations.STANDARD_ITEMS) + 1,
            done=True,
            done_at=done_at,
            done_by=owner,
        )
    with moment(left + timedelta(minutes=5)):
        notify.left(termination.pk)


def _jasur_leaving(story, owner, jasur) -> None:
    """Jasur's request, agreed for Friday next week, his handover under way and his answers."""
    friday = story.day(7 - story.today.weekday() + 4)
    last_day = friday if story.works("jasur", friday) else story.next_working_day("jasur", friday)
    last_day = last_day or friday
    with moment(story.at(story.day(-3), time(9, 40))):
        termination = terminations.request(
            jasur, by=jasur, wished_last_day=last_day, reason=JASUR_REASON
        )
    with moment(story.at(story.day(-2), time(11, 15))):
        termination = terminations.agree(termination, by=owner, leave_days=Decimal("6"))
        notify.leave_agreed(termination.pk)
        terminations.add_item(termination, by=owner, title=JASUR_ITEM, kind="documents")
    with moment(story.at(story.day(-1), time(18, 30))):
        keys = termination.handover.filter(kind=HandoverItem.Kind.KEYS).first()
        if keys is not None:
            terminations.set_item(keys, by=owner, done=True, note=KEYS_NOTE)
    with moment(story.at(story.day(-1), time(21, 10))):
        terminations.answer_exit(termination, by=jasur, **JASUR_EXIT)


def _job_changes(company, story, owner) -> None:
    gulnora, shahzoda, aziza = (story.member(key) for key in ("gulnora", "shahzoda", "aziza"))
    senior = Position.objects.filter(company=company, name=plan.SENIOR).first()
    first = story.today.replace(day=1)
    following = (first + timedelta(days=32)).replace(day=1)
    proposer = aziza if aziza is not None and aziza.status == Membership.Status.APPROVED else owner
    if gulnora is not None and senior is not None:
        # The promotion: proposed and approved the week before the 1st, applied on it.
        with moment(_before(story, first, days=6, at=time(15, 0))):
            promotion = job_changes.propose(
                gulnora,
                by=proposer,
                effective_on=first,
                reason=GULNORA_REASON,
                position=senior,
            )
        with moment(_before(story, first, days=5, at=time(10, 30))):
            promotion = job_changes.approve(promotion, by=owner)
        with moment(story.at(first, time(0, 5))):
            job_changes.apply(promotion)
        # Her pay follows next month, approved and waiting for its day.
        try:
            with moment(story.at(story.day(-2), time(16, 20))):
                raise_ = job_changes.propose(
                    gulnora,
                    by=proposer,
                    effective_on=following,
                    reason=GULNORA_PAY_REASON,
                    pay_amount=GULNORA_PAY,
                )
            with moment(story.at(story.day(-1), time(9, 45))):
                raise_ = job_changes.approve(raise_, by=owner)
                if raise_.proposed_by_id != owner.pk:
                    notify.change_decided(raise_.pk)
        except DomainError:
            pass  # payroll isn't in this demo: the promotion stands alone
    if shahzoda is not None:
        chilonzor = story.branches["C"]
        with moment(story.at(story.day(-1), time(17, 5))):
            job_changes.propose(
                shahzoda,
                by=proposer,
                effective_on=following,
                reason=SHAHZODA_REASON,
                branch=chilonzor,
            )


def _before(story, day, *, days: int, at: time) -> datetime:
    """A moment `days` before `day`, never later than now (the 1st may be today)."""
    moment_at = story.at(day - timedelta(days=days), at)
    return min(moment_at, timezone.localtime(story.now, story.zone) - timedelta(hours=1))


def _event(kind: str, at: datetime, by, day) -> dict:
    return {
        "kind": kind,
        "at": at.isoformat(),
        "by": by.pk if by is not None else None,
        "name": str(by) if by is not None else "",
        "day": day.isoformat(),
        "note": "",
    }
