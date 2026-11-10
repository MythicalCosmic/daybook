"""Demo data of HR records (docs/PLAN-OWNER.md §14.3; the story is apps/core/demo_plan.py).

Demo Dorixona: a profile for everyone (made-up IDs, birthdays, one coming work anniversary),
the documents a pharmacy keeps (medical books, diplomas, specialist certificates: two medical
books expire within 30 days, one has expired), what each position must have, a contract for
everyone (one fixed-term one ends in three weeks, one probation ends in five days, a newcomer's
waits as a draft, two printed from the company's template), and the person who left with their
contract ended. The distributor gets profiles and contracts. Every number is invented.

Pharmacist coverage (docs/PLAN-OWNER.md §14.3, §14.9): the head, the senior pharmacists and the
pharmacists count, each with a verified diploma and specialist certificate. One certificate
ends in 20 days. The pharmacist on next Saturday's night at Yunusobod has a certificate that
ends the day before and a renewed one she uploaded herself that HR hasn't verified yet, so that
night (and her nights after it) show a coverage gap until someone checks it.
"""

from datetime import date, time, timedelta

from django.utils import timezone

from apps.core import demo_plan as plan
from apps.core.demo_time import moment
from apps.hr import conf, printing, services, watch
from apps.hr.hiring import demo as hiring_demo
from apps.hr.models import (
    Contract,
    ContractKind,
    ContractTemplate,
    DocumentKind,
    EmergencyContact,
    EmployeeDocument,
    EmployeeProfile,
    RequiredDocument,
)
from apps.members.models import Membership, Position

CURRENT = (Membership.Status.APPROVED, Membership.Status.SUSPENDED)

TEMPLATE = """<h1>Mehnat shartnomasi</h1>
<p>{{company_name}} (STIR: {{company_tin}}), bundan buyon «Ish beruvchi», va
{{employee_full_name}}, bundan buyon «Xodim», quyidagilar haqida shartnoma tuzdilar.</p>
<h2>1. Shartnoma predmeti</h2>
<p>Xodim {{branch}} filialida «{{position}}» lavozimida ishlaydi. Ish haftasi:
{{weekly_hours}} soat.</p>
<h2>2. Muddati</h2>
<p>Shartnoma boshlanadigan sana: {{starts_on}}. Tugash sanasi: {{ends_on}}.
Sinov muddati tugaydigan sana: {{probation_until}}.</p>
<h2>3. Mehnatga haq to‘lash</h2>
<p>Ish haqi: {{salary_text}}.</p>
<h2>4. Xodimning majburiyatlari</h2>
<ul><li>Dori vositalarini saqlash va berish qoidalariga rioya qilish.</li>
<li>Tibbiy daftarchani va mutaxassis sertifikatini amal qilish muddatida saqlash.</li></ul>
<p>Sana: {{today}}</p>
<p>Ish beruvchi: ____________ &nbsp;&nbsp; Xodim: ____________</p>"""
TEMPLATE_RU = """<h1>Трудовой договор</h1>
<p>{{company_name}} (ИНН: {{company_tin}}), далее «Работодатель», и {{employee_full_name}},
далее «Работник», заключили настоящий договор.</p>
<p>Должность: {{position}}. Филиал: {{branch}}. Рабочая неделя: {{weekly_hours}} ч.</p>
<p>Начало: {{starts_on}}. Окончание: {{ends_on}}. Испытательный срок до: {{probation_until}}.</p>
<p>Заработная плата: {{salary_text}}.</p>
<p>Дата: {{today}}</p>"""

