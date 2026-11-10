"""The Equipment page's story in Demo Dorixona (called from `apps/lifecycle/demo.py`'s `seed`,
before the assets demo gives Jasur the courier's scooter and before the leaving demo builds his
handover list).

- The pharmacy's categories from the suggestions: lab coats, badges, keys, cash-box keys, phones,
  scanners.
- Lab coats (by size) for the pharmacists and both heads, a badge for nearly everyone, the
  cash-box key of each pharmacy with its head, a phone for Otabek (stock and delivery) and a
  barcode scanner for Malika; a few coats, badges and door keys stay in stock.
- Each hand-out has its photo; everything is confirmed in the app except Kamola's new coat
  (given yesterday: she has just been told).
- Sardor handed back a worn coat a month ago and got a new one; Dilshod lost his badge two weeks
  ago, it was written off and a deduction went to payroll.
- Jasur, who leaves next week, holds his badge (and the scooter): two things to hand back.
"""

import io
from datetime import time, timedelta
from decimal import Decimal

from django.db import transaction
from PIL import Image, ImageDraw

from apps.assets import services as assets
from apps.assets.models import Asset
from apps.core import demo_plan as plan
from apps.core.demo_time import moment
from apps.core.exceptions import DomainError
from apps.lifecycle.equipment import services
from apps.members.models import Membership

# Who gets a coat (and a badge), and since how many days; the badge-only people after them.
COATS = ("manager", "farrux", "worker", "madina", "gulnora", "sardor", "malika", "shahzoda")
COATS_RECENT = ("dilshod", "nigora")
BADGE_ONLY = ("jasur", "otabek", "aziza")
SIZES = (("46", 3), ("48", 6), ("50", 4), ("52", 2))


def _picture(kind: str) -> bytes:
    """A calm stand-in photo of the thing (the demo has no camera): a coat, a badge, a key or a
    device, drawn on a soft background."""
    width, height = 640, 480
    backgrounds = {
        "coat": (214, 236, 230),
        "badge": (240, 232, 218),
        "key": (246, 236, 214),
        "device": (224, 230, 238),
    }
    image = Image.new("RGB", (width, height), backgrounds[kind])
    draw = ImageDraw.Draw(image)
    # A soft floor shadow.
    draw.ellipse((150, 400, 490, 450), fill=tuple(max(0, c - 22) for c in backgrounds[kind]))
    if kind == "coat":
        body = [(250, 110), (390, 110), (470, 170), (440, 410), (200, 410), (170, 170)]
        draw.polygon(body, fill=(252, 252, 250), outline=(196, 204, 202))
        draw.polygon([(250, 110), (320, 220), (390, 110)], fill=(236, 240, 238))
        draw.line([(320, 220), (320, 400)], fill=(205, 212, 210), width=3)
        for y in (250, 300, 350):
            draw.ellipse((328, y, 340, y + 12), fill=(170, 182, 180))
        draw.rectangle((210, 300, 270, 330), outline=(205, 212, 210), width=3)
        draw.polygon([(170, 170), (120, 360), (160, 370), (200, 230)], fill=(246, 247, 245))
        draw.polygon([(470, 170), (520, 360), (480, 370), (440, 230)], fill=(246, 247, 245))
    elif kind == "badge":
        draw.rounded_rectangle(
            (200, 120, 440, 400), radius=22, fill=(255, 255, 255), outline=(206, 196, 180), width=3
        )
        draw.rounded_rectangle((200, 120, 440, 180), radius=22, fill=(168, 90, 39))
        draw.rectangle((200, 160, 440, 180), fill=(168, 90, 39))
        draw.ellipse((280, 200, 360, 280), fill=(232, 222, 206))
        for y, x2 in ((300, 400), (325, 380), (350, 360)):
            draw.rounded_rectangle((240, y, x2, y + 12), radius=6, fill=(226, 216, 200))
        draw.rectangle((305, 80, 335, 125), fill=(120, 120, 128))
    elif kind == "key":
        gold, edge = (214, 170, 70), (170, 130, 40)
        draw.ellipse((150, 170, 290, 310), fill=gold, outline=edge, width=4)
        draw.ellipse((195, 215, 245, 265), fill=(246, 236, 214))
        draw.rounded_rectangle((280, 225, 500, 255), radius=10, fill=gold, outline=edge, width=3)
        for x in (430, 465):
            draw.rectangle((x, 250, x + 22, 290), fill=gold, outline=edge, width=3)
    else:
        draw.rounded_rectangle((250, 90, 390, 400), radius=26, fill=(38, 42, 52))
        draw.rounded_rectangle((262, 112, 378, 370), radius=12, fill=(96, 130, 176))
        draw.ellipse((310, 378, 330, 392), fill=(90, 96, 110))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=82)
    return out.getvalue()


