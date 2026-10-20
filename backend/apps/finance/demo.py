"""Demo data of the finance ledger: two months of a believable shop's books.

Demo Shop sells food and household goods in Chilonzor and Yunusobod (Tashkent). The ledger
starts 62 days ago with opening balances and opening debts, then books every day: cash and
card sales per branch, goods bought from suppliers (from the bank, in cash or on credit), rent
(Yunusobod's in dollars), utilities, salaries, turnover tax, marketing, fuel, packaging, a new
fridge, a bank loan with monthly repayments, an owner's contribution and draws, cash moved to
the safe and the bank, card settlements with the bank's fee, a dollar purchase with its
exchange difference, customers buying on credit (nasiya) with partial payments, an instalment
plan, a write-off, a voided mistake, an entry waiting for approval and receipts with pictures.
The period before last month is closed.

Sales and salaries are tagged with the source `finance.demo` (id = branch or person, key
`s:<yymmdd>:<cash|card>` / `sal:<yyyymm>`): the sales and payroll demos, which run later and
book the same things through their own sources, can void these rows for the days they cover.
"""

import io
import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.utils import translation

from apps.finance import alerts, defaults, queries, services
from apps.finance.models import Category, Counterparty, ExchangeRate, MoneyAccount, RateSource
from apps.finance.sources import Source

DAYS = 62
CHANNELS = {"cash": "naqd", "card": "karta"}
DEMO_SOURCE = "finance.demo"
D = Decimal


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    with translation.override(company.default_language):
        Ledger(company, people, now).build()


def _round(value: float, step: int = 1000) -> Decimal:
    return D(round(value / step) * step)


