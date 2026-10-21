"""Demo data of the finance ledger (docs/PLAN-OWNER.md §14.3, apps/core/demo_plan.py): two
months of Demo Dorixona's books and three weeks of the distributor's. Every company and person
in it is invented.

Demo Dorixona sells medicines in Chilonzor (about 6 mln so‘m a day) and Yunusobod (12 mln,
open around the clock). The ledger starts 62 days ago with opening balances and debts. Until the
tills' weeks begin (`demo_plan.SALES_DAYS` ago, when the sales demo runs) it books each day's
sales per pharmacy (cash into the pharmacy's till, cards and QR payments into the terminal
account), takes the cash to the safe and the safe to the bank, and settles the terminal into
the bank; from then on the sales demo books every shift itself, so no day is counted twice.
Every working day a distributor delivers medicines: on credit with its own terms (payables due
on dates the calendar shows) or paid ahead. Rent (Yunusobod's in dollars), salaries (night hours
paid 1.5 times), utilities, disinfection, the bank loan, the owner's draws, nasiya for three
regular customers and a clinic, a bad debt, a voided mistake, an entry waiting for approval and
receipts with pictures fill the rest. `finish`, once every app has booked its rows, settles the
terminal into the bank for the tills' weeks, pays the month's turnover tax and closes the books
up to the end of the month before last.

Daily sales and salaries carry the source `finance.demo` (id = branch or person, key
`s:<yymmdd>:<cash|card>` / `sal:<yyyymm>`).
"""

import io
import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.utils import translation

from apps.core import demo_plan
from apps.finance import alerts, defaults, queries, services
from apps.finance.models import (
    Category,
    Counterparty,
    ExchangeRate,
    MoneyAccount,
    RateSource,
)
from apps.finance.sources import Source

DAYS = demo_plan.LEDGER_DAYS
DEMO_SOURCE = "finance.demo"
D = Decimal
# Expected sales a day (so‘m) and the share paid in cash (the rest is cards and QR payments).
DAILY_SALES = {"C": 6_000_000, "Y": 12_000_000}
CASH_SHARE = 0.40
CARD_FEE = 0.007  # what the bank keeps of card and QR payments when it settles them
FLOAT = D("300000")  # the change a till keeps overnight
# A month's pay (so‘m): pharmacists 4.5-6.5 mln, night pharmacists 6-7.5 mln (their night hours
# at 1.5 times), heads 10-12 mln, the courier 3.5 mln.
PAY = {
    "manager": 10_500_000,
    "farrux": 10_000_000,
    "madina": 5_800_000,
    "sardor": 5_600_000,
    "malika": 5_500_000,
    "worker": 4_900_000,
    "gulnora": 4_800_000,
    "shahzoda": 4_700_000,
    "kamola": 4_500_000,
    "nigora": 7_000_000,
    "dilshod": 6_800_000,
    "jasur": 3_500_000,
    "otabek": 4_500_000,
    "aziza": 6_000_000,
    "bobur": 4_600_000,
}
NIGHT = ("nigora", "dilshod")
SMALL_PAY = {"manager": 9_000_000, "worker": 5_000_000, "cashier": 7_000_000, "driver": 4_500_000}


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    with translation.override(company.default_language):
        Ledger(company, people, now).build()


def seed_small(company, people, now) -> None:
    """The distributor's books: three weeks of invoices to pharmacies and clinics, purchases
    from manufacturers, rent and pay. `people`: owner, manager, worker and cashier."""
    with translation.override(company.default_language):
        Distributor(company, people, now).build()


def finish(company, people, now) -> None:
    """Once every app has booked its rows: settle the card terminal into the bank for the days
    the tills booked, pay the turnover tax on the sales the ledger now holds, and close the
    books up to the end of the month before last (a closed period refuses rows, and the
    projects and sales demos book older ones)."""
    if company.slug == demo_plan.DISTRIBUTOR:
        return
    with translation.override(company.default_language):
        Ledger(company, people, now).finish()
    today = queries.local_today(company, now)
    first_of_last_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    locked_until = first_of_last_month - timedelta(days=1)
    if locked_until > today - timedelta(days=DAYS):
        services.lock_period(company, by=people["owner"], until=locked_until)


def _round(value: float, step: int = 1000) -> Decimal:
    return D(round(value / step) * step)


