"""Demo data of announcements: what a Tashkent shop owner actually sends (in Uzbek, one in
Russian), with read receipts, a pinned rule, a scheduled reminder, an expired notice and a
cancelled one, so the list, the read-rate bars and the receipts page have something real."""

from datetime import timedelta

from django.utils import timezone

from apps.announcements.models import Announcement, Receipt
from apps.announcements.services import audience
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.members.models import Position

ITEMS = [
    {
        "days_ago": 1,
        "author": "owner",
        "text": (
            "<b>Yangi kassa tartibi</b> 💳\n\n"
            "Ertadan boshlab har bir smena oxirida <b>Z-hisobot</b> va terminal chekini "
            "suratga olib, ilovada smenani yoping. "
            "Naqd pulni sanashda ikki kishi bo‘lishi shart.\n\n"
            "Savollar bo‘lsa, Bekzodga yozing."
        ),
        "pinned_days": 6,
        "read_share": 0.72,
    },
    {
        "days_ago": 3,
        "author": "manager",
        "text": (
            "Hurmatli jamoa! Shanba kuni soat <b>08:00</b> da <u>inventarizatsiya</u> bo‘ladi. "
            "Yunusobod filiali soat 11:00 gacha yopiq. Hammaga omad! 📦"
        ),
        "branches": ["Yunusobod"],
        "read_share": 0.86,
    },
    {
        "days_ago": 6,
        "author": "owner",
        "text": (
            "🎉 Oktabr oyi natijalari: Chilonzor rejani <b>108%</b> bajardi! Eng yaxshi kassir — "
            "Sardor Rahimov. Rahmat, jamoa!"
        ),
        "read_share": 0.95,
    },
    {
        "days_ago": 9,
        "author": "manager",
        "text": (
            "Kuryerlar diqqatiga: yangi buyurtmalar endi botga keladi. Yetkazib bo‘lgach "
            "<b>«Bajarildi»</b> tugmasini bosing va mijozning imzosi bilan chekni suratga oling."
        ),
        "positions": ["Delivery"],
        "read_share": 1.0,
    },
    {
        "days_ago": 14,
        "author": "owner",
        "text": (
            "Коллеги, напоминаю: униформа обязательна с первого дня смены. "
            "Новые футболки можно получить у Азизы в офисе."
        ),
        "read_share": 0.64,
        "expired_days": 4,
    },
]


def seed(company, people, now) -> None:
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

    # Tomorrow morning's reminder, written today and sent by the scheduler.
    tomorrow = timezone.localtime(now).replace(hour=9, minute=0, second=0, microsecond=0)
    Announcement.objects.create(
        company=company,
        author=people["manager"],
        text=(
            "⏰ Eslatma: ertaga <b>Chilonzor</b> filialida sanitariya kuni. "
            "Smena soat 08:30 da boshlanadi, kechikmang!"
        ),
        status=Announcement.Status.SCHEDULED,
        scheduled_for=tomorrow + timedelta(days=1),
    ).branches.set([branches[name] for name in ("Chilonzor",) if name in branches])
    # A notice the owner called off.
    Announcement.objects.create(
        company=company,
        author=people["owner"],
        text="Juma kuni korporativ kechki ovqat — tafsilotlar keyinroq.",
        status=Announcement.Status.CANCELLED,
        scheduled_for=now + timedelta(days=2),
    )
