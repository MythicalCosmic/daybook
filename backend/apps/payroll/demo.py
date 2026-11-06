"""Demo data of payroll (docs/PLAN-OWNER.md §14.3, §14.11, apps/core/demo_plan.py).

Demo Dorixona pays everyone the monthly salary of the finance demo's pay table (pharmacists
4.5 to 6.5 mln so‘m, heads 10 to 10.5 mln, the courier 3.5 mln); its night pharmacists at
Yunusobod earn the night premium on top from their 20:00 to 08:00 shifts, so their month comes
to 6 to 7.5 mln. Alisher got a raise from this month. The 1 % sales bonus rule is on (approved
automatically). Last month's payroll is finalized, published and paid (a few people already
tapped "I received it"); this month's is a draft. Bonuses and fines: an approved bonus and fine
last month, and this month an approved bonus, a proposed fine and a disputed one. Jasur's
advance is repaid over two months, Alisher's card advance (from the finance demo) comes off this
month's pay, and Kamola's request waits for a decision. Nodira resigned: her final payslip pays
her days through the last one and 9 unused leave days, and takes her advance back in full; it is
finalized and paid when she left last month (a draft while her month still runs).

The finance demo books each month's salaries straight into the ledger; once payroll books a
month, the demo voids those rows for it, so the books carry each salary once.

The distributor gets its people's pay setups and this month's draft.
"""

import logging
from datetime import time, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import translation

from apps.core import demo_plan
from apps.core.demo_time import moment
from apps.core.exceptions import DomainError
from apps.finance import services as finance
from apps.finance.models import Debt, MoneyAccount, Transaction
from apps.payroll import defaults, periods, queries, services
from apps.payroll.models import Adjustment, AdjustmentRule, Advance, Compensation, Payslip

logger = logging.getLogger(__name__)

D = Decimal
# A month's pay, as the finance demo pays it (night pharmacists: their base before the premium).
PAY = {
    "manager": D("10500000"),
    "farrux": D("10000000"),
    "madina": D("5800000"),
    "sardor": D("5600000"),
    "malika": D("5500000"),
    "worker": D("4900000"),
    "gulnora": D("4800000"),
    "shahzoda": D("4700000"),
    "kamola": D("4500000"),
    "nigora": D("4700000"),
    "dilshod": D("4600000"),
    "jasur": D("3500000"),
    "otabek": D("4500000"),
    "aziza": D("6000000"),
    "bobur": D("4600000"),
    "nodira": D("4700000"),
}
RAISE = ("worker", D("5200000"), "Yillik baholash natijasi bo‘yicha oshirildi")
SMALL_PAY = {
    "manager": D("9000000"),
    "worker": D("5000000"),
    "cashier": D("7000000"),
    "driver": D("4500000"),
}
FINANCE_DEMO = "finance.demo"  # the finance demo's source type (its salary rows)
RECEIVED = ("worker", "madina", "nigora", "jasur")


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    with translation.override(company.default_language):
        Story(company, people, now).build()


def seed_small(company, people, now) -> None:
    """The distributor: pay setups and this month's draft. `people`: owner, manager, worker
    and cashier."""
    with translation.override(company.default_language):
        story = Story(company, people, now)
        story.pay_setups(SMALL_PAY)
        story.draft()


