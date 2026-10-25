"""Demo data of announcements (docs/PLAN-OWNER.md §14.3): what Demo Dorixona's owner and heads
send (in the company's Uzbek, like everything its people write), with read receipts, a pinned
rule, a scheduled reminder of the sanitary day, an expired notice and a cancelled one, so the
list, the read-rate bars and the receipts page have something real."""

from datetime import timedelta

from django.utils import timezone

from apps.announcements.audit_actions import AnnouncementAction
from apps.announcements.models import Announcement, Receipt
from apps.announcements.services import audience
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.core import demo_plan
from apps.members.models import Position

ITEMS = [
    {
        "days_ago": 1,
        "author": "owner",
        "text": (
            "<b>Ertadan yangi referent narxlar</b>\n\n"
            "Retseptli dorilarning referent narxlari yangilandi. Ertalab smenani ochishda narx "
            "yorliqlarini yangi ro‘yxat bo‘yicha tekshiring: ustama xarid narxidan "
            "<b>20\u00a0%</b> dan oshmasin.\n\nSavollar bo‘lsa, mudiringizga yozing."
        ),
        "pinned_days": 6,
        "read_share": 0.72,
    },
    {
        "days_ago": 3,
        "author": "manager",
        "text": (
            "Hurmatli jamoa! Shanba kuni Chilonzorda <b>sanitariya kuni</b>: soat 07:00 da "
            "dezinfeksiya, dorixona 08:00 da ochiladi. Muzlatgichlarni oldindan bo‘shatmang."
        ),
        "branches": ["Chilonzor"],
        "read_share": 0.86,
    },
    {
        "days_ago": 6,
        "author": "owner",
        "text": (
            "Sentabr natijalari: Yunusobod rejani <b>104%</b> bajardi, tungi smenada "
            "birorta kassa farqi bo‘lmadi! Rahmat, jamoa!"
        ),
        "read_share": 0.95,
    },
    {
        "days_ago": 9,
        "author": "manager",
        "text": (
            "Kuryer diqqatiga: onlayn buyurtmalarda retseptli dorilar yetkazilmaydi. Insulin va "
            "boshqa sovuq zanjir dorilari faqat termosumkada. Topshirgach "
            "<b>«Bajarildi»</b> tugmasini bosing."
        ),
        "positions": [demo_plan.COURIER],
        "read_share": 1.0,
    },
    {
        "days_ago": 14,
        "author": "owner",
        "text": (
            "Hamkasblar, eslatma: oq xalat va beyj smenaning birinchi daqiqasidan majburiy. "
            "Yangi xalatlarni ofisda Azizadan olishingiz mumkin."
        ),
        "read_share": 0.64,
        "expired_days": 4,
    },
]


def seed(company, people, now) -> None:
    story = demo_plan.Plan(company, people, now)
    branches = {b.name: b for b in company.branches.all()}
    positions = {p.name: p for p in Position.objects.for_company(company)}
    for item in ITEMS:
        author = people[item["author"]]
        sent_at = now - timedelta(days=item["days_ago"], hours=2)
        chosen_branches = [branches[name] for name in item.get("branches", []) if name in branches]
        chosen_positions = [
            positions[name] for name in item.get("positions", []) if name in positions
        ]
        announcement = Announcement.objects.create(
            company=company,
            author=author,
            text=item["text"],
            status=Announcement.Status.SENT,
            sent_at=sent_at,
            pinned_until=now + timedelta(days=item["pinned_days"])
            if "pinned_days" in item
            else None,
            expires_at=now - timedelta(days=item["expired_days"])
            if "expired_days" in item
            else None,
            summary_sent_at=sent_at + timedelta(days=1),
        )
        Announcement.objects.filter(pk=announcement.pk).update(created_at=sent_at)
        announcement.branches.set(chosen_branches)
        announcement.positions.set(chosen_positions)
        recipients = list(
            audience(company.pk, chosen_positions, chosen_branches)
            .exclude(pk=author.pk)
            .order_by("pk")
        )
        reading = round(len(recipients) * item["read_share"])
        Receipt.objects.bulk_create(
            Receipt(
                announcement=announcement,
                membership=person,
                read_at=sent_at + timedelta(minutes=7 + 23 * index) if index < reading else None,
                reminded_at=sent_at + timedelta(hours=3) if index >= reading else None,
            )
            for index, person in enumerate(recipients)
        )
        entry = audit.record(
            AuditLog.Action.ANNOUNCEMENT_SENT,
            company_id=company.pk,
            actor=author.user,
            target=announcement,
            recipients=len(recipients),
        )
        AuditLog.objects.filter(pk=entry.pk).update(created_at=sent_at)

    # The evening before Chilonzor's sanitary day, a reminder the scheduler will send.
    today = story.today
    sanitary_day = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
    evening = timezone.localtime(now).replace(hour=18, minute=0, second=0, microsecond=0)
    send_at = evening + timedelta(days=(sanitary_day - today).days - 1)
    if send_at <= now:
        send_at = now + timedelta(hours=2)
    scheduled = Announcement.objects.create(
        company=company,
        author=people["manager"],
        text=(
            "Eslatma: ertaga <b>Chilonzor</b> dorixonasida sanitariya kuni. "
            "Smena soat 07:00 da boshlanadi, kechikmang!"
        ),
        status=Announcement.Status.SCHEDULED,
        scheduled_for=send_at,
    )
    chilonzor = [branches[name] for name in ("Chilonzor",) if name in branches]
    scheduled.branches.set(chilonzor)
    audit.record(
        AnnouncementAction.SCHEDULED,
        company_id=company.pk,
        actor=people["manager"].user,
        target=scheduled,
        scheduled_for=scheduled.scheduled_for.isoformat(),
        positions=[],
        branches=[branch.name for branch in chilonzor],
    )
    # A notice the owner called off: the team day out next week (the calendar's event, cancelled
    # yesterday) moved to the month after the stock count.
    written, called_off_at = now - timedelta(days=3, hours=1), now - timedelta(hours=20)
    called_off = Announcement.objects.create(
        company=company,
        author=people["owner"],
        text="Keyingi hafta jamoa bilan dam olish kuni — tafsilotlar keyinroq.",
        status=Announcement.Status.CANCELLED,
        scheduled_for=now + timedelta(days=2),
    )
    Announcement.objects.filter(pk=called_off.pk).update(
        created_at=written, updated_at=called_off_at
    )
    for action, at in (
        (AnnouncementAction.SCHEDULED, written),
        (AnnouncementAction.CANCELLED, called_off_at),
    ):
        entry = audit.record(
            action, company_id=company.pk, actor=people["owner"].user, target=called_off
        )
        AuditLog.objects.filter(pk=entry.pk).update(created_at=at)