class Ledger:
    def __init__(self, company, people, now):
        self.company = company
        self.people = people
        self.story = demo_plan.Plan(company, people, now)
        self.owner = people["owner"]
        self.manager = people["manager"]
        self.today = queries.local_today(company, now)
        self.start = self.today - timedelta(days=DAYS)
        # The sales demo books the tills' weeks; without it (another module's own test, or
        # `--only finance`) the ledger books every day's sales itself.
        self.tills_from = self.today - timedelta(days=demo_plan.SALES_DAYS)
        self.rng = random.Random(911)
        self.chl, self.yns = self.story.branches["C"], self.story.branches["Y"]

    def books_sales(self, day: date) -> bool:
        return day < self.tills_from or not self.company.has_feature("sales")

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
            "refunds": "Qaytarishlar",
            "cash_surplus": "Kassa ortiqchasi",
            "other_income": "Boshqa daromad",
            "goods": "Dori va tovar xaridi",
            "rent": "Ijara",
            "utilities": "Kommunal to‘lovlar",
            "salaries": "Ish haqi",
            "payroll_taxes": "Ish haqi soliqlari",
            "bank_fees": "Bank xizmatlari",
            "taxes": "Soliqlar va yig‘imlar",
            "marketing": "Marketing",
            "transport": "Transport va yetkazish",
            "repairs": "Ta’mirlash",
            "cash_shortage": "Kassa kamomadi",
            "bad_debts": "Umidsiz qarzlar",
            "fx_diff": "Kurs farqi",
            "other_expense": "Boshqa xarajatlar",
        }
        colors = {
            "sales": "#2e7d6b",
            "goods": "#4a6a8a",
            "rent": "#8a5a7a",
            "utilities": "#d1a040",
            "salaries": "#c67139",
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
            "corporate": child("sales", "Klinika va tashkilotlarga savdo"),
            "delivery_income": child("sales", "Yetkazib berish xizmati"),
            "medicines": child("goods", "Dori vositalari"),
            "devices": child("goods", "Tibbiy buyumlar"),
            "vitamins": child("goods", "Vitaminlar va gigiyena"),
            "electricity": child("utilities", "Elektr energiyasi"),
            "water": child("utilities", "Suv"),
            "internet": child("utilities", "Internet va aloqa"),
            "rent_chl": child("rent", f"Ijara: {self.chl.name}"),
            "rent_yns": child("rent", f"Ijara: {self.yns.name}")
            if self.yns.pk != self.chl.pk
            else None,
            "ads": child("marketing", "Ijtimoiy tarmoqlarda reklama"),
            "print": child("marketing", "Narx yorliqlari va bosma"),
            "fuel": child("transport", "Kuryer yoqilg‘isi"),
            "turnover_tax": child("taxes", "Aylanmadan olinadigan soliq"),
            "licences": child("taxes", "Litsenziya va ruxsatnomalar"),
            "salaries": code["salaries"],
            "bank_fees": code["bank_fees"],
            "repairs": code["repairs"],
            "other_income": code["other_income"],
        }
        supplies = services.create_category(
            self.company, by=by, name="Xo‘jalik xarajatlari", kind=Category.Kind.EXPENSE
        )
        self.cat["disinfection"] = services.create_category(
            self.company,
            by=by,
            name="Dezinfeksiya va tozalash",
            kind=Category.Kind.EXPENSE,
            parent=supplies,
        )
        self.cat["equipment"] = services.create_category(
            self.company,
            by=by,
            name="Uskunalar",
            kind=Category.Kind.EXPENSE,
            is_capex=True,
            color="#4a6a8a",
        )
        self.cat["interest"] = services.create_category(
            self.company, by=by, name="Kredit foizlari", kind=Category.Kind.EXPENSE, color="#a8701c"
        )

    def parties(self) -> None:
        by = self.owner

        def party(name, kind, **fields):
            return services.create_counterparty(self.company, by=by, name=name, kind=kind, **fields)

        supplier, customer, state, other = (
            Counterparty.Kind.SUPPLIER,
            Counterparty.Kind.CUSTOMER,
            Counterparty.Kind.STATE,
            Counterparty.Kind.OTHER,
        )
        medicines = self.cat["medicines"]
        self.party = {
            "kokterak": party(
                "Ko‘kterak Farm Distribyutor",
                supplier,
                phone="+998712004411",
                contact_person="Azamat Yo‘ldoshev",
                default_category=medicines,
                tags=["distribyutor", "30 kun"],
                notes="To‘lov muddati yetkazilgandan keyin 30 kun.",
            ),
            "oqtosh": party(
                "Oqtosh Med Ta’minot",
                supplier,
                phone="+998712004455",
                contact_person="Shuhrat Karimov",
                default_category=medicines,
                tags=["distribyutor", "45 kun"],
                notes="To‘lov muddati 45 kun. Antibiotiklar va gormonlar.",
            ),
            "tolzor": party(
                "Tolzor Farm Savdo",
                supplier,
                phone="+998712004477",
                default_category=self.cat["vitamins"],
                tags=["distribyutor", "14 kun"],
                notes="Vitaminlar, gigiyena va tibbiy buyumlar. To‘lov 14 kun ichida.",
            ),
            "chinorbek": party(
                "Chinorbek Pharma Logistika",
                supplier,
                phone="+998712004499",
                default_category=medicines,
                tags=["distribyutor", "oldindan to‘lov"],
                notes="Faqat oldindan to‘lov bilan yetkazadi.",
            ),
            "landlord_chl": party(
                "Rustam Qodirov (ijara)",
                other,
                phone="+998901237788",
                notes="Chilonzordagi dorixona binosi egasi. Ijara har oy 3-sanagacha, naqd.",
            ),
            "landlord_yns": party(
                "Akmal Hasanov (ijara)",
                other,
                phone="+998935557744",
                notes="Yunusoboddagi bino egasi. Ijara dollarda, har oy boshida.",
            ),
            "electric": party("Elektr ta’minoti", state),
            "water": party("Suv ta’minoti", state),
            "internet": party("Internet provayderi", supplier),
            "tax": party("Soliq inspeksiyasi", state),
            "sanitary": party(
                "Dezinfeksiya xizmati", supplier, notes="Har oy dezinfeksiya va deratizatsiya."
            ),
            "bank": party("Bank (aylanma kredit)", other),
            "clinic": party(
                "Tonggi Shabnam klinikasi",
                customer,
                phone="+998712226633",
                contact_person="Malika Ergasheva",
                credit_limit=D("15000000"),
                tags=["klinika", "nasiya"],
                address="Chilonzor, 9-mavze",
            ),
            "rahima": party("Rahima Yo‘ldosheva", customer, phone="+998901114455", tags=["nasiya"]),
            "botir": party("Botir Qosimov", customer, phone="+998998887700", tags=["nasiya"]),
            "zuhra": party("Zuhra Ahmedova", customer, phone="+998933332211", tags=["nasiya"]),
        }
        self.suppliers = ["kokterak", "oqtosh", "tolzor", "chinorbek"]
        self.terms = {"kokterak": 30, "oqtosh": 45, "tolzor": 14, "chinorbek": 0}

    def accounts(self) -> None:
        by = self.owner
        accounts = MoneyAccount.objects.filter(company=self.company)
        desk = accounts.filter(kind=MoneyAccount.Kind.CASH, branch=None).order_by("pk").first()
        clearing = accounts.filter(kind=MoneyAccount.Kind.CLEARING).order_by("pk").first()
        if clearing is None:
            clearing = services.create_account(
                self.company, by=by, kind="clearing", name="Terminal"
            )

        def create(kind, name, currency="UZS", branch=None, **extra):
            account = services.create_account(
                self.company, by=by, kind=kind, name=name, currency=currency, branch=branch
            )
            return services.update_account(account, by=by, **extra) if extra else account

        # A pharmacy's cash is its till's (the sales module makes one per branch); without the
        # sales module, the company's cash desk becomes Chilonzor's and Yunusobod gets one.
        self.till = {}
        for code, branch in (("C", self.chl), ("Y", self.yns)):
            till = accounts.filter(kind=MoneyAccount.Kind.CASH, branch=branch).order_by("pk")
            account = till.first()
            if account is None and desk is not None:
                account, desk = (
                    services.update_account(
                        desk, by=by, name=f"Kassa: {branch.name}", branch=branch
                    ),
                    None,
                )
            if account is None:
                account = create("cash", f"Kassa: {branch.name}", branch=branch)
            self.till[code] = account
            if self.yns.pk == self.chl.pk:
                self.till["Y"] = account
                break
        if desk is not None and not desk.transactions.exists():
            desk.delete()  # nothing uses the company's own cash desk: the tills hold the cash
        self.terminal = services.update_account(
            clearing, by=by, name="Terminal (karta va QR)", color="#7a8a5e", order=4
        )
        # A branch has one safe per currency, and sales' defaults may have made it already.
        self.safe = {}
        for order, (code, branch) in enumerate((("C", self.chl), ("Y", self.yns))):
            safe = services.account_for_branch(branch, currency=self.company.base_currency)
            self.safe[code] = services.update_account(
                safe, by=by, name=f"Seyf: {branch.name}", color="#8a5a7a", order=2 + order
            )
        self.bank = create(
            "bank",
            "Asosiy bank hisobi",
            number_last4="4417",
            color="#4a6a8a",
            order=0,
            # Allowed below zero only while the demo books: the tills' income arrives after the
            # expenses of the same days are booked (`finish` turns it off).
            allow_negative=True,
        )
        self.card = create("card", "Biznes karta", number_last4="8812", color="#3f8a83", order=5)
        self.dollars = create("safe", "Dollar seyf", currency="USD", color="#5f7a45", order=6)
        self.petty = services.account_for_holder(self.company, self.manager)

    def openings(self) -> None:
        day = self.start
        by = self.owner
        opening = {
            self.till["C"]: str(FLOAT),
            self.till["Y"]: str(FLOAT),  # the same till when there's one branch: booked once
            self.safe["C"]: "4500000",
            self.safe["Y"]: "7800000",
            self.bank: "168000000",
            self.card: "3500000",
            self.dollars: "3000",
            self.petty: "500000",
        }
        for account, amount in opening.items():
            services.record_transaction(
                self.company,
                by=by,
                kind="opening",
                amount=D(amount),
                occurred_on=day,
                account=account,
                description="Boshlang‘ich qoldiq",
            )
        for key, amount, due_in in (("kokterak", "38400000", 18), ("oqtosh", "52700000", 34)):
            services.open_debt(
                self.company,
                by=by,
                direction="payable",
                kind="trade",
                amount=D(amount),
                currency="UZS",
                issued_on=day,
                due_on=day + timedelta(days=due_in),
                counterparty=self.party[key],
                is_opening=True,
                description="Hisob boshlanishidagi nakladnoylar",
            )
        services.open_debt(
            self.company,
            by=by,
            direction="receivable",
            kind="trade",
            amount=D("6500000"),
            currency="UZS",
            issued_on=day,
            due_on=day + timedelta(days=15),
            counterparty=self.party["clinic"],
            branch=self.chl,
            is_opening=True,
            description="Klinikaning avvalgi nasiyasi",
        )
        self.loan = services.open_debt(
            self.company,
            by=by,
            direction="payable",
            kind="loan",
            amount=D("80000000"),
            currency="UZS",
            issued_on=day + timedelta(days=3),
            due_on=day + timedelta(days=3 + 365),
            counterparty=self.party["bank"],
            account=self.bank,
            description="Aylanma mablag‘ uchun kredit, 12 oy",
        )

    # A day of business ---------------------------------------------------------------------------

    def balance(self, account, on=None) -> Decimal:
        return queries.balance(account, on)

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

    def pharmacies(self):
        rows = [("C", self.chl)]
        if self.yns.pk != self.chl.pk:
            rows.append(("Y", self.yns))
        return rows

    def day(self, day: date, offset: int) -> None:
        rng = self.rng
        trend = 1 + offset / 500
        for code, branch in self.pharmacies():
            mean = DAILY_SALES[code] * trend * (1.06 if day.weekday() == 0 else 1.0)
            if self.books_sales(day):
                total = rng.gauss(mean, mean * 0.12)
                cash = _round(total * CASH_SHARE)
                card = _round(total * (1 - CASH_SHARE))
                for channel, account, amount in (
                    ("cash", self.till[code], cash),
                    ("card", self.terminal, card),
                ):
                    services.record_transaction(
                        self.company,
                        by=self.owner,
                        kind="income",
                        amount=amount,
                        occurred_on=day,
                        account=account,
                        category=self.cat["retail"],
                        branch=branch,
                        description=f"Kunlik savdo, {branch.name} "
                        f"({'naqd' if channel == 'cash' else 'karta va QR'})",
                        source=Source(DEMO_SOURCE, branch.pk, f"s:{day:%y%m%d}:{channel}"),
                    )
                # Every other evening (and before the tills' weeks) the cash goes to the
                # safe; the till keeps its change.
                last = day + timedelta(days=1) == self.tills_from
                left = self.balance(self.till[code]) - FLOAT
                if left > 0 and (offset % 2 == 0 or last):
                    services.transfer(
                        self.company,
                        by=self.manager,
                        from_account=self.till[code],
                        to_account=self.safe[code],
                        amount_out=left,
                        occurred_on=day,
                        description="Kunlik tushum seyfga",
                    )
            # A distributor delivers every working day: to Chilonzor on Mondays, Wednesdays
            # and Fridays, to Yunusobod on the other three.
            if day.weekday() < 6 and (day.weekday() % 2 == 0) == (code == "C"):
                self.delivery(day, offset, code, branch, mean)
        if self.books_sales(day):
            if day.weekday() == 0:
                for code, _branch in self.pharmacies():
                    banked = self.balance(self.safe[code]) - D(1_000_000)
                    if banked > D(1_000_000):
                        services.transfer(
                            self.company,
                            by=self.manager,
                            from_account=self.safe[code],
                            to_account=self.bank,
                            amount_out=_round(float(banked), 100_000),
                            occurred_on=day,
                            description="Inkassatsiya: seyfdan bankka",
                        )
            # The bank settles card and QR payments every two days, less its fee.
            if offset % 2 == 0:
                settled = self.balance(self.terminal)
                if settled > 0:
                    fee = _round(float(settled) * CARD_FEE, 100)
                    services.transfer(
                        self.company,
                        by=self.owner,
                        from_account=self.terminal,
                        to_account=self.bank,
                        amount_out=settled - fee,
                        fee=fee,
                        occurred_on=day,
                        description="Terminal tushumi (karta va QR)",
                    )
        if day.weekday() in (1, 4):
            self.petty_expense(
                day,
                _round(rng.uniform(150_000, 260_000)),
                self.cat["fuel"],
                by=self.people["jasur"],
                description="Kuryer mashinasiga benzin",
            )
        if day == self.today - timedelta(days=13):
            repair = self.petty_expense(
                day,
                "380000",
                self.cat["repairs"],
                branch=self.chl,
                by=self.manager,
                description="Termometr va gigrometrni almashtirish",
            )
            self.receipt(
                repair, "USTAXONA", [("Termometr", "180 000"), ("Gigrometr", "200 000")], "380 000"
            )
        if day == self.today - timedelta(days=6):
            supplies = self.petty_expense(
                day,
                "290000",
                self.cat["disinfection"],
                branch=self.yns,
                by=self.manager,
                description="Dezinfeksiyalovchi vositalar, salfetkalar",
            )
            self.receipt(
                supplies,
                "XO'JALIK MOLLARI",
                [("Dezinfeksiyalovchi 5 l", "160 000"), ("Salfetkalar", "130 000")],
                "290 000",
            )
        self.month_day(day)

    def petty_expense(self, day, amount, category, **fields):
        """Bekzod pays a small expense from the cash he holds, topped up from the bank first
        when it runs low."""
        if self.balance(self.petty) < D(amount) + D(200_000):
            self.refill_petty(day)
        return self.expense(day, self.petty, amount, category, **fields)

    def delivery(self, day, offset, code, branch, mean) -> None:
        """A distributor's delivery: about two days of the pharmacy's sales at cost (70 %)."""
        rng = self.rng
        key = self.suppliers[(offset + (0 if code == "C" else 1)) % len(self.suppliers)]
        category = self.party[key].default_category or self.cat["medicines"]
        amount = _round(DAILY_SALES[code] * 2.33 * 0.70 * rng.uniform(0.88, 1.12), 10_000)
        number = f"{key[:2].upper()}-{1000 + offset * 3 + (1 if code == 'Y' else 0)}"
        if self.terms[key]:
            services.open_debt(
                self.company,
                by=self.manager,
                direction="payable",
                kind="trade",
                amount=amount,
                currency="UZS",
                issued_on=day,
                due_on=day + timedelta(days=self.terms[key]),
                counterparty=self.party[key],
                category=category,
                branch=branch,
                description=f"Nakladnoy №{number}",
            )
        else:  # paid ahead from the bank
            self.expense(
                day,
                self.bank,
                amount,
                category,
                counterparty=self.party[key],
                branch=branch,
                description=f"Nakladnoy №{number} (oldindan to‘langan)",
            )

    def refill_petty(self, day) -> None:
        services.transfer(
            self.company,
            by=self.owner,
            from_account=self.bank,
            to_account=self.petty,
            amount_out=D("1000000"),
            occurred_on=day,
            description="Bekzodga mayda xarajatlar uchun naqd",
        )

    def month_day(self, day: date) -> None:
        """What happens on fixed days of the month."""
        rng = self.rng
        if day.day == 1:
            services.transfer(
                self.company,
                by=self.owner,
                from_account=self.bank,
                to_account=self.card,
                amount_out=D("2000000"),
                occurred_on=day,
                description="Biznes kartani to‘ldirish",
            )
            services.record_transaction(
                self.company,
                by=self.owner,
                kind="owner",
                amount=D("-12000000"),
                occurred_on=day,
                account=self.bank,
                description="Ta’sischi olgan mablag‘",
            )
            if self.yns.pk != self.chl.pk:
                self.expense(
                    day,
                    self.dollars,
                    "1400",
                    self.cat["rent_yns"],
                    counterparty=self.party["landlord_yns"],
                    branch=self.yns,
                    description=f"{self.yns.name} dorixonasi ijarasi, {day:%m.%Y}",
                )
        if day.day == 3:
            row = self.expense(
                day,
                self.safe["C"],
                "9000000",
                self.cat["rent_chl"],
                counterparty=self.party["landlord_chl"],
                branch=self.chl,
                description=f"{self.chl.name} dorixonasi ijarasi, {day:%m.%Y}",
            )
            self.receipt(row, "IJARA SHARTNOMASI", [("Oylik ijara", "9 000 000")], "9 000 000")
        if day.day == 5:
            self.salaries(day)
            if self.loan.status == "open":
                services.pay_debt(
                    self.loan, by=self.owner, amount=D("6700000"), paid_on=day, account=self.bank
                )
                self.expense(
                    day,
                    self.bank,
                    "1400000",
                    self.cat["interest"],
                    counterparty=self.party["bank"],
                    description="Kredit foizi",
                )
        if day.day == 10:
            for code, branch in self.pharmacies():
                electricity = self.expense(
                    day,
                    self.bank,
                    _round(rng.uniform(1_600_000, 2_100_000) * (1.4 if code == "Y" else 1)),
                    self.cat["electricity"],
                    counterparty=self.party["electric"],
                    branch=branch,
                    description=f"Elektr energiyasi, {branch.name}",
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
                    _round(rng.uniform(120_000, 190_000)),
                    self.cat["water"],
                    counterparty=self.party["water"],
                    branch=branch,
                    description=f"Suv, {branch.name}",
                )
            self.expense(
                day,
                self.card,
                "420000",
                self.cat["internet"],
                counterparty=self.party["internet"],
                description="Internet, ikki dorixona",
            )
        if day.day == 12:
            self.expense(
                day,
                self.card,
                _round(rng.uniform(900_000, 1_500_000)),
                self.cat["ads"],
                description="Ijtimoiy tarmoqlarda reklama: onlayn buyurtmalar",
            )
        if day.day == 15:
            for _code, branch in self.pharmacies():
                self.expense(
                    day,
                    self.bank,
                    "450000",
                    self.cat["disinfection"],
                    counterparty=self.party["sanitary"],
                    branch=branch,
                    description=f"Oylik dezinfeksiya, {branch.name}",
                )
        if day.day == 28:
            self.expense(day, self.bank, "85000", self.cat["bank_fees"], description="Bank xizmati")

    def salaries(self, day: date) -> None:
        """Last month's pay for everyone who worked in it (night hours at 1.5 times)."""
        month_end = day.replace(day=1) - timedelta(days=1)
        month_start = month_end.replace(day=1)
        month = month_end.strftime("%Y%m")
        for key, member in self.story.members().items():
            amount = PAY.get(key)
            if amount is None or self.story.joined(key) > month_end:
                continue
            if self.story.away(key, month_start) in ("left", "blocked"):
                continue
            note = ", tungi soatlar 1,5 baravar" if key in NIGHT else ""
            services.record_transaction(
                self.company,
                by=self.owner,
                kind="expense",
                amount=D(amount),
                occurred_on=day,
                account=self.bank,
                category=self.cat["salaries"],
                membership=member,
                branch=member.home_branch,
                description=f"Ish haqi, {member} ({month_end:%m.%Y}{note})",
                source=Source(DEMO_SOURCE, member.pk, f"sal:{month}"),
            )

    # Debts, one-offs and settings ---------------------------------------------------------------

    def debts(self) -> None:
        by = self.owner
        today = self.today

        def on_credit(party, amount, ago, due_in, category=None):
            return services.open_debt(
                self.company,
                by=by,
                direction="receivable",
                kind="trade",
                amount=D(amount),
                currency="UZS",
                issued_on=today - timedelta(days=ago),
                due_on=today + timedelta(days=due_in),
                counterparty=self.party[party],
                category=category or self.cat["corporate"],
                branch=self.chl,
                responsible=self.manager,
                description="Nasiya",
            )

        clinic = on_credit("clinic", "4200000", 26, 4)
        services.set_installments(
            clinic,
            by=by,
            rows=[
                (today - timedelta(days=11), D("1400000")),
                (today + timedelta(days=4), D("1400000")),
                (today + timedelta(days=19), D("1400000")),
            ],
        )
        services.pay_debt(
            clinic,
            by=by,
            amount=D("1400000"),
            paid_on=today - timedelta(days=11),
            account=self.bank,
        )
        on_credit("rahima", "620000", 17, -3, category=self.cat["retail"])
        botir = on_credit("botir", "380000", 16, -2, category=self.cat["retail"])
        services.pay_debt(
            botir, by=by, amount=D("180000"), paid_on=today - timedelta(days=3), account=self.bank
        )
        zuhra = on_credit("zuhra", "240000", 55, -40, category=self.cat["retail"])
        services.write_off(
            zuhra, by=by, reason="Mijoz boshqa shaharga ko‘chib ketgan, bog‘lanib bo‘lmayapti"
        )
        # Payables fall due on their terms: paid from the bank, except one Tolzor invoice that
        # is a week overdue (the head is sorting out a short delivery on it).
        overdue = None
        late_window = (today - timedelta(days=10), today - timedelta(days=4))
        for debt in queries.open_debts(self.company, direction="payable", kind="trade"):
            if debt.due_on is None or debt.due_on >= today:
                continue
            if (
                overdue is None
                and debt.counterparty_id == self.party["tolzor"].pk
                and late_window[0] <= debt.due_on <= late_window[1]
            ):
                overdue = debt
                continue
            services.pay_debt(
                debt, by=by, amount=debt.amount - debt.paid, paid_on=debt.due_on, account=self.bank
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
            account=self.bank,
            branch=self.chl,
            description="Ish haqi avansi (kartaga)",
        )

    def extras(self) -> None:
        by = self.owner
        today = self.today
        fridge = self.expense(
            today - timedelta(days=24),
            self.bank,
            "14500000",
            self.cat["equipment"],
            branch=self.yns,
            description="Yunusobod uchun ikkinchi farmatsevtik muzlatgich (+2…+8 °C)",
            by=self.manager,
        )
        self.receipt(
            fridge,
            "TIBBIY USKUNALAR DO'KONI",
            [("Farmatsevtik muzlatgich 400 l", "13 900 000"), ("Yetkazib berish", "600 000")],
            "14 500 000",
        )
        if fridge is not None:
            alerts.send_large_expense(fridge.pk)
        tags = self.expense(
            today - timedelta(days=18),
            self.card,
            "640000",
            self.cat["print"],
            description="Narx yorliqlari va «Gripp mavsumi» e’loni",
        )
        self.receipt(
            tags,
            "BOSMAXONA",
            [("Narx yorliqlari, 2000 dona", "440 000"), ("E'lon, A1", "200 000")],
            "640 000",
        )
        services.record_transaction(
            self.company,
            by=by,
            kind="expense",
            amount=D("1650000"),
            occurred_on=today - timedelta(days=20),
            account=self.bank,
            category=self.cat["licences"],
            description="GPP sertifikati: kuzatuv tashrifi to‘lovi",
        )
        # A dollar purchase: the bank's rate differs from the Central Bank's.
        quote = queries.valuation(self.company, today - timedelta(days=17)).rate or D("12100")
        services.transfer(
            self.company,
            by=by,
            from_account=self.bank,
            to_account=self.dollars,
            amount_out=_round(float(quote) * 1500 * 1.006, 1000),
            amount_in=D("1500"),
            occurred_on=today - timedelta(days=17),
            description="Ijara uchun dollar sotib olindi",
        )
        mistake = self.expense(
            today - timedelta(days=3),
            self.bank,
            "420000",
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
            by=self.people["jasur"],
            kind="expense",
            amount=D("240000"),
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
            amount=D("1800000"),
            occurred_on=today - timedelta(days=7),
            account=self.bank,
            category=self.cat["other_income"],
            counterparty=self.party["kokterak"],
            description="Ko‘kterak Farm Distribyutor: chorak rejasi bajarilgani uchun bonus",
        )

    def settings(self) -> None:
        services.update_settings(
            self.company,
            by=self.owner,
            receipt_required_over=D("3000000"),
            large_expense_alert=D("10000000"),
            approval_threshold=D("200000"),
        )

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

    # After every app's demo ----------------------------------------------------------------

    def finish(self) -> None:
        self.terminal = MoneyAccount.objects.get(
            company=self.company, kind=MoneyAccount.Kind.CLEARING, branch=None, currency="UZS"
        )
        self.bank = MoneyAccount.objects.get(company=self.company, name="Asosiy bank hisobi")
        self.cat = {
            "turnover_tax": Category.objects.get(
                company=self.company, name="Aylanmadan olinadigan soliq"
            )
        }
        self.party = {
            "tax": Counterparty.objects.get(company=self.company, name="Soliq inspeksiyasi")
        }
        # The tills' weeks: the bank settles what reached the terminal every two days (the
        # sales module booked each provider's fee with the shift).
        day = self.tills_from
        while day < self.today:
            if (day - self.tills_from).days % 2 == 1:
                settled = self.balance(self.terminal, day)
                if settled > 0:
                    services.transfer(
                        self.company,
                        by=self.owner,
                        from_account=self.terminal,
                        to_account=self.bank,
                        amount_out=settled,
                        occurred_on=day,
                        description="Terminal tushumi (karta va QR)",
                    )
            day += timedelta(days=1)
        # Turnover tax on the 20th for the month before, now that every sale is booked.
        day = self.start + timedelta(days=1)
        while day < self.today:
            if day.day == 20:
                month_end = day.replace(day=1) - timedelta(days=1)
                month_start = month_end.replace(day=1)
                income = queries.totals(self.company, month_start, month_end, branch_ids=None)[
                    "income"
                ]
                if income > 0:
                    services.record_transaction(
                        self.company,
                        by=self.owner,
                        kind="expense",
                        amount=_round(float(income) * 0.04, 1000),
                        occurred_on=day,
                        account=self.bank,
                        category=self.cat["turnover_tax"],
                        counterparty=self.party["tax"],
                        description=f"Aylanmadan olinadigan soliq, {month_start:%m.%Y}",
                    )
            day += timedelta(days=1)
        services.update_account(self.bank, by=self.owner, allow_negative=False)


