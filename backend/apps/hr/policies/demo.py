"""Demo policies of Demo Dorixona (docs/PLAN-OWNER.md §14.3), run from apps/hr/demo.py.

- **Dori berish qoidalari** (the head, senior pharmacists and pharmacists): version 1 four
  months ago, everyone signed; version 2 ten days ago asked everyone again (with the director's
  order as a PDF). Most signed within days, one signed after the deadline, two still haven't:
  they were reminded the day before the deadline and their managers heard the day after it.
  Version 3 waits as a draft.
- **Saqlash va harorat rejimi** (the same people and the storekeeper): published three days ago,
  a typo fixed yesterday without asking again; half have signed, the rest have four days left.
- **Kassa intizomi** (whoever runs a till): version 1 six weeks ago (one person signed two days
  late, after their head heard); version 2 six days ago, due tomorrow: two still to sign, reminded
  this morning.

Signatures go in through the services as of their moment (`apps.core.demo_time.moment`), inside
each person's hours, after they were asked; people who joined after a version came out were
asked when they joined. The texts describe the pharmacy's own procedures and never advise a
customer. Every name is invented.
"""

from datetime import datetime, time, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.core import demo_plan as plan
from apps.core import pdf
from apps.core.demo_time import moment
from apps.hr.models import Policy, PolicyAcknowledgement
from apps.hr.policies import follow_up, queries, services
from apps.members.models import Position

PHARMACY_STAFF = (plan.HEAD, plan.SENIOR, plan.PHARMACIST)
WITH_STOCK = (*PHARMACY_STAFF, plan.STOCK)
AT_THE_TILL = (plan.SENIOR, plan.PHARMACIST)

DISPENSING_V1 = """
<h2>1. Kim dori beradi</h2>
<p>Dorilarni faqat farmatsevtik ma’lumotli xodim beradi: dorixona mudiri, provizor yoki
farmatsevt. Kuryer va omborchi xaridorga dori bermaydi.</p>
<h2>2. Har bir sotuvda</h2>
<ul>
<li><p>Dori nomi, shakli, seriyasi va yaroqlilik muddati tekshiriladi.</p></li>
<li><p>Retsept bo‘yicha beriladigan dorilar faqat amaldagi retsept bilan beriladi.</p></li>
<li><p>Xaridorga tashxis qo‘yilmaydi va davolash buyurilmaydi: kerak bo‘lsa, shifokorga
yo‘naltiriladi.</p></li>
</ul>
<h2>3. Retseptlar jurnali</h2>
<p>Retsept bo‘yicha berilgan har bir dori o‘sha smenaning o‘zida Retseptlar jurnaliga
yoziladi: sana, dori, seriya, retsept raqami va bergan xodim.</p>
"""
DISPENSING_V2 = (
    DISPENSING_V1
    + """
<h2>4. Elektron retseptlar</h2>
<p>Antibiotiklar va tizimli gormonlar faqat elektron retsept bilan beriladi. Retsept raqami
kassada sotuvga kiritiladi; raqamsiz sotuv ochilmaydi.</p>
<div data-callout="warning"><p>Retsept bo‘lmasa yoki muddati o‘tgan bo‘lsa, dori berilmaydi va
xaridor shifokorga yo‘naltiriladi. Bahslashmang: mudirni chaqiring.</p></div>
"""
)
DISPENSING_V3 = (
    DISPENSING_V2
    + """
<h2>5. Nazoratdagi moddalar</h2>
<p>Nazoratdagi moddalar alohida seyfda saqlanadi, kaliti mudirda turadi. Har bir berilgan
qadoq maxsus jurnalga yoziladi va smena oxirida qoldiq sanaladi.</p>
"""
)
ORDER = """
<h1>Buyruq № 45</h1>
<p>«Demo Dorixona» MChJ, Toshkent</p>
<h2>Dori berish qoidalarining yangi tahririni tasdiqlash to‘g‘risida</h2>
<p>Elektron retseptlar joriy etilgani munosabati bilan:</p>
<ol>
<li><p>«Dori berish qoidalari»ning 2-tahriri tasdiqlansin va barcha dorixonalarda joriy
etilsin.</p></li>
<li><p>Dorixona mudirlari, provizorlar va farmatsevtlar qoidalar bilan ilovada tanishib,
imzo qo‘ysin.</p></li>
<li><p>Buyruq ijrosini nazorat qilish dorixona mudirlariga yuklansin.</p></li>
</ol>
<p>Direktor: D. Karimova</p>
"""

