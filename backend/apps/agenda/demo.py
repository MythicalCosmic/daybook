"""Demo data of the company calendar (docs/PLAN-OWNER.md §14.3): Demo Dorixona's weekly
planning, a cold-chain training, the GPP surveillance visit, a distributor meeting, the monthly
sanitary day, Yunusobod's stock count and a few more, with answers from the invited people.
Nobody away that day (apps/core/demo_plan.py) is invited as coming."""

from datetime import datetime, time, timedelta

from apps.agenda import queries, services
from apps.agenda.models import Event, EventAttendee
from apps.core import demo_plan
from apps.core.demo_time import moment


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    story = demo_plan.Plan(company, people, now)
    owner = people["owner"]
    zone = queries.tz_of(company)
    today = queries.local_day(now, company)
    monday = today - timedelta(days=today.weekday())
    chilonzor, yunusobod = story.branches["C"], story.branches["Y"]

    def at(day, hour, minute=0):
        return datetime.combine(day, time(hour, minute), tzinfo=zone)

    def who(day, *keys):
        """The people of `keys` the company has who aren't away on `day`."""
        return [
            story.member(key)
            for key in keys
            if story.member(key) is not None and story.away(key, day) is None
        ]

    made = []

    def event(title, start, *, by=owner, attendees=(), **fields):
        # Planned a few days ahead (invitations went out then), never "added 2 minutes ago".
        begins = start if isinstance(start, datetime) else at(start, 9)
        added = min(begins - timedelta(days=5), now - timedelta(days=1, hours=3 + len(made) * 5))
        with moment(added):
            item = services.create_event(
                company,
                by=by,
                title=title,
                start=start,
                attendee_ids=[member.pk for member in attendees],
                **fields,
            )
        made.append(item)
        return item

    first_planning = monday - timedelta(days=21)
    planning = event(
        "Haftalik reja yig‘ilishi",
        at(first_planning, 9, 0),
        end=at(first_planning, 9, 30),
        kind=Event.Kind.MEETING,
        place="Chilonzor dorixonasi, ofis xonasi",
        description="O‘tgan hafta natijalari, defektura, shu haftaning rejasi. 30 daqiqa.",
        attendees=who(first_planning, "owner", "manager", "farrux", "madina", "malika"),
        repeat=Event.Repeat.WEEKLY,
        remind_before=30,
    )
    training_day = monday + timedelta(days=3)
    if training_day <= today:
        training_day += timedelta(days=7)
    training = event(
        "Sovuq zanjir bo‘yicha trening",
        at(training_day, 15, 0),
        end=at(training_day, 17, 0),
        kind=Event.Kind.TRAINING,
        place="Chilonzor dorixonasi",
        branch=chilonzor,
        description=(
            "Muzlatgich harorati, termometr ko‘rsatkichini yozish, chegaradan chiqsa nima qilish "
            "kerak. Insulin va vaksinalarni qabul qilish tartibi."
        ),
        attendees=who(
            training_day, "manager", "madina", "worker", "gulnora", "sardor", "nigora", "kamola"
        ),
        remind_before=60,
    )
    inventory_day = story.inventory_day()
    inventory = event(
        "Inventarizatsiya — Yunusobod",
        inventory_day,
        all_day=True,
        kind=Event.Kind.INVENTORY,
        branch=yunusobod,
        place="Yunusobod dorixonasi, ombor",
        description=(
            "Barcha dorilar seriya va muddati bilan sanaladi. Dorixona ishlashda davom etadi: "
            "sanash ombordan boshlanadi."
        ),
        attendees=who(inventory_day, "farrux", "malika", "nigora", "manager"),
        remind_before=24 * 60,
    )
    gpp_day = today + timedelta(days=21)
    event(
        "GPP sertifikati: kuzatuv tashrifi",
        at(gpp_day, 10, 0),
        end=at(gpp_day, 15, 0),
        kind=Event.Kind.DEADLINE,
        place="Chilonzor va Yunusobod dorixonalari",
        description="Saqlash sharoitlari, jurnallar, SOPlar va xodimlar hujjatlari tekshiriladi.",
        attendees=who(gpp_day, "owner", "manager", "madina", "farrux"),
        remind_before=3 * 24 * 60,
    )
    supplier_day = today + timedelta(days=1)
    supplier = event(
        "Distribyutor bilan uchrashuv — Ko‘kterak Farm Distribyutor",
        at(supplier_day, 11, 0),
        end=at(supplier_day, 12, 0),
        kind=Event.Kind.MEETING,
        place="Chilonzor dorixonasi, ofis xonasi",
        visibility=Event.Visibility.ATTENDEES,
        description="Yangi narxlar ro‘yxati, to‘lov muddati va kuzgi aksiya shartlari.",
        attendees=who(supplier_day, "owner", "manager"),
        remind_before=30,
    )
    sanitary_day = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
    event(
        "Oylik sanitariya kuni — Chilonzor",
        at(sanitary_day, 7, 0),
        end=at(sanitary_day, 8, 0),
        kind=Event.Kind.OTHER,
        place="Chilonzor dorixonasi",
        branch=chilonzor,
        description="Dezinfeksiya, javon va muzlatgichlarni yuvish. Dorixona 08:00 da ochiladi.",
        attendees=who(sanitary_day, "manager", "worker", "madina", "gulnora", "sardor"),
        repeat=Event.Repeat.MONTHLY,
        remind_before=12 * 60,
    )
    event(
        "Oylik natijalar yig‘ilishi",
        at(today.replace(day=1), 18, 0),
        end=at(today.replace(day=1), 19, 0),
        kind=Event.Kind.MEETING,
        place="Chilonzor dorixonasi, ofis xonasi",
        attendees=who(today.replace(day=1), "owner", "manager", "farrux"),
        repeat=Event.Repeat.MONTHLY,
        remind_before=60,
    )
    safety_day = monday - timedelta(days=5)
    event(
        "Yong‘in xavfsizligi bo‘yicha yo‘riqnoma",
        at(safety_day, 10, 0),
        end=at(safety_day, 11, 0),
        kind=Event.Kind.TRAINING,
        place="Chilonzor dorixonasi",
        attendees=who(safety_day, "manager", "worker", "madina", "jasur", "nigora"),
        remind_before=60,
    )
    praise_day = monday + timedelta(days=4)
    if praise_day < today:
        praise_day += timedelta(days=7)
    praise = event(
        "Oyning eng yaxshi xodimlarini taqdirlash",
        at(praise_day, 18, 30),
        end=at(praise_day, 19, 30),
        kind=Event.Kind.CELEBRATION,
        place="Chilonzor dorixonasi, ofis xonasi",
        description="Oktabrning eng yaxshi farmatsevtlari va kuryerimizni taqdirlaymiz.",
        attendees=who(praise_day, "owner", "manager", "worker", "madina", "jasur", "nigora"),
        remind_before=120,
    )
    trip = event(
        "Jamoa bilan dam olish kuni",
        monday + timedelta(days=9),
        all_day=True,
        kind=Event.Kind.OTHER,
        attendees=who(monday + timedelta(days=9), "manager", "worker", "jasur"),
        remind_before=None,
    )
    with moment(now - timedelta(hours=20)):
        services.cancel_event(
            trip, by=owner, reason="Inventarizatsiyadan keyingi oyga ko‘chirildi."
        )

    # Answers, as the people would give them in the bot.
    answers = [
        (planning, ["manager", "madina", "farrux"], ["malika"]),
        (training, ["madina", "worker", "gulnora", "nigora"], ["sardor"]),
        (inventory, ["farrux", "nigora", "malika"], []),
        (praise, ["manager", "worker", "madina", "nigora"], ["jasur"]),
        (supplier, ["manager"], []),
    ]
    for item, going, declined in answers:
        invited = set(item.invites.values_list("membership_id", flat=True))
        replies = [(key, EventAttendee.Response.GOING) for key in going]
        replies += [(key, EventAttendee.Response.DECLINED) for key in declined]
        for step, (key, response) in enumerate(replies):
            member = story.member(key)
            if member is None or member.pk not in invited:
                continue
            answered = min(
                item.created_at + timedelta(hours=2 + step * 7), now - timedelta(hours=1)
            )
            with moment(answered):
                services.respond(item, by=member, response=response)