class Distributor:
    """Three weeks of a small pharmaceutical distributor's books."""

    def __init__(self, company, people, now):
        self.company = company
        self.people = people
        self.story = demo_plan.Plan(company, people, now)
        self.owner = people["owner"]
        self.today = queries.local_today(company, now)
        self.start = self.today - timedelta(days=demo_plan.SMALL_DAYS + 9)
        self.rng = random.Random(912)

    def build(self) -> None:
        defaults.ensure(self.company)
        by, company, rng = self.owner, self.company, self.rng
        code = {c.system_code: c for c in Category.objects.filter(company=company)}
        services.update_category(code["sales"], by=by, name="Ulgurji savdo")
        services.update_category(code["goods"], by=by, name="Dori xaridi")
        accounts = MoneyAccount.objects.filter(company=company)
        desk = accounts.filter(kind=MoneyAccount.Kind.CASH).order_by("pk").first()
        if desk is not None:
            desk = services.update_account(desk, by=by, name="Ombor kassasi")
        else:
            desk = services.create_account(company, by=by, kind="cash", name="Ombor kassasi")
        bank = services.create_account(company, by=by, kind="bank", name="Asosiy bank hisobi")
        services.update_account(bank, by=by, number_last4="7302")

        def party(name, kind, **fields):
            return services.create_counterparty(company, by=by, name=name, kind=kind, **fields)

        buyers = [
            party("Oqqayin Dorixonasi", Counterparty.Kind.CUSTOMER, tags=["dorixona"]),
            party("Yashilbog‘ Dorixona", Counterparty.Kind.CUSTOMER, tags=["dorixona"]),
            party("Tonggi Shabnam klinikasi", Counterparty.Kind.CUSTOMER, tags=["klinika"]),
            party("Bodomgul Dorixonasi", Counterparty.Kind.CUSTOMER, tags=["dorixona"]),
        ]
        makers = [
            party(
                "Zarbuloq Farmatsevtika", Counterparty.Kind.SUPPLIER, tags=["ishlab chiqaruvchi"]
            ),
            party("Qorasuv Med Import", Counterparty.Kind.SUPPLIER, tags=["import"]),
        ]
        landlord = party("Sherali Rahmonov (ombor ijarasi)", Counterparty.Kind.OTHER)
        day = self.start
        for account, amount in ((bank, "240000000"), (desk, "5000000")):
            services.record_transaction(
                company,
                by=by,
                kind="opening",
                amount=D(amount),
                occurred_on=day,
                account=account,
                description="Boshlang‘ich qoldiq",
            )
        number = 2210
        while day < self.today:
            day += timedelta(days=1)
            if self.story.holiday(day) or day.weekday() == 6:
                continue
            # Invoices to buyers on 14 to 30 days' terms; the older ones paid when due.
            for buyer in rng.sample(buyers, 2):
                number += 1
                amount = _round(rng.uniform(9_000_000, 28_000_000), 10_000)
                debt = services.open_debt(
                    company,
                    by=self.people["cashier"],
                    direction="receivable",
                    kind="trade",
                    amount=amount,
                    currency="UZS",
                    issued_on=day,
                    due_on=day + timedelta(days=rng.choice((14, 21, 30))),
                    counterparty=buyer,
                    category=code["sales"],
                    description=f"Hisob-faktura №{number}",
                )
                if debt.due_on < self.today - timedelta(days=2) and rng.random() < 0.8:
                    services.pay_debt(debt, by=by, amount=amount, paid_on=debt.due_on, account=bank)
            if day.weekday() in (0, 3):
                maker = makers[day.toordinal() % 2]
                services.open_debt(
                    company,
                    by=self.people["manager"],
                    direction="payable",
                    kind="trade",
                    amount=_round(rng.uniform(40_000_000, 70_000_000), 100_000),
                    currency="UZS",
                    issued_on=day,
                    due_on=day + timedelta(days=30),
                    counterparty=maker,
                    category=code["goods"],
                    description="Kirim: dori partiyasi",
                )
            if day.weekday() == 1:
                services.record_transaction(
                    company,
                    by=self.people["manager"],
                    kind="expense",
                    amount=_round(rng.uniform(700_000, 1_100_000)),
                    occurred_on=day,
                    account=desk,
                    category=code["transport"],
                    description="Yetkazish mashinasiga yoqilg‘i",
                )
            if day.day == 2:
                services.record_transaction(
                    company,
                    by=by,
                    kind="expense",
                    amount=D("12000000"),
                    occurred_on=day,
                    account=bank,
                    category=code["rent"],
                    counterparty=landlord,
                    description=f"Ombor ijarasi, {day:%m.%Y}",
                )
            if day.day == 5:
                month = (day.replace(day=1) - timedelta(days=1)).strftime("%Y%m")
                for key, member in self.story.members().items():
                    amount = SMALL_PAY.get(key)
                    if amount is None:
                        continue
                    services.record_transaction(
                        company,
                        by=by,
                        kind="expense",
                        amount=D(amount),
                        occurred_on=day,
                        account=bank,
                        category=code["salaries"],
                        membership=member,
                        description=f"Ish haqi, {member}",
                        source=Source(DEMO_SOURCE, member.pk, f"sal:{month}"),
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
        "Rahmat!",
        fill=(130, 124, 116),
        font=small,
        anchor="mm",
    )
    out = io.BytesIO()
    image.save(out, "JPEG", quality=88)
    return out.getvalue()