STORAGE_V1 = """
<h2>1. Harorat va namlik</h2>
<table><tbody>
<tr><th><p>Joy</p></th><th><p>Harorat</p></th><th><p>Namlik</p></th></tr>
<tr><td><p>Savdo zali</p></td><td><p>+15 °C dan +25 °C gacha</p></td><td><p>60% gacha</p></td></tr>
<tr><td><p>Muzlatgich (sovuq zanjir)</p></td><td><p>+2 °C dan +8 °C gacha</p></td>
<td><p>—</p></td></tr>
<tr><td><p>Ombor</p></td><td><p>+15 °C dan +25 °C gacha</p></td><td><p>60% gacha</p></td></tr>
</tbody></table>
<h2>2. Harorat va namlik jurnali</h2>
<p>Ko‘rsatkichlar kuniga ikki marta, smena boshida va oxirida, jurnalga yoziladi: vaqt,
harorat, namlik va yozgan xodim.</p>
<div data-callout="danger"><p>Muzlatgich harorati chegaradan chiqsa: darhol mudirga xabar
bering, dorilarni zaxira muzlatgichga o‘tkazing va jurnalga yozing.</p></div>
<h2>3. Yaroqlilik muddati</h2>
<ul>
<li><p>Muddati olti oydan kam qolgan dorilar «Muddati tugayapti» javoniga qo‘yiladi.</p></li>
<li><p>Muddati o‘tgan dorilar sotuvdan olinadi va hisobdan chiqarish dalolatnomasi
tuziladi.</p></li>
</ul>
"""
STORAGE_V2 = STORAGE_V1.replace(
    "smena boshida va oxirida, jurnalga", "smena boshida va oxirida (08:00 va 20:00), jurnalga"
)

TILL_V1 = """
<h2>1. Smenani ochish</h2>
<ul>
<li><p>Kassa smenasi faqat o‘z nomingiz bilan ochiladi: boshqa xodim nomidan ochilmaydi.</p></li>
<li><p>Boshlang‘ich qoldiq sanaladi va botda tasdiqlanadi.</p></li>
</ul>
<h2>2. Smena davomida</h2>
<ul>
<li><p>Har bir sotuv chek bilan rasmiylashtiriladi.</p></li>
<li><p>Naqd pul kassadan faqat inkassatsiya yoki xarajat hujjati bilan chiqariladi.</p></li>
</ul>
<h2>3. Smenani yopish</h2>
<p>Smena oxirida Z-hisobot olinadi, naqd pul sanaladi, farq bo‘lsa sababi yoziladi.</p>
"""
TILL_V2 = (
    TILL_V1
    + """
<div data-callout="warning"><p>Z-hisobotning surati smena yopilishidan oldin botga yuboriladi.
Suratsiz smena yopilmaydi.</p></div>
"""
)

