"""Demo data of the company calendar: a shop's week of meetings, a training, an inventory
day, a team dinner and a tax deadline, with answers from the invited people."""

from datetime import datetime, time, timedelta

from apps.agenda import queries, services
from apps.agenda.models import Event, EventAttendee
from apps.companies.models import Branch


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    owner, manager = people["owner"], people["manager"]
    worker, madina, jasur, nigora = (people[key] for key in ("worker", "madina", "jasur", "nigora"))
    zone = queries.tz_of(company)
    today = queries.local_day(now, company)
    monday = today - timedelta(days=today.weekday())
    branches = {branch.name: branch for branch in Branch.objects.filter(company=company)}
    chilonzor = branches.get("Chilonzor") or next(iter(branches.values()), None)
    yunusobod = branches.get("Yunusobod")

    def at(day, hour, minute=0):
        return datetime.combine(day, time(hour, minute), tzinfo=zone)

    def event(title, start, *, by=owner, attendees=(), **fields):
        return services.create_event(
            company,
            by=by,
            title=title,
            start=start,
            attendee_ids=[member.pk for member in attendees],
            **fields,
        )

    everyone = [owner, manager, worker, madina, jasur, nigora]
    planning = event(
        "Haftalik reja yig‘ilishi",
        at(monday - timedelta(days=21), 9, 0),
        end=at(monday - timedelta(days=21), 9, 30),
        kind=Event.Kind.MEETING,
        place="Chilonzor filiali, ofis xonasi",
        description="O‘tgan hafta natijalari, shu haftaning rejasi va savollar. 30 daqiqa.",
        attendees=everyone,
        repeat=Event.Repeat.WEEKLY,
        remind_before=30,
    )
    training_day = monday + timedelta(days=3)
    training = event(
        "Yangi kassa dasturi bo‘yicha trening",
        at(training_day, 15, 0),
        end=at(training_day, 17, 0),
        kind=Event.Kind.TRAINING,
        place="Chilonzor filiali",
        branch=chilonzor,
        description="Yangi kassa dasturida smenani ochish, qaytarish va Z-hisobot. "
        "Noutbuk shart emas, kassa yonida o‘tadi.",
        attendees=[manager, madina, worker],
        remind_before=60,
    )
    inventory_day = monday + timedelta(days=5)
    if inventory_day <= today:
        inventory_day += timedelta(days=7)
    inventory = event(
        "Inventarizatsiya — Yunusobod",
        inventory_day,
        all_day=True,
        kind=Event.Kind.INVENTORY,
        branch=yunusobod,
        place="Yunusobod filiali, ombor",
        description="Barcha tovarlar sanaladi. Do‘kon soat 12:00 gacha yopiq bo‘ladi.",
        attendees=[manager, jasur, nigora],
        remind_before=24 * 60,
    )
    dinner_day = monday + timedelta(days=4)
    if dinner_day < today:
        dinner_day += timedelta(days=7)
    dinner = event(
        "Jamoa bilan kechki ovqat",
        at(dinner_day, 19, 0),
        end=at(dinner_day, 21, 30),
        kind=Event.Kind.CELEBRATION,
        place="“Afsona” restorani, Shota Rustaveli 45",
        description="Oyning eng yaxshi xodimlarini taqdirlaymiz. Hamma taklif qilinadi!",
        attendees=everyone,
        remind_before=120,
    )
    supplier_day = today + timedelta(days=1)
    supplier = event(
        "Yetkazib beruvchi bilan uchrashuv — “Coca-Cola Ichimligi”",
        at(supplier_day, 11, 0),
        end=at(supplier_day, 12, 0),
        kind=Event.Kind.MEETING,
        place="Yunusobod filiali",
        visibility=Event.Visibility.ATTENDEES,
        description="Yangi narxlar va yozgi aksiya shartlari.",
        attendees=[owner, jasur],
        remind_before=30,
    )
    tax_day = (
        today.replace(day=25)
        if today.day < 25
        else (today.replace(day=1) + timedelta(days=32)).replace(day=25)
    )
    event(
        "Soliq hisobotini topshirish muddati",
        tax_day,
        all_day=True,
        kind=Event.Kind.DEADLINE,
        visibility=Event.Visibility.ATTENDEES,
        description="QQS va daromad solig‘i hisobotlari my.soliq.uz orqali.",
        attendees=[owner],
        remind_before=3 * 24 * 60,
    )
    event(
        "Oylik natijalar yig‘ilishi",
        at(today.replace(day=1), 18, 0),
        end=at(today.replace(day=1), 19, 0),
        kind=Event.Kind.MEETING,
        place="Chilonzor filiali, ofis xonasi",
        attendees=[owner, manager],
        repeat=Event.Repeat.MONTHLY,
        remind_before=60,
    )
    safety_day = monday - timedelta(days=5)
    event(
        "Yong‘in xavfsizligi bo‘yicha yo‘riqnoma",
        at(safety_day, 10, 0),
        end=at(safety_day, 11, 0),
        kind=Event.Kind.TRAINING,
        place="Chilonzor filiali",
        attendees=[manager, worker, madina, jasur, nigora],
        remind_before=60,
    )
    cleaning = event(
        "Umumiy tozalash kuni",
        monday + timedelta(days=9),
        all_day=True,
        kind=Event.Kind.OTHER,
        attendees=[manager, worker, jasur],
        remind_before=None,
    )
    services.cancel_event(
        cleaning, by=owner, reason="Inventarizatsiyadan keyingi haftaga ko‘chirildi."
    )

    # Answers, as the people would give them in the bot.
    answers = [
        (planning, [manager, worker, madina, jasur], [nigora]),
        (training, [madina, worker], []),
        (inventory, [jasur, nigora], []),
        (dinner, [manager, worker, madina, nigora], [jasur]),
        (supplier, [jasur], []),
    ]
    for item, going, declined in answers:
        for member in going:
            services.respond(item, by=member, response=EventAttendee.Response.GOING)
        for member in declined:
            services.respond(item, by=member, response=EventAttendee.Response.DECLINED)