class Ledger:
    def __init__(self, company, people, now):
        self.company = company
        self.people = people
        self.owner = people["owner"]
        self.manager = people["manager"]
        self.today = queries.local_today(company, now)
        self.start = self.today - timedelta(days=DAYS)
        self.rng = random.Random(911)
        branches = list(company.branches.order_by("order", "pk"))
        self.chl = branches[0]
        self.yns = branches[1] if len(branches) > 1 else branches[0]

    # Setup --------------------------------------------------------------------------------

    def build(self) -> None:
        defaults.ensure(self.company)
        self.rates()
        self.categories()
        self.parties()
        self.accounts()
        self.openings()
        for offset in range(1, DAYS + 1):
            self.day(self.start + timedelta(days=offset), offset)
        self.debts()
        self.extras()
        self.settings()

    def rates(self) -> None:
        """A dollar rate for every day (the Central Bank's, as the hourly job would store)."""
        for offset in range(DAYS + 8):
            day = self.start - timedelta(days=7) + timedelta(days=offset)
            wobble = (offset * 37 % 11 - 5) * 1.7
            rate = D(str(round(12_068 + offset * 1.55 + wobble, 2)))
            ExchangeRate.objects.get_or_create(
                currency="USD", date=day, source=RateSource.CBU, defaults={"rate": rate}
            )

    def categories(self) -> None:
        by = self.owner
        code = {
            c.system_code: c
            for c in Category.objects.filter(company=self.company).exclude(system_code="")
        }
        names = {
            "sales": "Savdo",
            "refunds": "Qaytarilgan tovarlar",
            "cash_surplus": "Kassa ortiqchasi",
            "other_income": "Boshqa daromad",
            "goods": "Tovar xaridi",
            "rent": "Ijara",
            "utilities": "Kommunal to‘lovlar",
            "salaries": "Ish haqi",
            "payroll_taxes": "Ish haqi soliqlari",
            "bank_fees": "Bank xizmatlari",
            "taxes": "Soliqlar",
            "marketing": "Marketing",
            "transport": "Transport va yetkazish",
            "repairs": "Ta’mirlash",
            "cash_shortage": "Kassa kamomadi",
            "bad_debts": "Umidsiz qarzlar",
            "fx_diff": "Kurs farqi",
            "other_expense": "Boshqa xarajatlar",
        }
        colors = {
            "sales": "#5f7a45",
            "goods": "#c67139",
            "rent": "#4a6a8a",
            "utilities": "#d1a040",
            "salaries": "#8a5a7a",
            "taxes": "#a66a4f",
            "marketing": "#3f8a83",
            "transport": "#7a8a5e",
        }
        for system_code, name in names.items():
            category = code.get(system_code)
            if category is not None and category.name != name:
                services.update_category(
                    category, by=by, name=name, color=colors.get(system_code, category.color)
                )
        code = {
            c.system_code: c
            for c in Category.objects.filter(company=self.company).exclude(system_code="")
        }

        def child(parent_code, name, **extra):
            return services.create_category(
                self.company,
                by=by,
                name=name,
                kind=code[parent_code].kind,
                parent=code[parent_code],
                **extra,
            )

        self.cat = {
            "retail": child("sales", "Chakana savdo"),
            "wholesale": child("sales", "Ulgurji savdo"),
            "delivery_income": child("sales", "Yetkazib berish xizmati"),
            "drinks": child("goods", "Ichimliklar"),
            "groceries": child("goods", "Oziq-ovqat"),
            "chemicals": child("goods", "Maishiy kimyo"),
            "bread": child("goods", "Non mahsulotlari"),
            "electricity": child("utilities", "Elektr energiyasi"),
            "gas": child("utilities", "Gaz"),
            "water": child("utilities", "Suv"),
            "internet": child("utilities", "Internet va aloqa"),
            "rent_chl": child("rent", f"Ijara — {self.chl.name}"),
            "rent_yns": child("rent", f"Ijara — {self.yns.name}")
            if self.yns.pk != self.chl.pk
            else None,
            "instagram": child("marketing", "Instagram reklama"),
            "banners": child("marketing", "Banner va bosma"),
            "fuel": child("transport", "Yoqilg‘i"),
            "turnover_tax": child("taxes", "Aylanmadan soliq"),
            "salaries": code["salaries"],
            "bank_fees": code["bank_fees"],
            "repairs": code["repairs"],
            "other_income": code["other_income"],
            "cash_surplus": code["cash_surplus"],
            "cash_shortage": code["cash_shortage"],
        }
        supplies = services.create_category(
            self.company,
            by=by,
            name="Xo‘jalik mollari",
            kind=Category.Kind.EXPENSE,
            color="#8c857a",
        )
        self.cat["packaging"] = services.create_category(
            self.company, by=by, name="Paket va qadoq", kind=Category.Kind.EXPENSE, parent=supplies
        )
        self.cat["cleaning"] = services.create_category(
            self.company,
            by=by,
            name="Tozalash vositalari",
            kind=Category.Kind.EXPENSE,
            parent=supplies,
        )
        equipment = services.create_category(
            self.company,
            by=by,
            name="Uskunalar",
            kind=Category.Kind.EXPENSE,
            is_capex=True,
            color="#4a6a8a",
        )
        self.cat["equipment"] = equipment
        self.cat["interest"] = services.create_category(
            self.company, by=by, name="Kredit foizlari", kind=Category.Kind.EXPENSE, color="#a8701c"
        )

    def parties(self) -> None:
        by = self.owner

        def party(name, kind, **fields):
            return services.create_counterparty(self.company, by=by, name=name, kind=kind, **fields)

        supplier, customer, state = (
            Counterparty.Kind.SUPPLIER,
            Counterparty.Kind.CUSTOMER,
            Counterparty.Kind.STATE,
        )
        self.party = {
            "cola": party(
                "Coca-Cola Ichimligi O‘zbekiston",
                supplier,
                tin="200857142",
                phone="+998712007700",
                contact_person="Azamat Yo‘ldoshev",
                default_category=self.cat["drinks"],
                tags=["ichimlik", "har hafta"],
            ),
            "agromir": party(
                "Agromir Savdo MChJ",
                supplier,
                tin="305112874",
                phone="+998909871122",
                contact_person="Shuhrat Karimov",
                default_category=self.cat["groceries"],
                address="Sergeli, Yangi Sergeli 14",
            ),
            "bread": party(
                "Toshkent Non Kombinati",
                supplier,
                tin="201447905",
                phone="+998712345090",
                default_category=self.cat["bread"],
            ),
            "musaffo": party(
                "Musaffo Kimyo MChJ",
                supplier,
                tin="306998121",
                phone="+998935556677",
                default_category=self.cat["chemicals"],
            ),
            "landlord_chl": party(
                "Rustam Qodirov (ijara)",
                Counterparty.Kind.OTHER,
                phone="+998901237788",
                notes="Chilonzor do‘koni egasi. Ijara har oy 5-sanagacha naqd.",
            ),
            "landlord_yns": party(
                "Yunusobod Savdo Markazi MChJ",
                supplier,
                tin="302556190",
                notes="Ijara dollarda, har oy boshida.",
            ),
            "electric": party("Hududiy elektr tarmoqlari", state, tin="200011201"),
            "gas": party("Hududgaz ta’minot", state, tin="200011318"),
            "internet": party("Uzonline", supplier, tin="203660021", phone="+998712000505"),
            "tax": party("Davlat soliq qo‘mitasi", state, tin="200100100"),
            "bank": party(
                "Kapitalbank", Counterparty.Kind.OTHER, tin="200531224", phone="+998781500000"
            ),
            "barakat": party(
                "Barakat Kafe",
                customer,
                phone="+998977001234",
                contact_person="Odil aka",
                credit_limit=D("15000000"),
                tags=["ulgurji", "nasiya"],
                address="Chilonzor 9-kvartal",
            ),
            "sardor": party("Sardor Rahimov", customer, phone="+998901114455", tags=["nasiya"]),
            "gulnora": party("Gulnora Yusupova", customer, phone="+998998887766", tags=["nasiya"]),
            "ofis": party(
                "Ofis Plyus MChJ",
                customer,
                tin="307441029",
                phone="+998712223344",
                contact_person="Malika Ergasheva",
                tags=["korporativ"],
            ),
            "bogcha": party("Mehribon bog‘chasi", customer, phone="+998951239900"),
            "javlon": party("Javlon Nurmatov", customer, phone="+998933332211"),
            "samarqand": party(
                "Samarqand Delivery", customer, phone="+998662334455", notes="Dollarda hisob-kitob."
            ),
        }

    def accounts(self) -> None:
        by = self.owner
        cash = MoneyAccount.objects.filter(
            company=self.company, kind=MoneyAccount.Kind.CASH
        ).first()
        clearing = MoneyAccount.objects.filter(
            company=self.company, kind=MoneyAccount.Kind.CLEARING
        ).first()
        if cash is None:
            cash = services.create_account(self.company, by=by, kind="cash", name="Kassa")
        if clearing is None:
            clearing = services.create_account(
                self.company, by=by, kind="clearing", name="Terminal"
            )

        def create(kind, name, currency="UZS", branch=None, **extra):
            account = services.create_account(
                self.company, by=by, kind=kind, name=name, currency=currency, branch=branch
            )
            return services.update_account(account, by=by, **extra) if extra else account

        self.kassa_chl = services.update_account(
            cash,
            by=by,
            name=f"Kassa — {self.chl.name}",
            branch=self.chl,
            color="#c67139",
            order=0,
            operators=[self.people["madina"], self.manager],
        )
        self.terminal = services.update_account(
            clearing, by=by, name="Terminal (Uzcard, Humo)", color="#7a8a5e", order=4
        )
        self.kassa_yns = (
            create(
                "cash",
                f"Kassa — {self.yns.name}",
                branch=self.yns,
                color="#d1a040",
                order=1,
                operators=[self.people["jasur"]],
            )
            if self.yns.pk != self.chl.pk
            else self.kassa_chl
        )
        self.safe = create(
            "safe", f"Seyf — {self.chl.name}", branch=self.chl, color="#8a5a7a", order=2
        )
        self.bank = create(
            "bank",
            "Kapitalbank hisob raqami",
            bank_name="Kapitalbank",
            number_last4="4417",
            color="#4a6a8a",
            order=3,
        )
        self.card = create(
            "card",
            "Humo biznes karta",
            bank_name="Kapitalbank",
            number_last4="8812",
            color="#3f8a83",
            order=5,
        )
        self.wallet = create("wallet", "Payme / Click", color="#a66a4f", order=6)
        self.dollars = create("safe", "Dollar seyf", currency="USD", color="#5f7a45", order=7)
        self.petty = services.account_for_holder(self.company, self.manager)

    def openings(self) -> None:
        day = self.start
        by = self.owner
        for account, amount in (
            (self.kassa_chl, "6200000"),
            (self.kassa_yns, "4100000"),
            (self.safe, "38500000"),
            (self.bank, "214750000"),
            (self.card, "12300000"),
            (self.wallet, "3450000"),
            (self.dollars, "8500"),
            (self.petty, "500000"),
        ):
            services.record_transaction(
                self.company,
                by=by,
                kind="opening",
                amount=D(amount),
                occurred_on=day,
                account=account,
                description="Boshlang‘ich qoldiq",
            )
        services.open_debt(
            self.company,
            by=by,
            direction="receivable",
            kind="trade",
            amount=D("4800000"),
            currency="UZS",
            issued_on=day,
            due_on=day + timedelta(days=20),
            counterparty=self.party["barakat"],
            branch=self.chl,
            is_opening=True,
            description="Avvalgi daftardan nasiya",
        )
        self.agromir_opening = services.open_debt(
            self.company,
            by=by,
            direction="payable",
            kind="trade",
            amount=D("11200000"),
            currency="UZS",
            issued_on=day,
            due_on=day + timedelta(days=25),
            counterparty=self.party["agromir"],
            is_opening=True,
            description="Ochilish kunidagi qarz",
        )
        self.loan = services.open_debt(
            self.company,
            by=by,
            direction="payable",
            kind="loan",
            amount=D("60000000"),
            currency="UZS",
            issued_on=day + timedelta(days=3),
            due_on=day + timedelta(days=3 + 365),
            counterparty=self.party["bank"],
            account=self.bank,
            description="Aylanma mablag‘ uchun kredit, 12 oy",
        )
        services.record_transaction(
            self.company,
            by=by,
            kind="owner",
            amount=D("50000000"),
            occurred_on=day + timedelta(days=10),
            account=self.bank,
            description="Ta’sischi qo‘shimcha mablag‘ kiritdi",
        )

    # A day of business ---------------------------------------------------------------------------

    def balance(self, account) -> Decimal:
        return queries.balance(account)

    def expense(self, day, account, amount, category, *, by=None, **fields):
        amount = D(amount)
        if self.balance(account) < amount and not account.allow_negative:
            return None
        return services.record_transaction(
            self.company,
            by=by or self.owner,
            kind="expense",
            amount=amount,
            occurred_on=day,
            account=account,
            category=category,
            **fields,
        )

    def day(self, day: date, offset: int) -> None:
        rng = self.rng
        weekend = day.weekday() >= 5
        lift = 1.15 if weekend else 1.0
        trend = 1 + offset / 400
        branches = [(self.chl, self.kassa_chl, 8_200_000, 6_100_000)]
        if self.yns.pk != self.chl.pk:
            branches.append((self.yns, self.kassa_yns, 6_000_000, 4_900_000))
        for branch, kassa, cash_mean, card_mean in branches:
            for channel, account, mean in (
                ("cash", kassa, cash_mean),
                ("card", self.terminal, card_mean),
            ):
                amount = _round(rng.gauss(mean, mean * 0.16) * lift * trend)
                services.record_transaction(
                    self.company,
                    by=self.people["madina"] if branch.pk == self.chl.pk else self.people["jasur"],
                    kind="income",
                    amount=amount,
                    occurred_on=day,
                    account=account,
                    category=self.cat["retail"],
                    branch=branch,
                    description=f"Kunlik savdo, {branch.name} ({CHANNELS[channel]})",
                    source=Source(DEMO_SOURCE, branch.pk, f"s:{day:%y%m%d}:{channel}"),
                )
            # Goods: most days a delivery from a supplier.
            if rng.random() < 0.72:
                supplier, category = rng.choice(
                    [
                        (self.party["cola"], self.cat["drinks"]),
                        (self.party["agromir"], self.cat["groceries"]),
                        (self.party["agromir"], self.cat["groceries"]),
                        (self.party["musaffo"], self.cat["chemicals"]),
                    ]
                )
                amount = _round(rng.uniform(9_000_000, 19_000_000) * trend, 10_000)
                if rng.random() < 0.22:
                    services.open_debt(
                        self.company,
                        by=self.manager,
                        direction="payable",
                        kind="trade",
                        amount=amount,
                        currency="UZS",
                        issued_on=day,
                        due_on=day + timedelta(days=14),
                        counterparty=supplier,
                        category=category,
                        branch=branch,
                        description=f"Nakladnaya №{1000 + offset * 3 + branch.pk}",
                    )
                else:
                    self.expense(
                        day,
                        self.bank,
                        amount,
                        category,
                        counterparty=supplier,
                        branch=branch,
                        description=f"Tovar: nakladnaya №{1000 + offset * 3 + branch.pk}",
                    )
            # Bread every morning, in cash.
            self.expense(
                day,
                kassa,
                _round(rng.uniform(380_000, 620_000)),
                self.cat["bread"],
                counterparty=self.party["bread"],
                branch=branch,
                by=self.manager,
                description="Non va bulochkalar",
            )
            # Cash to the safe (Chilonzor) or to the bank (the other branch) every few days.
            if offset % 3 == 0:
                keep = D("2000000")
                excess = self.balance(kassa) - keep
                if excess > 1_000_000:
                    target = self.safe if branch.pk == self.chl.pk else self.bank
                    services.transfer(
                        self.company,
                        by=self.manager,
                        from_account=kassa,
                        to_account=target,
                        amount_out=_round(float(excess), 100_000),
                        occurred_on=day,
                        description="Inkassatsiya" if target == self.bank else "Kassadan seyfga",
                    )
        # Card settlements reach the bank every two days, minus the bank's 1% fee.
        if offset % 2 == 0:
            settled = self.balance(self.terminal)
            if settled > 0:
                fee = _round(float(settled) * 0.01, 100)
                services.transfer(
                    self.company,
                    by=self.owner,
                    from_account=self.terminal,
                    to_account=self.bank,
                    amount_out=settled - fee,
                    fee=fee,
                    occurred_on=day,
                    description="Terminal tushumi (Uzcard, Humo)",
                )
        # The safe goes to the bank once a week.
        if day.weekday() == 0 and self.balance(self.safe) > 30_000_000:
            services.transfer(
                self.company,
                by=self.manager,
                from_account=self.safe,
                to_account=self.bank,
                amount_out=_round(float(self.balance(self.safe)) - 10_000_000, 1_000_000),
                occurred_on=day,
                description="Seyfdan bankka topshirildi",
            )
        if day.weekday() in (1, 4):
            self.expense(
                day,
                self.petty,
                _round(rng.uniform(280_000, 520_000)),
                self.cat["fuel"],
                by=self.people["nigora"],
                description="Yetkazib berish mashinasiga benzin",
            ) or self.refill_petty(day)
        if day.weekday() == 2:
            self.expense(
                day,
                self.kassa_chl,
                _round(rng.uniform(240_000, 410_000)),
                self.cat["packaging"],
                by=self.manager,
                branch=self.chl,
                description="Paketlar va qadoq",
            )
        if day.weekday() == 5 and rng.random() < 0.6:
            services.record_transaction(
                self.company,
                by=self.owner,
                kind="income",
                amount=_round(rng.uniform(180_000, 420_000)),
                occurred_on=day,
                account=self.wallet,
                category=self.cat["delivery_income"],
                description="Yetkazib berish to‘lovlari (Payme)",
            )
        self.month_day(day)

    def refill_petty(self, day) -> None:
        services.transfer(
            self.company,
            by=self.owner,
            from_account=self.safe,
            to_account=self.petty,
            amount_out=D("1500000"),
            occurred_on=day,
            description="Bekzodga xarajatlar uchun naqd",
        )

    def month_day(self, day: date) -> None:
        """What happens on fixed days of the month."""
        rng = self.rng
        if day.day == 1:
            services.record_transaction(
                self.company,
                by=self.owner,
                kind="owner",
                amount=D("-15000000"),
                occurred_on=day,
                account=self.bank,
                description="Ta’sischi oylik olgan mablag‘i",
            )
            if self.yns.pk != self.chl.pk:
                self.expense(
                    day,
                    self.dollars,
                    "1200",
                    self.cat["rent_yns"],
                    counterparty=self.party["landlord_yns"],
                    branch=self.yns,
                    description=f"{self.yns.name} do‘koni ijarasi, {day:%m.%Y}",
                )
        if day.day == 3:
            row = self.expense(
                day,
                self.safe,
                "14000000",
                self.cat["rent_chl"],
                counterparty=self.party["landlord_chl"],
                branch=self.chl,
                description=f"{self.chl.name} do‘koni ijarasi, {day:%m.%Y}",
            )
            self.receipt(row, "IJARA SHARTNOMASI", [("Oylik ijara", "14 000 000")], "14 000 000")
        if day.day == 5:
            for key, amount in (
                ("manager", "7200000"),
                ("worker", "4300000"),
                ("madina", "4600000"),
                ("jasur", "4100000"),
                ("nigora", "3900000"),
            ):
                person = self.people[key]
                month = (day.replace(day=1) - timedelta(days=1)).strftime("%Y%m")
                services.record_transaction(
                    self.company,
                    by=self.owner,
                    kind="expense",
                    amount=D(amount),
                    occurred_on=day,
                    account=self.bank,
                    category=self.cat["salaries"],
                    membership=person,
                    branch=person.home_branch,
                    description=f"Ish haqi, {person}",
                    source=Source(DEMO_SOURCE, person.pk, f"sal:{month}"),
                )
            if self.loan.status == "open":
                services.pay_debt(
                    self.loan, by=self.owner, amount=D("5000000"), paid_on=day, account=self.bank
                )
                self.expense(
                    day,
                    self.bank,
                    "1100000",
                    self.cat["interest"],
                    counterparty=self.party["bank"],
                    description="Kredit foizi",
                )
        if day.day == 10:
            for branch, account in ((self.chl, self.kassa_chl), (self.yns, self.kassa_yns)):
                electricity = self.expense(
                    day,
                    self.bank,
                    _round(rng.uniform(1_900_000, 2_700_000)),
                    self.cat["electricity"],
                    counterparty=self.party["electric"],
                    branch=branch,
                    description=f"Elektr, {branch.name}",
                )
                self.receipt(
                    electricity,
                    "ELEKTR ENERGIYASI",
                    [("Hisoblagich", "kVt"), ("To'lov", f"{branch.name}")],
                    "",
                )
                self.expense(
                    day,
                    self.bank,
                    _round(rng.uniform(520_000, 760_000)),
                    self.cat["gas"],
                    counterparty=self.party["gas"],
                    branch=branch,
                    description=f"Gaz, {branch.name}",
                )
                self.expense(
                    day,
                    account,
                    _round(rng.uniform(150_000, 230_000)),
                    self.cat["water"],
                    branch=branch,
                    description=f"Suv, {branch.name}",
                )
                if self.yns.pk == self.chl.pk:
                    break
            self.expense(
                day,
                self.card,
                "450000",
                self.cat["internet"],
                counterparty=self.party["internet"],
                description="Internet, ikki do‘kon",
            )
        if day.day == 12:
            self.expense(
                day,
                self.card,
                _round(rng.uniform(1_400_000, 2_200_000)),
                self.cat["instagram"],
                description="Instagram reklama (aksiya)",
            )
        if day.day == 20:
            month_start = day.replace(day=1) - timedelta(days=1)
            month_start = month_start.replace(day=1)
            sales = queries.totals(
                self.company, month_start, day.replace(day=1) - timedelta(days=1), branch_ids=None
            )["income"]
            if sales > 0:
                self.expense(
                    day,
                    self.bank,
                    _round(float(sales) * 0.04, 1000),
                    self.cat["turnover_tax"],
                    counterparty=self.party["tax"],
                    description=f"Aylanmadan soliq, {month_start:%m.%Y}",
                )
        if day.day == 28:
            self.expense(day, self.bank, "85000", self.cat["bank_fees"], description="Bank xizmati")

    # Debts, one-offs and settings ---------------------------------------------------------------

    def debts(self) -> None:
        by = self.owner
        today = self.today

        def sold_on_credit(party, amount, ago, due_in, *, currency="UZS", category=None):
            return services.open_debt(
                self.company,
                by=by,
                direction="receivable",
                kind="trade",
                amount=D(amount),
                currency=currency,
                issued_on=today - timedelta(days=ago),
                due_on=today + timedelta(days=due_in),
                counterparty=self.party[party],
                category=category or self.cat["wholesale"],
                branch=self.chl,
                responsible=self.manager,
                description="Ulgurji, nasiyaga",
            )

        barakat = sold_on_credit("barakat", "9600000", 30, 15)
        services.set_installments(
            barakat,
            by=by,
            rows=[
                (today - timedelta(days=10), D("3200000")),
                (today + timedelta(days=5), D("3200000")),
                (today + timedelta(days=15), D("3200000")),
            ],
        )
        services.pay_debt(
            barakat,
            by=by,
            amount=D("3200000"),
            paid_on=today - timedelta(days=11),
            account=self.kassa_chl,
        )
        services.pay_debt(
            barakat,
            by=by,
            amount=D("1500000"),
            paid_on=today - timedelta(days=2),
            account=self.kassa_chl,
        )
        older = sold_on_credit("barakat", "2350000", 26, -12)
        services.pay_debt(
            older,
            by=by,
            amount=D("850000"),
            paid_on=today - timedelta(days=15),
            account=self.kassa_chl,
        )
        sold_on_credit("sardor", "1250000", 19, -5, category=self.cat["retail"])
        sold_on_credit("gulnora", "780000", 9, 3, category=self.cat["retail"])
        sold_on_credit("ofis", "6400000", 12, 6)
        bogcha = sold_on_credit("bogcha", "2900000", 40, -20)
        services.pay_debt(
            bogcha,
            by=by,
            amount=D("2900000"),
            paid_on=today - timedelta(days=21),
            account=self.bank,
        )
        javlon = sold_on_credit("javlon", "150000", 55, -40, category=self.cat["retail"])
        services.write_off(
            javlon, by=by, reason="Mijoz boshqa shaharga ko‘chib ketdi, bog‘lanib bo‘lmayapti"
        )
        samarqand = sold_on_credit("samarqand", "650", 16, 9, currency="USD")
        services.pay_debt(
            samarqand,
            by=by,
            amount=D("250"),
            paid_on=today - timedelta(days=4),
            account=self.dollars,
        )

        def bought_on_credit(party, amount, ago, due_in, category):
            return services.open_debt(
                self.company,
                by=self.manager,
                direction="payable",
                kind="trade",
                amount=D(amount),
                currency="UZS",
                issued_on=today - timedelta(days=ago),
                due_on=today + timedelta(days=due_in),
                counterparty=self.party[party],
                category=category,
                branch=self.yns,
                description="Tovar nasiyaga olindi",
            )

        bought_on_credit("cola", "18600000", 10, 4, self.cat["drinks"])
        overdue = bought_on_credit("musaffo", "3100000", 22, -8, self.cat["chemicals"])
        bought_on_credit("bread", "2200000", 6, 1, self.cat["bread"])
        services.pay_debt(
            self.agromir_opening,
            by=by,
            amount=D("6000000"),
            paid_on=self.start + timedelta(days=12),
            account=self.bank,
        )
        # Older payables bought on credit during the window get paid when they fall due.
        for debt in queries.open_debts(self.company, direction="payable", kind="trade"):
            if debt.due_on and debt.due_on < today - timedelta(days=1) and debt.pk != overdue.pk:
                left = debt.amount - debt.paid
                if self.balance(self.bank) > left:
                    services.pay_debt(
                        debt, by=by, amount=left, paid_on=debt.due_on, account=self.bank
                    )
        services.open_debt(
            self.company,
            by=self.owner,
            direction="receivable",
            kind="advance",
            amount=D("1000000"),
            currency="UZS",
            issued_on=today - timedelta(days=8),
            membership=self.people["worker"],
            account=self.kassa_chl,
            branch=self.chl,
            description="Ish haqi avansi",
        )

    def extras(self) -> None:
        by = self.owner
        today = self.today
        fridge = self.expense(
            today - timedelta(days=24),
            self.bank,
            "18500000",
            self.cat["equipment"],
            branch=self.yns,
            description="Ichimliklar uchun yangi muzlatgich (Artel)",
            by=self.manager,
        )
        self.receipt(
            fridge,
            "ARTEL BRAND STORE",
            [("Muzlatgich Artel HS-430", "17 900 000"), ("Yetkazib berish", "600 000")],
            "18 500 000",
        )
        if fridge is not None:
            alerts.send_large_expense(fridge.pk)
        repair = self.expense(
            today - timedelta(days=13),
            self.kassa_chl,
            "2400000",
            self.cat["repairs"],
            branch=self.chl,
            by=self.manager,
            description="Sovutkich kompressorini ta’mirlash",
        )
        self.receipt(
            repair,
            "SOVUQ SERVIS",
            [("Kompressor ta'miri", "1 800 000"), ("Freon", "600 000")],
            "2 400 000",
        )
        clean = self.expense(
            today - timedelta(days=6),
            self.kassa_yns,
            "365000",
            self.cat["cleaning"],
            branch=self.yns,
            by=self.people["jasur"],
            description="Pol yuvish vositalari, latta",
        )
        self.receipt(
            clean,
            "KORZINKA",
            [("Fairy 1L", "38 000"), ("Domestos", "45 000"), ("Latta x10", "120 000")],
            "365 000",
        )
        banners = self.expense(
            today - timedelta(days=18),
            self.card,
            "1750000",
            self.cat["banners"],
            description="Vitrina uchun banner",
        )
        self.receipt(
            banners,
            "PRINT CITY",
            [("Banner 3x1 m", "1 250 000"), ("O'rnatish", "500 000")],
            "1 750 000",
        )
        # A dollar purchase: the bank's rate differs from the Central Bank's.
        quote = queries.valuation(self.company, today - timedelta(days=17)).rate or D("12100")
        services.transfer(
            self.company,
            by=by,
            from_account=self.bank,
            to_account=self.dollars,
            amount_out=_round(float(quote) * 2000 * 1.006, 1000),
            amount_in=D("2000"),
            occurred_on=today - timedelta(days=17),
            description="Ijara uchun dollar sotib olindi",
        )
        services.record_transaction(
            self.company,
            by=self.manager,
            kind="income",
            amount=D("64000"),
            occurred_on=today - timedelta(days=9),
            account=self.kassa_chl,
            category=self.cat["cash_surplus"],
            branch=self.chl,
            description="Smena oxirida kassa ortiqchasi",
        )
        services.record_transaction(
            self.company,
            by=self.manager,
            kind="expense",
            amount=D("42000"),
            occurred_on=today - timedelta(days=4),
            account=self.kassa_yns,
            category=self.cat["cash_shortage"],
            branch=self.yns,
            description="Kassa kamomadi, smena №47",
        )
        mistake = self.expense(
            today - timedelta(days=3),
            self.bank,
            "1100000",
            self.cat["internet"],
            counterparty=self.party["internet"],
            description="Internet (ikki marta kiritilgan)",
        )
        if mistake is not None:
            services.void_transaction(
                mistake, by=by, reason="Ikki marta kiritilgan, oyning 10-sanasida to‘langan"
            )
        services.record_transaction(
            self.company,
            by=self.people["nigora"],
            kind="expense",
            amount=D("450000"),
            occurred_on=today - timedelta(days=1),
            account=self.petty,
            category=self.cat["fuel"],
            description="Benzin, chek bilan (tasdiqlash kutilmoqda)",
            status="pending",
        )
        services.record_transaction(
            self.company,
            by=self.owner,
            kind="income",
            amount=D("2400000"),
            occurred_on=today - timedelta(days=7),
            account=self.bank,
            category=self.cat["other_income"],
            counterparty=self.party["cola"],
            description="Coca-Cola bonus: reja bajarilgani uchun",
        )

    def settings(self) -> None:
        by = self.owner
        services.update_settings(
            self.company,
            by=by,
            receipt_required_over=D("5000000"),
            large_expense_alert=D("10000000"),
            approval_threshold=D("500000"),
        )
        first_of_last_month = (self.today.replace(day=1) - timedelta(days=1)).replace(day=1)
        locked_until = first_of_last_month - timedelta(days=1)
        if locked_until > self.start:
            services.lock_period(self.company, by=by, until=locked_until)

    def receipt(self, row, shop: str, lines: list[tuple[str, str]], total: str) -> None:
        if row is None:
            return
        services.upload_receipt(
            self.company,
            by=self.owner,
            file=ContentFile(
                _receipt_picture(shop, row.occurred_on, lines, total), name="receipt.jpg"
            ),
            txn=row,
        )