# Who signed each version, in days after they were asked (and the clock they aimed for);
# missing: not yet.
DISPENSING_SIGNED_V1 = {
    "manager": (0, 11),
    "farrux": (0, 12),
    "sardor": (0, 16),
    "worker": (1, 10),
    "gulnora": (1, 14),
    "madina": (2, 15),
    "nigora": (3, 21),
    "malika": (4, 11),
    "shahzoda": (2, 13),
    "dilshod": (6, 22),
    "kamola": (2, 12),
}
DISPENSING_SIGNED_V2 = {
    "manager": (0, 10),
    "farrux": (0, 11),
    "worker": (1, 9),
    "sardor": (1, 17),
    "madina": (2, 15),
    "malika": (3, 12),
    "gulnora": (4, 10),
    "shahzoda": (6, 13),
    "kamola": (8, 14),  # after the deadline, once her head had heard
}
STORAGE_SIGNED = {
    "manager": (0, 10),
    "madina": (0, 15),
    "farrux": (0, 18),
    "otabek": (1, 11),
    "malika": (1, 12),
    "sardor": (2, 18),  # after the typo fix: signs version 2
}
TILL_SIGNED_V1 = {
    "worker": (0, 15),
    "gulnora": (0, 18),
    "madina": (1, 14),
    "sardor": (1, 16),
    "nigora": (2, 21),
    "malika": (2, 10),
    "shahzoda": (3, 12),
    "dilshod": (9, 21),  # two days late
    "kamola": (1, 10),
}
TILL_SIGNED_V2 = {
    "worker": (0, 12),
    "madina": (1, 15),
    "gulnora": (1, 11),
    "malika": (2, 12),
    "sardor": (3, 16),
    "shahzoda": (4, 10),
    "dilshod": (5, 21),
}


class Timeline:
    """Things that happened, run in the order they happened (each as of its moment); anything
    after `now` didn't happen yet."""

    def __init__(self, now: datetime):
        self.now = now
        self.events: list[tuple[datetime, int, object]] = []

    def at(self, when: datetime, action) -> None:
        if when < self.now:
            self.events.append((when, len(self.events), action))

    def run(self) -> None:
        for when, _order, action in sorted(self.events, key=lambda event: event[:2]):
            with moment(when):
                action()


def seed(company, people, now) -> None:
    story = plan.Plan(company, people, now)
    owner = people["owner"]
    positions = {row.name: row.pk for row in Position.objects.filter(company=company)}

    def ids(names) -> list[int]:
        return [positions[name] for name in names if name in positions]

    at, day = story.at, story.day
    timeline = Timeline(now)

    # Dori berish qoidalari ----------------------------------------------------------------
    with moment(at(day(-121), time(15, 20))):
        dispensing = services.create_policy(
            company,
            by=owner,
            title="Dori berish qoidalari",
            category="dispensing",
            position_ids=ids(PHARMACY_STAFF),
            ack_within_days=7,
            body=DISPENSING_V1,
        )
    first = _publish(story, timeline, dispensing, owner, at(day(-120), time(10, 0)))
    _signatures(story, timeline, dispensing, 1, first, DISPENSING_SIGNED_V1)
    timeline.at(
        at(day(-11), time(16, 40)),
        lambda: services.save_draft(
            dispensing,
            by=owner,
            body=DISPENSING_V2,
            file=_order_pdf(company),
            change_note="Elektron retseptlar bo‘limi qo‘shildi (buyruq № 45)",
        ),
    )
    second = _publish(story, timeline, dispensing, owner, at(day(-10), time(9, 30)))
    _signatures(story, timeline, dispensing, 2, second, DISPENSING_SIGNED_V2)
    # The day before the deadline a reminder; the day after it the managers hear.
    timeline.at(at(day(-4), time(8, 30)), lambda: follow_up.remind_due(company, timezone.now()))
    timeline.at(at(day(-2), time(9, 0)), lambda: follow_up.late_notes(company, timezone.now()))
    timeline.at(
        at(day(-1), time(17, 30)),
        lambda: services.save_draft(
            dispensing, by=owner, body=DISPENSING_V3, change_note="Nazoratdagi moddalar bo‘limi"
        ),
    )

    # Saqlash va harorat rejimi ------------------------------------------------------------
    with moment(at(day(-4), time(17, 0))):
        storage = services.create_policy(
            company,
            by=owner,
            title="Saqlash va harorat rejimi",
            category="storage",
            position_ids=ids(WITH_STOCK),
            ack_within_days=7,
            body=STORAGE_V1,
        )
    published = _publish(story, timeline, storage, owner, at(day(-3), time(9, 15)))
    _signatures(story, timeline, storage, 1, published, STORAGE_SIGNED)

    def fix_a_typo():
        services.save_draft(
            storage, by=owner, body=STORAGE_V2, change_note="Jurnal vaqtlari aniqlashtirildi"
        )
        services.publish(storage, by=owner, asks_again=False)

    timeline.at(at(day(-1), time(16, 30)), fix_a_typo)

    # Kassa intizomi -----------------------------------------------------------------------
    with moment(at(day(-46), time(12, 0))):
        till = services.create_policy(
            company,
            by=owner,
            title="Kassa intizomi",
            category="conduct",
            position_ids=ids(AT_THE_TILL),
            ack_within_days=7,
            body=TILL_V1,
        )
    first = _publish(story, timeline, till, owner, at(day(-45), time(11, 0)))
    _signatures(story, timeline, till, 1, first, TILL_SIGNED_V1)
    timeline.at(at(day(-37), time(9, 5)), lambda: follow_up.late_notes(company, timezone.now()))
    timeline.at(
        at(day(-7), time(15, 10)),
        lambda: services.save_draft(
            till, by=owner, body=TILL_V2, change_note="Z-hisobot surati majburiy bo‘ldi"
        ),
    )
    second = _publish(story, timeline, till, owner, at(day(-6), time(10, 0)))
    _signatures(story, timeline, till, 2, second, TILL_SIGNED_V2)
    timeline.at(at(day(0), time(8, 30)), lambda: follow_up.remind_due(company, timezone.now()))

    timeline.run()