# key -> (birthday, middle name, gender); made up.
PEOPLE = {
    "owner": (date(1984, 3, 14), "Rustamovna", "female"),
    "manager": (date(1988, 7, 2), "Anvarovich", "male"),
    "worker": (date(1997, 12, 9), "Karimovich", "male"),
    "madina": ((0, 2), "Botirovna", "female"),  # her birthday is the day after tomorrow
    "jasur": (date(2001, 4, 23), "Olimovich", "male"),
    "nigora": (date(1999, 9, 30), "Shavkatovna", "female"),
    "gulnora": ((0, 0), "Ilhomovna", "female"),  # today
    "sardor": (date(1990, 1, 18), "Baxtiyorovich", "male"),
    "farrux": ((0, 5), "Ravshanovich", "male"),
    "malika": (date(1993, 6, 11), "Murodovna", "female"),
    "shahzoda": (date(2000, 2, 27), "Akmalovna", "female"),
    "kamola": (date(2002, 8, 5), "Nodirovna", "female"),
    "dilshod": (date(1995, 11, 21), "Sobirovich", "male"),
    "otabek": (date(1992, 5, 16), "Jamshidovich", "male"),
    "aziza": (date(1986, 10, 3), "Tohirovna", "female"),
    "bobur": (date(1996, 3, 8), "Ulug‘bekovich", "male"),
    "nodira": (date(1994, 12, 1), "Hamidovna", "female"),
    "jahongir": (date(1991, 7, 19), "Sherzodovich", "male"),
}
# Medical books: key -> days until it expires (negative: expired that long ago).
MEDICAL_BOOKS = {"worker": 12, "nigora": 25, "dilshod": -9}
CONTACTS = {
    "worker": [("Valiyeva Muhabbat", "Ona", "+998 90 111 22 33")],
    "madina": [("Saidov Rustam", "Turmush o‘rtog‘i", "+998 93 444 55 66")],
    "nigora": [("Azimova Zarina", "Opa", "+998 97 555 66 77")],
    "jasur": [("Tursunov Olim", "Ota", "+998 91 222 33 44")],
}
PHARMACISTS = (plan.HEAD, plan.SENIOR, plan.PHARMACIST)
# The senior pharmacist whose specialist certificate ends in 20 days.
RENEWS_SOON = "sardor"


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    story = plan.Plan(company, people, now)
    owner = people["owner"]
    settings = conf.get_settings(company)
    settings.employer_name = "«Demo Dorixona» MChJ"
    settings.employer_tin = "305998877"
    settings.save()
    hiring_demo.seed(company, people, now)  # vacancies and applicants (apps.hr.hiring.demo)
    everyone = _everyone(company)
    keys = {member.pk: story.key_of(member) for member in everyone}
    _profiles(company, story, everyone, keys)
    _required(company)
    _documents(company, story, everyone, keys, owner)
    templates = _templates(company, owner)
    _contracts(company, story, everyone, keys, owner, templates)


def seed_small(company, people, now) -> None:
    """The distributor: profiles and a contract for everyone."""
    story = plan.Plan(company, people, now)
    owner = people["owner"]
    everyone = _everyone(company)
    keys = {member.pk: story.key_of(member) for member in everyone}
    _profiles(company, story, everyone, keys)
    for member in everyone:
        if member.pk == owner.pk or member.status not in CURRENT:
            continue
        Contract.objects.create(
            company=company,
            membership=member,
            number=services.next_number(company, _hired(story, keys, member).year),
            kind=ContractKind.INDEFINITE,
            status=Contract.Status.ACTIVE,
            position=member.position,
            starts_on=_hired(story, keys, member),
            weekly_hours=40,
            created_by=owner.user,
            acknowledged_at=now - timedelta(days=30),
        )


def _everyone(company) -> list[Membership]:
    return list(
        Membership.objects.filter(
            company=company,
            status__in=(*CURRENT, Membership.Status.LEFT, Membership.Status.BLOCKED),
        )
        .select_related("user", "position", "home_branch", "company")
        .order_by("decided_at", "pk")
    )


def _hired(story, keys, member) -> date:
    """The day they were hired: their approval, or the story's own day (Sardor came before
    the company used the app). Someone who left or was blocked has the departure as their
    last decision, so their hire day comes from the cast list."""
    key = keys.get(member.pk)
    if key == "sardor":
        return story.day(-(2 * 365) + 3)  # two years with the team in three days
    if key and member.status in (Membership.Status.LEFT, Membership.Status.BLOCKED):
        return story.joined(key)
    if member.decided_at:
        return timezone.localtime(member.decided_at, story.zone).date()
    return story.joined(key) if key else story.today


