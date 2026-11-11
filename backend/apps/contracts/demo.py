"""Demo data of business contracts (the story is apps/core/demo_plan.py).

Demo Dorixona has four contracts, all with the finance demo's own parties and money:

- the Chilonzor lease (Rustam Qodirov, 9 000 000 so‘m a month on the 3rd): it renews by itself
  every year and its notice deadline is ten days away, so it waits for the owner's decision on
  Egasi paneli; it takes over Finance's existing "Ijara: Chilonzor" payment, so the rent is
  counted once and the bank transfers of the last months show as paid under it;
- the Yunusobod lease (Akmal Hasanov, 1 400 dollars a month): it ends in 45 days and isn't
  renewing, so it is "ending soon", an insight and a reminder; its rent joins the forecast,
  paid from the dollar safe;
- the supply contract with Ko‘kterak Farm Distribyutor: a framework agreement, payment 30 days
  after each delivery, renewing every year; what was paid to it shows under it;
- a cleaning service for both pharmacies (2 400 000 so‘m a month), in the forecast.

The leases carry a scan of the signed contract (a generated one-page PDF). Demo Distribyutor
rents its warehouse. Every name and number is invented.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.core.files.base import ContentFile

from apps.contracts import services
from apps.contracts.models import BusinessContract

D = Decimal


def _party(company, name: str):
    from apps.finance.models import Counterparty

    return Counterparty.objects.for_company(company).filter(name=name).first()


def _pdf(lines: list[str]) -> bytes:
    """A one-page PDF with `lines` of text (Helvetica, ASCII): the "scan" of a contract."""

    def text(value: str) -> str:
        plain = value.replace("‘", "'").replace("’", "'").encode("ascii", "replace").decode()
        return plain.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    rows = ["BT", "/F1 16 Tf", "72 770 Td", f"({text(lines[0])}) Tj", "/F1 11 Tf"]
    for line in lines[1:]:
        rows += ["0 -22 Td", f"({text(line)}) Tj"]
    rows.append("ET")
    stream = "\n".join(rows).encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    )
    return bytes(out)


def _scan(contract: BusinessContract, by, lines: list[str], *, kind="signed", label="") -> None:
    services.add_file(
        contract, by=by, file=ContentFile(_pdf(lines), name="scan.pdf"), kind=kind, label=label
    )


def _rule(company, party):
    """Finance's recurring payment to `party` (the finance demo's rent), if it has one."""
    from apps.finance.models import RecurringRule

    if party is None:
        return None
    return (
        RecurringRule.objects.for_company(company)
        .filter(counterparty=party, kind="expense", is_active=True, business_contracts__isnull=True)
        .order_by("pk")
        .first()
    )


def _day(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def seed(company, people, now) -> None:
    owner, manager = people["owner"], people["manager"]
    today = services.local_today(company)
    branches = list(company.branches.order_by("order", "pk"))
    chl = branches[0]
    yns = branches[1] if len(branches) > 1 else branches[0]
    money_on = company.has_feature("finance")

    # The Chilonzor lease: renewing every year, the notice deadline ten days away.
    landlord = _party(company, "Rustam Qodirov (ijara)")
    ends = today + timedelta(days=70)
    term = services.add_months(ends + timedelta(days=1), -12)  # the current term's first day
    started = services.add_months(term, -12)
    rent_rule = _rule(company, landlord) if money_on else None
    chilonzor = services.create_contract(
        company,
        by=owner,
        kind="lease",
        title=f"{chl.name} dorixonasi ijarasi",
        branch=chl,
        counterparty=landlord,
        counterparty_name="" if landlord else "Rustam Qodirov (ijara)",
        number="IJ-2024/07",
        signed_on=started - timedelta(days=12),
        starts_on=started,
        ends_on=ends,
        auto_renews=True,
        renewal_months=12,
        notice_days=60,
        amount=D("9000000"),
        period="monthly",
        payment_day=3,
        responsible=manager,
        in_forecast=money_on,
        money=services.RuleChoice(rule=rent_rule) if rent_rule else None,
        notes=(
            "Bino 86 kv.m, birinchi qavat. Shartnoma soliq idorasida ro‘yxatdan o‘tgan. "
            "Ijara har oy 3-sanagacha bank o‘tkazmasi bilan to‘lanadi. Ijara haqi yiliga bir "
            "marta, yangi muddat boshlanishida kelishiladi."
        ),
    )
    BusinessContract.objects.filter(pk=chilonzor.pk).update(last_renewed_on=term)
    _scan(
        chilonzor,
        owner,
        [
            "IJARA SHARTNOMASI No IJ-2024/07",
            "Toshkent shahri",
            "Ijaraga beruvchi: Rustam Qodirov",
            "Ijaraga oluvchi: Demo Dorixona MChJ",
            f"Obyekt: {chl.name} filiali, 86 kv.m, birinchi qavat",
            "Oylik ijara haqi: 9 000 000 so'm, har oyning 3-sanasigacha",
            f"Birinchi muddat: {_day(started)} - {_day(term - timedelta(days=1))}",
            "Muddat tugashidan 60 kun oldin yozma xabar berilmasa, shartnoma",
            "yana bir yilga o'z-o'zidan uzaytiriladi.",
            "",
            "Imzolar: ____________ (R. Qodirov)    ____________ (D. Karimova)",
        ],
    )
    _scan(
        chilonzor,
        owner,
        [
            "QO'SHIMCHA KELISHUV No 1",
            "IJ-2024/07 ijara shartnomasiga",
            "Ijara haqi 8 200 000 so'mdan 9 000 000 so'mga oshirildi.",
            f"Kuchga kirish sanasi: {_day(term)}",
            "",
            "Imzolar: ____________    ____________",
        ],
        kind="annex",
        label="Ijara haqi oshirilishi",
    )

    # The Yunusobod lease: ends in 45 days, not renewing; dollars.
    if yns.pk != chl.pk:
        owner_yns = _party(company, "Akmal Hasanov (ijara)")
        yns_end = today + timedelta(days=45)
        yns_start = services.add_months(yns_end + timedelta(days=1), -11)
        yunusobod = services.create_contract(
            company,
            by=owner,
            kind="lease",
            title=f"{yns.name} dorixonasi ijarasi",
            branch=yns,
            counterparty=owner_yns,
            counterparty_name="" if owner_yns else "Akmal Hasanov (ijara)",
            number="IJ-11/Y",
            signed_on=yns_start - timedelta(days=5),
            starts_on=yns_start,
            ends_on=yns_end,
            amount=D("1400"),
            currency="USD",
            period="monthly",
            payment_day=1,
            notice_days=30,
            in_forecast=money_on and _has_dollars(company),
            notes=(
                "11 oylik shartnoma (notarial tasdiqsiz). Bino egasi binoni sotmoqchi: yangi "
                "shartnoma yoki boshqa joy kerak."
            ),
        )
        _scan(
            yunusobod,
            owner,
            [
                "IJARA SHARTNOMASI No IJ-11/Y",
                "Toshkent shahri",
                "Ijaraga beruvchi: Akmal Hasanov",
                "Ijaraga oluvchi: Demo Dorixona MChJ",
                f"Obyekt: {yns.name} filiali, 64 kv.m, kunu tun ishlaydi",
                "Oylik ijara haqi: 1 400 AQSh dollari, har oyning 1-sanasigacha",
                f"Muddat: {_day(yns_start)} - {_day(yns_end)} (11 oy)",
                "",
                "Imzolar: ____________ (A. Hasanov)    ____________ (D. Karimova)",
            ],
        )

    # The distributor: a framework supply agreement, renewing every year.
    supplier = _party(company, "Ko‘kterak Farm Distribyutor")
    supply_start = date(today.year, 1, 15)
    if supply_start > today:
        supply_start = date(today.year - 1, 1, 15)
    services.create_contract(
        company,
        by=owner,
        kind="supply",
        title="Dori vositalarini yetkazib berish",
        counterparty=supplier,
        counterparty_name="" if supplier else "Ko‘kterak Farm Distribyutor",
        number="YT-118",
        signed_on=supply_start - timedelta(days=3),
        starts_on=supply_start,
        ends_on=services.add_months(supply_start, 12) - timedelta(days=1),
        auto_renews=True,
        renewal_months=12,
        notice_days=30,
        period="once",
        notes=(
            "Bosh shartnoma: har bir yetkazib berish o‘z hisob-fakturasi bilan. To‘lov "
            "yetkazilgandan keyin 30 kun ichida. Narxlar har chorakda kelishiladi; muddati "
            "6 oydan kam qolgan dorilar qabul qilinmaydi."
        ),
    )

    # Cleaning for both pharmacies, monthly, in the forecast.
    services.create_contract(
        company,
        by=owner,
        kind="service",
        title="Tozalash xizmati, ikki dorixona",
        counterparty_name="Pokiza Makon (tozalash xizmati)",
        number="TX-2026/31",
        signed_on=services.add_months(today, -4).replace(day=1) - timedelta(days=2),
        starts_on=services.add_months(today, -4).replace(day=1),
        ends_on=services.add_months(today, 8).replace(day=1) - timedelta(days=1),
        amount=D("2400000"),
        period="monthly",
        payment_day=5,
        responsible=manager,
        in_forecast=money_on,
        notes="Har kuni ertalab nam tozalash, haftada bir marta oynalar. Vositalar xizmatniki.",
    )


def _has_dollars(company) -> bool:
    from apps.finance.models import MoneyAccount

    return MoneyAccount.objects.for_company(company).filter(currency="USD", is_active=True).exists()


def seed_small(company, people, now) -> None:
    """Demo Distribyutor rents its warehouse."""
    owner = people["owner"]
    today = services.local_today(company)
    landlord = _party(company, "Sherali Rahmonov (ombor ijarasi)")
    start = services.add_months(today, -7).replace(day=1)
    services.create_contract(
        company,
        by=owner,
        kind="lease",
        title="Ombor ijarasi",
        counterparty=landlord,
        counterparty_name="" if landlord else "Sherali Rahmonov (ombor ijarasi)",
        number="OM-03",
        signed_on=start - timedelta(days=4),
        starts_on=start,
        ends_on=services.add_months(start, 24) - timedelta(days=1),
        amount=D("14000000"),
        period="monthly",
        payment_day=10,
        notice_days=60,
        notes="Ombor 420 kv.m, sovutish xonasi bilan.",
    )
