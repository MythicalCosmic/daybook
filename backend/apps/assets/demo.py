"""Demo data of fixed assets (the story is apps/core/demo_plan.py).

Demo Dorixona owns what two pharmacies need: vaccine fridges, air conditioners, shelving and
counters, tills and scanners, thermometers and hygrometers for the storage log (one check is
due in three weeks, one is overdue), cameras, the Yunusobod fit-out (made from the finance
demo's own purchase, so it leaves the P&L and comes back as depreciation), the courier's
scooter, a laptop and uniforms given to people, an old air conditioner in storage, a fridge
whose repairs approach the price of a new one, and an old fridge sold this autumn. They were
entered at the start of the year: months before are the old books, months since are in Finance.
Every name and number is invented.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.assets import posting, services
from apps.assets.models import Asset, AssetCategory, DepreciationEntry


def _months_ago(today: date, months: int, day: int = 10) -> date:
    first = posting.engine.add_months(today.replace(day=1), -months)
    return first.replace(day=min(day, posting.engine.days_in(first)))


def _backdate(asset: Asset, entered: date) -> None:
    """As if it had been entered on `entered`: its months since are kept here for real."""
    moment = timezone.make_aware(
        timezone.datetime.combine(entered, timezone.datetime.min.time()),
        posting.zone_of(asset.company),
    )
    Asset.objects.filter(pk=asset.pk).update(created_at=moment)
    DepreciationEntry.objects.filter(asset=asset, transaction__isnull=True).delete()
    asset.refresh_from_db()
    posting.post_asset(asset)


def seed(company, people, now) -> None:
    owner = people["owner"]
    today = posting.local_today(company)
    branches = list(company.branches.order_by("order", "pk"))
    first = branches[0]
    second = branches[1] if len(branches) > 1 else branches[0]
    entered = date(today.year, 1, 2)
    cats = {
        category.system_code: category
        for category in AssetCategory.objects.filter(company=company).exclude(system_code="")
    }
    if not cats:
        return
    made: list[Asset] = []

    def add(code, name, cost, months_ago, branch, **fields):
        start = _months_ago(today, months_ago)
        asset = services.create_asset(
            company,
            by=owner,
            category=cats[code],
            name=name,
            cost=Decimal(cost),
            branch=branch,
            purchased_on=start - timedelta(days=3),
            in_service_on=start,
            **fields,
        )
        made.append(asset)
        return asset

    fridge = add(
        "fridges",
        "Farmatsevtik muzlatgich Pozis-Paracels",
        "18500000",
        20,
        first,
        model="Pozis-Paracels",
        serial="PZ-24-01873",
        warranty_until=today + timedelta(days=24),
        supplier_name="«Sovutish Texnika» MChJ",
    )
    add(
        "fridges",
        "Vaksina muzlatgichi Liebherr",
        "26400000",
        8,
        second,
        model="Liebherr MKv 3910",
        serial="LH-25-33412",
        warranty_until=today + timedelta(days=500),
    )
    tired = add(
        "fridges",
        "Muzlatgich Saratov (zaxira)",
        "6200000",
        55,
        first,
        model="Saratov 263",
    )
    add("climate", "Konditsioner Artel 18", "7400000", 30, first, model="Artel ART-18HE")
    old_ac = add("climate", "Konditsioner Samsung (eski)", "5100000", 70, second)
    add(
        "furniture",
        "Savdo zali javonlari va peshtaxta",
        "34000000",
        26,
        first,
        notes="12 seksiya, 2 peshtaxta, dori vitrinasi",
    )
    laptop = add("computers", "Noutbuk Lenovo ThinkPad", "11800000", 14, first, serial="LN-PF4X21")
    add("tills", "Kassa apparati va skaner", "6900000", 11, first)
    add("tills", "Kassa apparati va skaner", "6900000", 6, second)
    add(
        "instruments",
        "Termogigrometr (savdo zali)",
        "480000",
        11,
        first,
        next_verification_on=today + timedelta(days=21),
    )
    add(
        "instruments",
        "Muzlatgich termometri",
        "260000",
        13,
        second,
        next_verification_on=today - timedelta(days=5),
    )
    add("security", "Kuzatuv kameralari (8 ta)", "9600000", 17, second)
    scooter = add(
        "vehicles",
        "Kuryer skuteri Yadea",
        "21000000",
        12,
        second,
        insurance_until=today + timedelta(days=12),
    )
    uniform = services.create_asset(
        company,
        by=owner,
        category=cats["low_value"],
        name="Farmatsevt xalati (2 dona)",
        cost=Decimal("380000"),
        branch=first,
    )

    # The fit-out of the second pharmacy, from the finance demo's own purchase when there is one.
    from apps.finance.models import Transaction

    fit_out = (
        Transaction.objects.filter(
            company=company,
            kind=Transaction.Kind.EXPENSE,
            category__is_capex=True,
            capitalized=False,
            status=Transaction.Status.POSTED,
        )
        .order_by("-base_amount")
        .last()
    )
    if fit_out is not None and company.has_feature("finance"):
        services.create_asset(
            company,
            by=owner,
            category=cats["renovation"],
            name="Ikkinchi dorixona ta’miri",
            purchase_transaction=fit_out,
            in_service_on=fit_out.occurred_on,
            life_months=60,
        )
    else:
        add("renovation", "Ikkinchi dorixona ta’miri", "48000000", 9, second, life_months=60)

    # Entered at the start of the year: months since are kept here for real, booked in one go
    # (one row a month and branch, as the nightly job books them).
    for asset in made:
        _backdate(asset, entered)
    posting.book_company(company)

    # People hold some of it.
    for asset, person, condition in (
        (laptop, people["manager"], "good"),
        (scooter, people["jasur"], "good"),
        (uniform, people["madina"], "new"),
    ):
        assignment = services.issue(
            asset, by=owner, membership=person, on=today - timedelta(days=40), condition=condition
        )
        if person is not people["jasur"]:
            services.acknowledge(assignment, by=person)

    # Upkeep and its history.
    services.record_service(fridge, by=owner, on=today - timedelta(days=150), note="Freon")
    for days, amount, note in (
        (300, "1450000", "Kompressor rele almashtirildi"),
        (160, "1900000", "Termostat"),
        (40, "2300000", "Kompressor ta’miri"),
    ):
        services.record_repair(
            tired, by=owner, on=today - timedelta(days=days), amount=Decimal(amount), note=note
        )
    services.suspend(
        old_ac, by=owner, on=today - timedelta(days=95), note="Yangi konditsioner o‘rnatildi"
    )

    # The old fridge, sold this autumn.
    sold = add("fridges", "Muzlatgich Indesit (eski)", "4300000", 80, first)
    _backdate(sold, entered)
    services.dispose(
        sold,
        by=owner,
        on=today - timedelta(days=25),
        kind=Asset.Disposal.SOLD,
        amount=Decimal("900000"),
        account=_cash(company, first),
        reason="Yangi muzlatgich olindi",
    )
    posting.book_company(company)
    _permits(company, owner, today, first, second, people)


def _permits(company, owner, today, first, second, people) -> None:
    """The papers a pharmacy keeps valid: licences, the lease (ending soon), approvals (one
    expired three days ago), the cash register's registration and insurance."""
    from apps.assets.models import Permit

    rows = (
        (
            Permit.Kind.PHARMACY_LICENCE,
            "Farmatsevtika faoliyati litsenziyasi",
            first,
            "L-2024-0412",
            800,
        ),
        (
            Permit.Kind.PHARMACY_LICENCE,
            "Farmatsevtika faoliyati litsenziyasi",
            second,
            "L-2025-1187",
            1100,
        ),
        (Permit.Kind.LEASE, "Ijara shartnomasi (Yunusobod)", second, "IJ-17", 45),
        (Permit.Kind.SANITARY, "Sanitariya-epidemiologik xulosa", first, "SE-3391", -3),
        (Permit.Kind.FIRE_SAFETY, "Yong‘in xavfsizligi xulosasi", first, "YX-882", 210),
        (
            Permit.Kind.CASH_REGISTER,
            "Kassa apparatini ro‘yxatdan o‘tkazish",
            second,
            "KA-55-019",
            330,
        ),
        (Permit.Kind.INSURANCE, "Mol-mulk sug‘urtasi", None, "SP-2026-7781", 120),
    )
    for kind, name, branch, number, days in rows:
        services.save_permit(
            company,
            by=owner,
            kind=kind,
            name=name,
            branch=branch,
            number=number,
            issuer="Sog‘liqni saqlash vazirligi" if kind == Permit.Kind.PHARMACY_LICENCE else "",
            issued_on=today - timedelta(days=365),
            valid_until=today + timedelta(days=days),
            responsible=people["manager"],
        )


def _cash(company, branch):
    if not company.has_feature("finance"):
        return None
    from apps.finance.models import MoneyAccount

    return (
        MoneyAccount.objects.filter(company=company, is_active=True, kind=MoneyAccount.Kind.CASH)
        .order_by("pk")
        .first()
    )