def _profiles(company, story, everyone, keys) -> None:
    for index, member in enumerate(everyone):
        key = keys.get(member.pk)
        birthday, middle, gender = PEOPLE.get(key, (date(1995, 1, 1), "", ""))
        if isinstance(birthday, tuple):  # (years ago: 0 = this year's date, days from today)
            day = story.day(birthday[1])
            birthday = day.replace(year=day.year - 27)
        telegram_id = member.user.telegram_id or 9_000_000 + index
        serial = telegram_id % 10_000_000
        hired = _hired(story, keys, member)
        by_card = key in ("worker", "madina", "nigora")
        district = ("Chilonzor", "Yunusobod", "Mirzo Ulug‘bek")[index % 3]
        fields = {
            "company": company,
            "employee_number": f"DD-{index + 1:03d}",
            "middle_name": middle,
            "birth_date": birthday,
            "show_birthday": key != "kamola",
            "gender": gender,
            "hire_date": hired,
            "employment_type": "part_time" if key == "jasur" else "full_time",
            "city": "Toshkent",
            "address": f"Toshkent, {district} tumani",
            # Invented numbers in the right shapes (PINFL: sex, birthday, a serial).
            "pinfl": f"{3 if gender == 'male' else 4}{birthday:%d%m%y}{serial:07d}",
            "passport": f"AD{serial:07d}",
            "tin": f"5{telegram_id % 100_000_000:08d}",
            "payout_method": "card" if by_card else "cash",
            "payout_card": f"8600{telegram_id:012d}" if by_card else "",
        }
        if member.status in (Membership.Status.LEFT, Membership.Status.BLOCKED):
            left = timezone.localtime(member.decided_at or story.now, story.zone).date()
            fields["terminated_on"] = left
            fields["termination_reason"] = "resigned" if key == "nodira" else "dismissed"
        profile, _created = EmployeeProfile.objects.update_or_create(
            membership=member, defaults=fields
        )
        for name, relation, phone in CONTACTS.get(key, []):
            EmergencyContact.objects.create(
                company=company, profile=profile, name=name, relation=relation, phone=phone
            )


def _required(company) -> None:
    """A medical book for everyone; the pharmacists as the setup step chooses them (the head,
    the senior pharmacists and the pharmacists, each with its standard documents)."""
    RequiredDocument.objects.get_or_create(
        company=company, kind=DocumentKind.MEDICAL_BOOK, position=None
    )
    positions = {row.name: row for row in Position.objects.filter(company=company)}
    roles = {
        positions[name]: role
        for name, role in (
            (plan.HEAD, services.HEAD),
            (plan.SENIOR, services.SENIOR),
            (plan.PHARMACIST, services.PHARMACIST),
        )
        if name in positions
    }
    if roles:
        services.set_pharmacists(company, by=None, roles=roles)


def saturday_night(story) -> tuple[date, str | None]:
    """Next Saturday (after today), and who of the story works its night at Yunusobod."""
    today = story.today
    saturday = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
    nights = [shift for shift in story.working(saturday, branch="Y") if shift.night]
    return saturday, nights[0].key if nights else None


def _documents(company, story, everyone, keys, owner) -> None:
    today = story.today
    verified_at = story.now - timedelta(days=20)
    saturday, night_key = saturday_night(story)
    for index, member in enumerate(everyone):
        key = keys.get(member.pk)
        if member.status not in CURRENT or key == "owner":
            continue
        position = member.position.name if member.position_id else ""
        rows = []
        days = MEDICAL_BOOKS.get(key, 90 + index * 17)
        rows.append(
            {
                "kind": DocumentKind.MEDICAL_BOOK,
                "number": f"TD-{20000 + index * 37}",
                "issued_on": today + timedelta(days=days) - timedelta(days=365),
                "expires_on": today + timedelta(days=days),
                "issuer": "Toshkent shahar SEO",
            }
        )
        if position in PHARMACISTS:
            higher = position != plan.PHARMACIST or index % 2 == 0
            rows.append(
                {
                    "kind": DocumentKind.PHARMACY_DIPLOMA,
                    "number": f"B-{1_000_000 + index * 7919}",
                    "issued_on": date(2015 + index % 7, 7, 1),
                    "level": "higher" if higher else "college",
                    "specialty": "Farmatsiya",
                    "issuer": "Toshkent farmatsevtika instituti"
                    if higher
                    else "Toshkent farmatsevtika kolleji",
                }
            )
            certificate = {
                "kind": DocumentKind.PHARMACIST_CERTIFICATE,
                "number": f"SRT-{300000 + index * 113}",
                "issued_on": today - timedelta(days=400 + index * 31),
                "expires_on": today + timedelta(days=700 + index * 29),
                "specialty": "Farmatsiya",
                "issuer": "Sog‘liqni saqlash vazirligi",
            }
            if key == RENEWS_SOON:
                certificate["expires_on"] = today + timedelta(days=20)
            if key == night_key:
                # Hers ends the day before next Saturday; the renewed one she sent from the app
                # waits for HR's check, so that night has no qualified pharmacist yet.
                certificate["expires_on"] = saturday - timedelta(days=1)
                certificate["issued_on"] = saturday - timedelta(days=1 + 5 * 365)
                rows.append(
                    {
                        **certificate,
                        "title": "Mutaxassis sertifikati (yangilangan)",
                        "number": f"SRT-{400000 + index * 113}",
                        "issued_on": today - timedelta(days=3),
                        "expires_on": today + timedelta(days=5 * 365),
                        "verified": False,
                        "uploaded_by": member.user,
                    }
                )
            rows.append(certificate)
        if key in ("worker", "madina", "manager"):
            rows.append(
                {
                    "kind": DocumentKind.PASSPORT,
                    "number": f"AD{(member.user.telegram_id or index) % 10_000_000:07d}",
                    "issued_on": date(2020, 5, 12),
                    "expires_on": date(2030, 5, 11),
                    "issuer": "Toshkent shahar IIBB",
                }
            )
        for row in rows:
            verified = row.pop("verified", True)
            EmployeeDocument.objects.create(
                company=company,
                membership=member,
                uploaded_by=row.pop("uploaded_by", owner.user),
                verified_by=owner.user if verified else None,
                verified_at=verified_at if verified else None,
                **row,
            )