def seed(company, people, now) -> None:
    if not company.has_feature("assets"):
        return
    story = plan.Plan(company, people, now)
    if story.small:
        return
    owner = people["owner"]
    first, second = story.branches["C"], story.branches["Y"]
    with moment(story.at(story.day(-120), time(9, 0))):
        cats = {
            key: services.add_category(company, by=owner, suggestion=key)
            for key in ("lab_coat", "badge", "key", "cash_key", "phone", "scanner")
        }
        coats: list[Asset] = []
        for size, count in SIZES:
            coats += services.add_items(
                company,
                by=owner,
                category=cats["lab_coat"],
                name="Xalat",
                quantity=count,
                branch=first if size in ("46", "48") else second,
                note=f"O‘lcham {size}",
                cost=Decimal("185000"),
            )
        badges = services.add_items(
            company, by=owner, category=cats["badge"], name="Beyj", quantity=18, cost="25000"
        )
        # The door keys stay in stock.
        services.add_items(
            company, by=owner, category=cats["key"], name="Eshik kaliti", quantity=3, branch=first
        )
        cash_keys = [
            services.add_items(
                company, by=owner, category=cats["cash_key"], name="Kassa kaliti", branch=branch
            )[0]
            for branch in (first, second)
        ]
        # The cash-box keys carry their pharmacy in the name.
        for asset, branch in zip(cash_keys, (first, second), strict=True):
            Asset.objects.filter(pk=asset.pk).update(name=f"Kassa kaliti — {branch.name}")
        [phone] = services.add_items(
            company,
            by=owner,
            category=cats["phone"],
            name="Telefon Samsung Galaxy A15",
            branch=first,
            cost="2400000",
            serial="SM-A155F-0042",
            model="Samsung Galaxy A15",
        )
        [scanner] = services.add_items(
            company,
            by=owner,
            category=cats["scanner"],
            name="Shtrix-kod skaneri Honeywell",
            branch=second,
            cost="1150000",
            serial="HW-1450G-7781",
            model="Honeywell Voyager 1450g",
        )

    pictures = {kind: _picture(kind) for kind in ("coat", "badge", "key", "device")}
    free_coats = {
        branch.pk: [c for c in coats if c.branch_id == branch.pk] for branch in (first, second)
    }
    free_badges = list(badges)

    def give(key, pairs, *, days_ago, confirm=True, note=""):
        """Give `pairs` [(asset, picture kind)] to `key` `days_ago` (not before they joined),
        each with its photo; confirmed in the app that evening unless `confirm` is off."""
        person = story.member(key)
        pairs = [(asset, kind) for asset, kind in pairs if asset is not None]
        if person is None or person.status != Membership.Status.APPROVED or not pairs:
            return []
        day = max(story.day(-days_ago), story.joined(key) + timedelta(days=1))
        made = []
        with moment(story.at(day, time(9, 30))):
            for asset, kind in pairs:
                made.append(
                    assets.issue(
                        asset,
                        by=owner,
                        membership=person,
                        on=day,
                        condition="new",
                        note=note,
                        photo=assets.handout_photo(pictures[kind]),
                        notify=False,
                    )
                )
        if confirm:
            with moment(story.at(day, time(18, 40))):
                for assignment in made:
                    assets.acknowledge(assignment, by=person)
        return made

    def coat_for(key):
        person = story.member(key)
        pool = free_coats.get(person.home_branch_id if person else first.pk) or free_coats[first.pk]
        return pool.pop(0) if pool else None

    def badge():
        return free_badges.pop(0) if free_badges else None

    for key in COATS:
        give(key, [(coat_for(key), "coat"), (badge(), "badge")], days_ago=90)
    for key in COATS_RECENT:
        give(key, [(coat_for(key), "coat"), (badge(), "badge")], days_ago=45)
    for key in BADGE_ONLY:
        give(key, [(badge(), "badge")], days_ago=80)
    give("manager", [(cash_keys[0], "key")], days_ago=200, note="Ikkinchi nusxasi seyfda")
    give("farrux", [(cash_keys[1], "key")], days_ago=200)
    give("otabek", [(phone, "device")], days_ago=60, note="Zaryadlovchi bilan")
    give("malika", [(scanner, "device")], days_ago=40)

    # Sardor's first coat came back worn a month ago; he got a new one the same day.
    sardor = story.member("sardor")
    held = (
        Asset.objects.filter(custodian=sardor, category=cats["lab_coat"]).first()
        if sardor
        else None
    )
    if held is not None:
        with moment(story.at(story.day(-30), time(10, 15))):
            assets.take_back(
                held,
                by=owner,
                on=story.day(-30),
                condition="worn",
                note="Yengi yirtilgan, yuvishdan keyin ham dog‘",
                photo=assets.handout_photo(pictures["coat"]),
            )
        give("sardor", [(coat_for("sardor"), "coat")], days_ago=30)

    # Dilshod lost his badge this month (payroll's earlier months are closed): written off, a
    # deduction proposed to payroll; a new badge followed the next day.
    dilshod = story.member("dilshod")
    lost = (
        Asset.objects.filter(custodian=dilshod, category=cats["badge"]).first() if dilshod else None
    )
    lost_on = max(story.day(-6), story.today.replace(day=1))
    if lost is not None:
        assignment = lost.assignments.filter(returned_on__isnull=True).first()
        note = "Avtobusda yo‘qotib qo‘ygan"
        with moment(story.at(lost_on, time(17, 20))):
            try:
                with transaction.atomic():
                    services.give_back(
                        assignment,
                        by=owner,
                        outcome=services.LOST,
                        on=lost_on,
                        note=note,
                        deduction=Decimal("50000"),
                        reason="Yo‘qolgan beyj uchun",
                    )
            except DomainError:  # payroll isn't in this build (or the month closed): no deduction
                services.give_back(
                    assignment, by=owner, outcome=services.LOST, on=lost_on, note=note
                )
        give("dilshod", [(badge(), "badge")], days_ago=max(0, (story.today - lost_on).days - 1))

    # Kamola's coat, given yesterday: she hasn't confirmed it yet (the one item waiting).
    kamola = story.member("kamola")
    coat = coat_for("kamola")
    if kamola is not None and coat is not None:
        with moment(story.at(story.day(-1), time(16, 5))):
            services.issue_many(
                company,
                by=owner,
                person=kamola,
                items=[coat],
                on=story.day(-1),
                condition="new",
                note="O‘lchami to‘g‘ri kelmasa, almashtiramiz",
                photo=pictures["coat"],
            )
    give("kamola", [(badge(), "badge")], days_ago=20)