def _receipt_picture(shop: str, day: date, lines: list[tuple[str, str]], total: str) -> bytes:
    """A paper till receipt drawn with Pillow, so receipt thumbnails look like the real thing."""
    from PIL import Image, ImageDraw, ImageFont

    width, height = 520, 300 + 46 * len(lines)
    image = Image.new("RGB", (width, height), (252, 250, 245))
    draw = ImageDraw.Draw(image)
    title = ImageFont.load_default(size=30)
    body = ImageFont.load_default(size=22)
    small = ImageFont.load_default(size=18)
    draw.text((width / 2, 40), shop, fill=(30, 28, 26), font=title, anchor="mm")
    draw.text((width / 2, 78), "Toshkent sh.", fill=(110, 104, 96), font=small, anchor="mm")
    draw.text(
        (width / 2, 104),
        day.strftime("%d.%m.%Y  10:%M"),
        fill=(110, 104, 96),
        font=small,
        anchor="mm",
    )
    y = 140
    draw.line((30, y, width - 30, y), fill=(200, 194, 186), width=2)
    y += 22
    for name, amount in lines:
        draw.text((34, y), name, fill=(40, 38, 36), font=body)
        draw.text((width - 34, y), amount, fill=(40, 38, 36), font=body, anchor="ra")
        y += 46
    draw.line((30, y, width - 30, y), fill=(200, 194, 186), width=2)
    y += 26
    if total:
        draw.text((34, y), "JAMI", fill=(20, 18, 16), font=title)
        draw.text((width - 34, y), total, fill=(20, 18, 16), font=title, anchor="ra")
    draw.text(
        (width / 2, height - 36),
        "Xaridingiz uchun rahmat!",
        fill=(130, 124, 116),
        font=small,
        anchor="mm",
    )
    out = io.BytesIO()
    image.save(out, "JPEG", quality=88)
    return out.getvalue()