def _templates(company, owner) -> dict[str, ContractTemplate]:
    uz = ContractTemplate.objects.create(
        company=company,
        name="Mehnat shartnomasi (namuna)",
        language="uz",
        body=printing.clean_body(TEMPLATE),
        created_by=owner.user,
    )
    ru = ContractTemplate.objects.create(
        company=company,
        name="Трудовой договор (образец)",
        language="ru",
        body=printing.clean_body(TEMPLATE_RU),
        created_by=owner.user,
    )
    return {"uz": uz, "ru": ru}


def _contracts(company, story, everyone, keys, owner, templates) -> None:
    today = story.today
    for member in everyone:
        key = keys.get(member.pk)
        if key == "owner":
            continue
        start = _hired(story, keys, member)
        # Probation: three months, passed long ago (Kamola's is still running).
        probation = start + timedelta(days=90)
        fields = {
            "kind": ContractKind.INDEFINITE,
            "probation_until": probation,
            "probation_passed_at": story.at(probation, time(10)) if probation < today else None,
        }
        if key == "jasur":  # six months as a courier, ending in three weeks
            fields.update(kind=ContractKind.FIXED_TERM, ends_on=story.day(21))
        if key == "kamola":  # new at Yunusobod: her probation ends in five days
            fields.update(probation_until=story.day(5), probation_passed_at=None)
        if probation >= today and key != "kamola":
            fields.update(probation_until=None, probation_passed_at=None)
        status, terminated_on, reason = Contract.Status.ACTIVE, None, ""
        if member.status in (Membership.Status.LEFT, Membership.Status.BLOCKED):
            status = Contract.Status.TERMINATED
            terminated_on = timezone.localtime(member.decided_at or story.now, story.zone).date()
            reason = "O‘z xohishi bilan" if key == "nodira" else "Ish beruvchi tashabbusi bilan"
        elif key is None:
            status = Contract.Status.DRAFT  # joined through this morning's team link
        unread = key in ("worker", "kamola") or status == Contract.Status.DRAFT
        Contract.objects.create(
            company=company,
            membership=member,
            number=services.next_number(company, start.year),
            status=status,
            position=member.position,
            starts_on=start,
            weekly_hours=24 if key == "jasur" else 40,
            template=templates["uz"],
            terminated_on=terminated_on,
            termination_reason=reason,
            acknowledged_at=None if unread else story.at(start, time(12)),
            created_by=owner.user,
            **fields,
        )


def finish(company, people, now) -> None:
    """Once every demo is in (payroll's pay setups among them, attendance's roster): two
    contracts printed from the template, what HR hears this morning, and the roster's gaps
    without a qualified pharmacist (next Saturday night at Yunusobod)."""
    story = plan.Plan(company, people, now)
    owner = people["owner"]
    template = ContractTemplate.objects.filter(company=company, language="uz").first()
    for key in ("worker", "kamola"):
        member = story.member(key)
        contract = Contract.objects.filter(membership=member, status="active").first()
        if template is None or contract is None:
            continue
        with moment(story.at(story.today - timedelta(days=1), time(16, 30))):
            services.generate_pdf(contract, by=owner, template=template)
    watch.watch_company(company, now)
    watch.planned_company(company, now)