def _publish(story, timeline: Timeline, policy: Policy, by, when: datetime) -> datetime:
    """Publish at `when`, then tell who was asked; someone who joined later was asked (and told)
    when they joined. Returns `when`."""

    def run():
        version = services.publish(policy, by=by)
        joined_later = []
        rows = PolicyAcknowledgement.objects.filter(version=version).select_related("membership")
        for row in rows:
            joined = row.membership.decided_at
            if joined is not None and joined > when:
                row.asked_at = row.notified_at = joined
                row.due_on = queries.due_from(policy, story.local(joined).date())
                joined_later.append(row)
        PolicyAcknowledgement.objects.bulk_update(
            joined_later, ["asked_at", "notified_at", "due_on"]
        )
        follow_up.tell_pending(policy.company, when, policy_id=policy.pk)

    timeline.at(when, run)
    return when


def _signatures(
    story, timeline: Timeline, policy: Policy, number: int, published: datetime, signed: dict
) -> None:
    """Each person in `signed` signs version `number` some days after they were asked (its
    publish day, or the day they joined if later), inside their hours."""
    published_on = story.local(published).date()

    def sign(key: str):
        def run():
            member = story.member(key)
            policy.refresh_from_db()
            row = queries.my_row(member, policy)
            if row is None or row.acknowledged_at is not None or row.version.number != number:
                return
            services.acknowledge(policy.current_version, by=member)

        return run

    for key, (days, hour) in signed.items():
        if story.member(key) is None:
            continue
        asked_on = max(published_on, story.joined(key))
        earliest = (
            published + timedelta(minutes=20)
            if asked_on == published_on
            else story.at(asked_on, time(10, 20))
        )
        signing_day = asked_on + timedelta(days=days)
        aimed = story.at(signing_day, time(hour, 7 * len(key) % 50))
        timeline.at(max(story.at_work(key, signing_day, aimed), earliest), sign(key))


def _order_pdf(company) -> SimpleUploadedFile:
    """The director's order that came with version 2, printed as the contracts are."""
    data = pdf.render_pdf(
        "hr/contract.html",
        {"company": company, "title": "Buyruq № 45", "body": ORDER},
        language="uz",
    )
    return SimpleUploadedFile("buyruq.pdf", data, content_type="application/pdf")