class Story:
    def __init__(self, company, people, now):
        self.company = company
        self.now = now
        self.plan = demo_plan.Plan(company, people, now)
        self.members = self.plan.members()
        self.owner = self.members["owner"]
        self.manager = self.members.get("manager")
        self.today = self.plan.today
        self.this_month = periods.first_day(self.today)
        self.last_month = periods.previous_period(self.this_month)

    def member(self, key: str):
        return self.members.get(key)

    def at(self, day, hour: int, minute: int = 0):
        """A moment on `day`, never later than an hour before now."""
        return min(self.plan.at(day, time(hour, minute)), self.now - timedelta(hours=1))

    def build(self) -> None:
        self.rules()
        self.pay_setups(PAY)
        self.newcomers()
        self.raise_()
        self.advances()
        self.leaver()
        self.last_month_adjustments()
        self.last_month_run()
        self.this_month_adjustments()
        self.draft()

    # Setup ----------------------------------------------------------------------------------

    def rules(self) -> None:
        """The shipped examples, with the 1 % sales bonus switched on (approved automatically)."""
        defaults.ensure(self.company)
        AdjustmentRule.objects.filter(company=self.company, example_key="sales_bonus").update(
            is_active=True, auto_approve=True
        )

    def pay_setups(self, table: dict) -> None:
        for key, amount in table.items():
            member = self.member(key)
            if member is None:
                continue
            first = self.plan.joined(key)
            if member.status in services.PAYABLE_STATUSES:
                with moment(self.at(first, 11)):
                    services.set_pay(member, by=self.owner, effective_from=first, amount=amount)
            else:
                # Somebody who has left keeps the pay they had, for their last month's payslip.
                Compensation.objects.create(
                    company=self.company,
                    membership=member,
                    effective_from=first,
                    amount=amount,
                    created_by=self.owner.user,
                )

    def newcomers(self) -> None:
        """People other demos approved (joiners of today): a pharmacist's pay from their first
        day, so nobody working here is left without a pay setup."""
        from apps.members.models import Membership

        rates = {
            demo_plan.HEAD: D("10000000"),
            demo_plan.SENIOR: D("5500000"),
            demo_plan.PHARMACIST: D("4500000"),
            demo_plan.STOCK: D("4200000"),
            demo_plan.COURIER: D("3500000"),
            demo_plan.OFFICE: D("5000000"),
        }
        paid = Compensation.objects.filter(company=self.company).values("membership_id")
        people = (
            Membership.objects.filter(company=self.company, status__in=services.PAYABLE_STATUSES)
            .exclude(pk__in=paid)
            .exclude(role__is_owner=True)
            .select_related("position")
        )
        for member in people:
            joined = member.decided_at or member.created_at
            first = periods.local(self.company, joined).date()
            name = member.position.name if member.position_id else ""
            with moment(min(joined, self.now - timedelta(hours=1))):
                services.set_pay(
                    member,
                    by=self.owner,
                    effective_from=first,
                    amount=rates.get(name, D("4500000")),
                )

    def raise_(self) -> None:
        key, amount, reason = RAISE
        member = self.member(key)
        if member is None:
            return
        with moment(self.at(self.last_month + timedelta(days=24), 16)):
            services.propose_pay_change(
                member,
                by=self.owner,
                setup={"amount": amount},
                effective_on=self.this_month,
                reason=reason,
            )

    # Money out of the till ------------------------------------------------------------------

    def payout_account(self, amount: Decimal) -> MoneyAccount | None:
        """The account with the most money (the bank, in the full demo) when it can pay."""
        accounts = MoneyAccount.objects.filter(
            company=self.company, is_active=True, currency="UZS"
        ).order_by("-balance", "pk")
        best = accounts.first()
        if best is None or (best.balance < amount and not best.allow_negative):
            return None
        return best

    def advances(self) -> None:
        jasur = self.member("jasur")
        if jasur is not None:
            asked = self.last_month + timedelta(days=7)
            with moment(self.at(asked, 9, 30)):
                row = services.request_advance(
                    jasur,
                    by=jasur,
                    amount=D("1000000"),
                    installments=2,
                    reason="Velosiped ta’miri uchun",
                )
            with moment(self.at(asked, 15)):
                services.decide_advance(row, by=self.owner, approve_it=True)
            account = self.payout_account(D("1000000"))
            if account is not None:
                method = "cash" if account.kind in ("cash", "safe") else "bank"
                with moment(self.at(asked + timedelta(days=1), 10)):
                    services.pay_advance(row, by=self.owner, account=account, method=method)
        self.adopt_card_advance()
        kamola = self.member("kamola")
        if kamola is not None and queries.advance_cap(kamola)["available"] >= D("500000"):
            with moment(self.now - timedelta(hours=3)):
                services.request_advance(
                    kamola, by=kamola, amount=D("500000"), reason="Ijara to‘lovi uchun"
                )

    def leaver(self) -> None:
        """Nodira's final settlement (§3.17): an advance paid ten days before she left comes off
        in full, 9 unused leave days are paid out."""
        from apps.members.models import Membership

        nodira = self.member("nodira")
        if nodira is None or nodira.status != Membership.Status.LEFT:
            return
        left_on = self.plan.day(-demo_plan.LEFT_DAYS_AGO)
        account = self.payout_account(D("800000"))
        if account is not None:
            given = left_on - timedelta(days=10)
            nodira.status = Membership.Status.APPROVED  # as she was then (not saved)
            try:
                with moment(self.at(given, 10)):
                    row = services.create_advance(
                        nodira,
                        by=self.owner,
                        amount=D("800000"),
                        installments=2,
                        first_period=periods.first_day(given),
                        reason="Oilaviy tadbir uchun",
                    )
                with moment(self.at(given, 11)):
                    services.pay_advance(row, by=self.owner, account=account, method="cash")
            except DomainError as exc:
                logger.warning("Demo advance of the leaver not given: %s", exc)
            finally:
                nodira.status = Membership.Status.LEFT
        try:
            with moment(self.at(left_on + timedelta(days=1), 10)):
                run = services.create_final_run(nodira, by=self.owner, leave_days=D("9"))
        except DomainError as exc:
            logger.warning("Demo final payslip not prepared: %s", exc)
            return
        if run.period != self.last_month or not run.payslips.exists():
            return
        try:
            with transaction.atomic(), moment(self.at(left_on + timedelta(days=1), 15)):
                run = services.finalize_run(run, by=self.owner)
                services.publish(run, by=self.owner)
        except DomainError as exc:
            logger.warning("Demo final payslip stays a draft: %s", exc)
            return
        payslip = run.payslips.get()
        account = self.payout_account(max(payslip.net, D(0)))
        if account is not None:
            with moment(self.at(left_on + timedelta(days=1), 17)):
                services.mark_paid(
                    run, by=self.owner, payslip_ids=[payslip.pk], account=account, method="cash"
                )

    def adopt_card_advance(self) -> None:
        """The finance demo pays Alisher an advance by card: payroll takes it back this month."""
        worker = self.member("worker")
        if worker is None:
            return
        debt = (
            Debt.objects.filter(
                company=self.company,
                membership=worker,
                kind=Debt.Kind.ADVANCE,
                direction=Debt.Direction.RECEIVABLE,
                status=Debt.Status.OPEN,
                source_type="",
            )
            .order_by("pk")
            .first()
        )
        if debt is None or Advance.objects.filter(debt=debt).exists():
            return
        Advance.objects.create(
            company=self.company,
            membership=worker,
            amount=debt.amount,
            currency=debt.currency,
            installments=1,
            first_period=max(self.this_month, periods.first_day(debt.issued_on)),
            reason="Ish haqi avansi (kartaga)",
            status=Advance.Status.PAID,
            requested_by=worker.user,
            decided_by=self.owner.user,
            paid_by=self.owner.user,
            payout_method="card",
            debt=debt,
        )

    # Bonuses and fines ----------------------------------------------------------------------

    def adjust(self, key, kind, amount, reason, *, period, day, by=None, approve=True):
        member = self.member(key)
        if member is None:
            return None
        proposer = by or self.manager or self.owner
        if proposer.pk == member.pk:
            proposer = self.owner
        with moment(self.at(day, 12)):
            row = services.propose(
                member, by=proposer, kind=kind, amount=amount, reason=reason, period=period
            )
        if approve:
            with moment(self.at(day, 17)):
                services.approve(row, by=self.owner)
        return row

    def last_month_adjustments(self) -> None:
        day = self.last_month + timedelta(days=24)
        self.adjust(
            "madina",
            Adjustment.Kind.BONUS,
            D("300000"),
            "Oylik inventarizatsiyada yordam bergani uchun",
            period=self.last_month,
            day=day,
        )
        self.adjust(
            "otabek",
            Adjustment.Kind.FINE,
            D("50000"),
            "Kirim hujjatlari ikki kun kechikib topshirildi",
            period=self.last_month,
            day=day,
        )

    def this_month_adjustments(self) -> None:
        day = max(self.this_month, self.today - timedelta(days=1))
        self.adjust(
            "shahzoda",
            Adjustment.Kind.BONUS,
            D("200000"),
            "Tungi smenada hamkasbini almashtirgani uchun",
            period=self.this_month,
            day=day,
        )
        self.adjust(
            "sardor",
            Adjustment.Kind.FINE,
            D("50000"),
            "Smenaga 40 daqiqa kechikib keldi",
            period=self.this_month,
            day=day,
            approve=False,
        )
        disputed = self.adjust(
            "gulnora",
            Adjustment.Kind.FINE,
            D("100000"),
            "Kassa hisobotida 100 000 so‘m kamomad",
            period=self.this_month,
            day=day,
        )
        if disputed is not None:
            with moment(self.now - timedelta(minutes=50)):
                services.dispute(
                    disputed,
                    by=disputed.membership,
                    text="Kamomad terminal xatosi edi, bankdan kelgan chekni ilova qildim",
                )

    # Runs -----------------------------------------------------------------------------------

    def void_ledger_salaries(self, period) -> None:
        """The finance demo's own salary rows of `period`: payroll books them now."""
        rows = Transaction.objects.filter(
            company=self.company,
            source_type=FINANCE_DEMO,
            source_key=f"sal:{period:%Y%m}",
            status=Transaction.Status.POSTED,
        )
        for row in rows.order_by("pk"):
            finance.void_transaction(
                row, by=self.owner, reason="Ish haqi endi ish haqi bo‘limidan hisoblanadi"
            )

    def last_month_run(self) -> None:
        with moment(self.now - timedelta(hours=4)):
            run = services.create_run(self.company, by=None, period=self.last_month)
        if not run.payslips.exists():
            return
        try:
            with transaction.atomic(), moment(self.now - timedelta(hours=3)):
                self.void_ledger_salaries(self.last_month)
                run = services.finalize_run(run, by=self.owner)
                services.publish(run, by=self.owner)
        except DomainError as exc:
            logger.warning("Demo payroll for %s stays a draft: %s", self.last_month, exc)
            return
        total = sum((payslip.net for payslip in run.payslips.all()), D(0))
        account = self.payout_account(total)
        if account is None:
            return
        with moment(self.now - timedelta(hours=2)):
            services.mark_paid(
                run,
                by=self.owner,
                payslip_ids=list(run.payslips.values_list("pk", flat=True)),
                account=account,
                method="card",
            )
        for key in RECEIVED:
            member = self.member(key)
            payslip = run.payslips.filter(membership=member).first() if member else None
            if payslip is not None and payslip.status == Payslip.Status.PAID:
                with moment(self.now - timedelta(minutes=70)):
                    services.confirm_received(payslip, by=member)

    def draft(self) -> None:
        with moment(self.now - timedelta(minutes=30)):
            services.create_run(self.company, by=self.owner, period=self.this_month)
