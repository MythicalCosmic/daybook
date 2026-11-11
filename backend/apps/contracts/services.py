"""Business contracts: every change goes through here (audited, pulse bumped after commit).

    create_contract / update_contract   the contract and, when asked, its recurring payment
    renew                                a new end date (an extension signed, a renewal by hand)
    confirm_renewal / stop_renewal       the owner's answer before an auto-renewal's notice deadline
    terminate                            stopped early, on a day (today, past or future)
    delete_contract, add_file, remove_file, update_settings

**Status.** `status_on` derives it from the dates (see `models`): `draft` and an early
termination are decisions, the rest follows the calendar; `refresh_status` stores it.

**Money.** A contract in force with `in_forecast`, an amount and a period (not "once") keeps a
recurring payment in Finance (`apps.finance.recurring`), so the cash forecast sees the rent: a
bill (a reminder to pay it) in the contract's currency, on its payment day, for its
counterparty and branch, until its end (open-ended while it renews by itself). A contract can
take over an existing recurring payment instead (`RuleChoice.rule`) so rent already planned in
Finance isn't counted twice. The contract is the source of the payment's amount, schedule,
counterparty, branch and end; its name, category, account and payer stay as set in Finance.
Ending, terminating, drafting or deleting the contract (or switching `in_forecast` off) switches
the payment off; what it booked stays in the ledger.
"""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.console import pulse
from apps.contracts import conf
from apps.contracts.audit_actions import ContractsAction
from apps.contracts.models import BusinessContract, ContractFile, ContractSettings
from apps.core.exceptions import DomainError
from apps.core.money import Currency, quantize
from apps.members.models import Membership
from apps.members.permissions import Perm

Kind = BusinessContract.Kind
Period = BusinessContract.Period
Status = BusinessContract.Status

PULSE = "contracts"
LEDGER = "finance.ledger"  # the forecast and the cockpit's money read recurring payments
MAX_FILES = 30
MAX_FILE_BYTES = 20 * 1024 * 1024
# Writable by hand: the rest of the statuses follow the dates or the terminate action.
WRITABLE_STATUSES = (Status.DRAFT, Status.ACTIVE)
FIELDS = (
    "kind",
    "title",
    "branch",
    "counterparty",
    "counterparty_name",
    "number",
    "signed_on",
    "starts_on",
    "ends_on",
    "auto_renews",
    "renewal_months",
    "notice_days",
    "amount",
    "period",
    "currency",
    "payment_day",
    "notes",
    "status",
    "responsible",
    "in_forecast",
)
# The Finance category a new recurring payment books into, by kind (system codes).
KIND_CATEGORY = {
    Kind.LEASE: "rent",
    Kind.SUPPLY: "goods",
    Kind.SERVICE: "other_expense",
    Kind.LICENCE: "other_expense",
    Kind.INSURANCE: "other_expense",
    Kind.OTHER: "other_expense",
}
FREQUENCY = {Period.MONTHLY: "monthly", Period.QUARTERLY: "quarterly", Period.YEARLY: "yearly"}


@dataclass(frozen=True)
class RuleChoice:
    """What the form picked for the recurring payment: its category and account when one is
    made, or an existing recurring payment to take over."""

    category: object = None  # apps.finance.models.Category
    account: object = None  # apps.finance.models.MoneyAccount
    rule: object = None  # apps.finance.models.RecurringRule


# Dates ------------------------------------------------------------------------------------------


def local_today(company) -> date:
    return timezone.localdate(timezone=ZoneInfo(company.timezone))


def add_months(day: date, months: int) -> date:
    """The same day `months` later (the month's last day when it is shorter)."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def next_term_end(ends_on: date, months: int) -> date:
    """The last day of the next term: a term from the day after `ends_on`, `months` long.
    1 Jan to 31 Dec renews to 31 Dec next year; a term ending 28 Feb 2027 renews to 29 Feb 2028."""
    start = ends_on + timedelta(days=1)
    return add_months(start, months) - timedelta(days=1)


def status_on(contract: BusinessContract, today: date, remind_days: int) -> str:
    """The status `contract`'s dates give it on `today` (see the module docstring)."""
    if contract.status == Status.DRAFT:
        return Status.DRAFT
    if contract.terminated_on is not None and contract.terminated_on <= today:
        return Status.TERMINATED
    end = contract.ends_on
    if end is None:
        return Status.ACTIVE
    if end < today:
        # An auto-renewing contract never ends by itself: the daily job moves it on.
        return Status.ACTIVE if contract.auto_renews else Status.ENDED
    if contract.terminated_on is not None:
        return Status.ENDING
    if not contract.auto_renews and (end - today).days <= remind_days:
        return Status.ENDING
    return Status.ACTIVE


def notice_due(contract: BusinessContract, today: date, warn_days: int) -> bool:
    """An auto-renewing contract whose notice deadline is within `warn_days` (or today) and
    whose renewal nobody has confirmed yet: a decision to make."""
    deadline = contract.notice_deadline
    if deadline is None or contract.status not in BusinessContract.IN_FORCE:
        return False
    if contract.renewal_confirmed_for == contract.ends_on:
        return False
    return 0 <= (deadline - today).days <= warn_days


def ends_soon(contract: BusinessContract, today: date, warn_days: int) -> bool:
    """In force, not renewing by itself, and its last day within `warn_days`."""
    if contract.status not in BusinessContract.IN_FORCE or contract.ends_on is None:
        return False
    if contract.auto_renews:
        return False
    return 0 <= (contract.ends_on - today).days <= warn_days


def needs_attention(contract: BusinessContract, today: date, settings: ContractSettings) -> bool:
    """The "ending soon" chip: it ends within the warning days, or a renewal decision is due."""
    return ends_soon(contract, today, settings.remind_days) or notice_due(
        contract, today, settings.notice_remind_days
    )


# Contracts --------------------------------------------------------------------------------------


@transaction.atomic
def create_contract(
    company, *, by: Membership, money: RuleChoice | None = None, **fields
) -> BusinessContract:
    """A new contract; with `in_forecast`, its recurring payment in Finance too."""
    _known(fields)
    contract = BusinessContract(company=company, created_by=_user(by))
    _apply(contract, fields, by=by, creating=True)
    settings = conf.get_settings(company)
    contract.status = status_on(contract, local_today(company), settings.remind_days)
    contract.save()
    touched = _sync_rule(contract, by=by, money=money)
    _audit(
        ContractsAction.CONTRACT_CREATED,
        contract,
        by,
        kind=contract.kind,
        status=contract.status,
        ends_on=_iso(contract.ends_on),
        rule=contract.rule_id,
    )
    _bump(company, ledger=touched)
    return contract


@transaction.atomic
def update_contract(
    contract: BusinessContract, *, by: Membership, money: RuleChoice | None = None, **fields
) -> BusinessContract:
    _known(fields)
    contract = _lock(contract)
    before = _snapshot(contract)
    _apply(contract, fields, by=by, creating=False)
    if contract.ends_on != before["ends_on_date"]:
        contract.renewal_confirmed_for = None  # a new end date asks the question again
    settings = conf.get_settings(contract.company)
    contract.status = status_on(contract, local_today(contract.company), settings.remind_days)
    contract.save()
    touched = _sync_rule(contract, by=by, money=money)
    changes = _diff(before, _snapshot(contract))
    if changes:
        _audit(ContractsAction.CONTRACT_UPDATED, contract, by, changes=changes)
    _bump(contract.company, ledger=touched)
    return contract


@transaction.atomic
def renew(contract: BusinessContract, *, by: Membership, ends_on: date) -> BusinessContract:
    """Its end moves to `ends_on`: an extension signed, or a lapsed contract signed again."""
    contract = _lock(contract)
    if contract.status in (Status.DRAFT, Status.TERMINATED):
        raise DomainError(_("Only a contract that is or was in force can be renewed."))
    if ends_on is None:
        raise DomainError(_("Pick the new end date."))
    if contract.ends_on is not None and ends_on <= contract.ends_on:
        raise DomainError(_("The new end date must be after the current one."))
    if contract.starts_on is not None and ends_on < contract.starts_on:
        raise DomainError(_("It can't end before it starts."))
    today = local_today(contract.company)
    if ends_on < today:
        raise DomainError(_("The new end date has already passed."))
    previous = contract.ends_on
    contract.ends_on = ends_on
    contract.terminated_on = None
    contract.termination_reason = ""
    contract.last_renewed_on = today
    contract.renewal_confirmed_for = None
    # Renewed by a person: the "renewed by itself" notice is not for this term.
    contract.reminders_sent = [*contract.reminders_sent, reminder_key("renewed", ends_on, "auto")]
    settings = conf.get_settings(contract.company)
    contract.status = status_on(contract, today, settings.remind_days)
    contract.save()
    touched = _sync_rule(contract, by=by, money=None)
    _audit(
        ContractsAction.CONTRACT_RENEWED,
        contract,
        by,
        **{"from": _iso(previous), "to": _iso(ends_on)},
    )
    _bump(contract.company, ledger=touched)
    return contract


@transaction.atomic
def confirm_renewal(contract: BusinessContract, *, by: Membership) -> BusinessContract:
    """The owner wants the auto-renewal: the notice reminder of this term is settled."""
    contract = _lock(contract)
    if not contract.auto_renews or contract.ends_on is None:
        raise DomainError(_("This contract doesn't renew by itself."))
    if contract.status not in BusinessContract.IN_FORCE:
        raise DomainError(_("This contract is no longer in force."))
    contract.renewal_confirmed_for = contract.ends_on
    contract.save(update_fields=["renewal_confirmed_for", "updated_at"])
    _audit(
        ContractsAction.CONTRACT_UPDATED,
        contract,
        by,
        changes={"renewal_confirmed_for": [None, _iso(contract.ends_on)]},
    )
    _bump(contract.company)
    return contract


def stop_renewal(contract: BusinessContract, *, by: Membership) -> BusinessContract:
    """The owner gives notice: it won't renew and ends on its end date."""
    if not contract.auto_renews:
        raise DomainError(_("This contract doesn't renew by itself."))
    return update_contract(contract, by=by, auto_renews=False)


@transaction.atomic
def terminate(
    contract: BusinessContract, *, by: Membership, on: date, reason: str = ""
) -> BusinessContract:
    """Stopped early: its last day is `on` (today, a past day found out late, or a day ahead
    after notice). The recurring payment ends with it."""
    contract = _lock(contract)
    if contract.status not in BusinessContract.IN_FORCE:
        raise DomainError(_("Only a contract in force can be terminated."))
    if on is None:
        raise DomainError(_("Pick the day it ends."))
    if contract.starts_on is not None and on < contract.starts_on:
        raise DomainError(_("It can't end before it starts."))
    if contract.ends_on is not None and on > contract.ends_on and not contract.auto_renews:
        raise DomainError(
            _("It ends on %(day)s anyway.") % {"day": contract.ends_on.strftime("%d.%m.%Y")}
        )
    before = _snapshot(contract)
    contract.terminated_on = on
    contract.ends_on = on
    contract.auto_renews = False
    contract.termination_reason = " ".join(str(reason or "").split())[:300]
    settings = conf.get_settings(contract.company)
    contract.status = status_on(contract, local_today(contract.company), settings.remind_days)
    contract.save()
    touched = _sync_rule(contract, by=by, money=None)
    _audit(
        ContractsAction.CONTRACT_TERMINATED,
        contract,
        by,
        on=_iso(on),
        reason=contract.termination_reason,
        changes=_diff(before, _snapshot(contract)),
    )
    _bump(contract.company, ledger=touched)
    return contract


@transaction.atomic
def delete_contract(contract: BusinessContract, *, by: Membership) -> None:
    """Gone with its files. Its recurring payment is switched off (what it booked stays)."""
    contract = _lock(contract)
    company = contract.company
    touched = _stop_rule(contract, by=by)
    names = [row.file.name for row in contract.files.all() if row.file]
    _audit(ContractsAction.CONTRACT_DELETED, contract, by, kind=contract.kind)
    contract.delete()
    if names:
        from apps.core.storage import private_storage

        transaction.on_commit(lambda: [private_storage.delete(name) for name in names])
    _bump(company, ledger=touched)


def refresh_status(contract: BusinessContract, today: date, settings: ContractSettings) -> bool:
    """Store the status the dates give (by the system: the daily job). True when it moved."""
    status = status_on(contract, today, settings.remind_days)
    if status == contract.status:
        return False
    previous = contract.status
    BusinessContract.objects.filter(pk=contract.pk).update(status=status, updated_at=timezone.now())
    contract.status = status
    _audit(ContractsAction.CONTRACT_STATUS, contract, None, **{"from": previous, "to": status})
    return True


def renew_by_itself(contract: BusinessContract, today: date, settings: ContractSettings) -> bool:
    """An auto-renewing contract past its last day moves on by whole terms (the daily job)."""
    if not contract.auto_renews or contract.ends_on is None or contract.ends_on >= today:
        return False
    if contract.status not in BusinessContract.IN_FORCE:
        return False
    previous = end = contract.ends_on
    while end < today:
        end = next_term_end(end, contract.renewal_months)
    contract.ends_on = end
    contract.last_renewed_on = today
    contract.renewal_confirmed_for = None
    contract.status = status_on(contract, today, settings.remind_days)
    contract.save(
        update_fields=[
            "ends_on",
            "last_renewed_on",
            "renewal_confirmed_for",
            "status",
            "updated_at",
        ]
    )
    _audit(
        ContractsAction.CONTRACT_RENEWED,
        contract,
        None,
        **{"from": _iso(previous), "to": _iso(end), "auto": True},
    )
    return True


# Files ------------------------------------------------------------------------------------------


@transaction.atomic
def add_file(
    contract: BusinessContract, *, by: Membership, file, kind: str = "", label: str = ""
) -> ContractFile:
    """The signed scan, an annex or another paper: a PDF or a picture (pictures are re-encoded,
    their metadata dropped), at most `MAX_FILE_BYTES`, `MAX_FILES` per contract."""
    from apps.core.uploads import accept_document

    contract = _lock(contract)
    kind = kind or ContractFile.Kind.SIGNED
    if kind not in ContractFile.Kind.values:
        raise DomainError(_("Pick what the file is from the list."))
    if contract.files.count() >= MAX_FILES:
        raise DomainError(
            _("A contract keeps at most %(count)d files: remove one first.") % {"count": MAX_FILES}
        )
    clean = accept_document(file, allowed=("pdf", "image"), max_bytes=MAX_FILE_BYTES)
    row = ContractFile(
        company=contract.company,
        contract=contract,
        kind=kind,
        label=" ".join(str(label or "").split())[:120],
        size=clean.size,
        uploaded_by=_user(by),
    )
    row.file.save(clean.name, clean, save=True)
    _audit(ContractsAction.FILE_ADDED, contract, by, file=row.pk, kind=kind, label=row.label)
    _bump(contract.company)
    return row


@transaction.atomic
def remove_file(row: ContractFile, *, by: Membership) -> None:
    contract = row.contract
    name = row.file.name if row.file else ""
    _audit(ContractsAction.FILE_REMOVED, contract, by, file=row.pk, kind=row.kind, label=row.label)
    row.delete()
    if name:
        from apps.core.storage import private_storage

        transaction.on_commit(lambda: private_storage.delete(name))
    _bump(contract.company)


# Settings ---------------------------------------------------------------------------------------


@transaction.atomic
def update_settings(company, *, by: Membership, **changes) -> ContractSettings:
    row = conf.get_settings(company)
    row = ContractSettings.objects.select_for_update().get(pk=row.pk)
    unknown = set(changes) - {"remind_days", "notice_remind_days"}
    if unknown:
        raise ValueError(f"Not contract settings: {sorted(unknown)}")
    if "remind_days" in changes and not 1 <= int(changes["remind_days"]) <= 365:
        raise DomainError(_("Warn 1 to 365 days ahead."))
    if "notice_remind_days" in changes and not 1 <= int(changes["notice_remind_days"]) <= 180:
        raise DomainError(_("Warn about a notice deadline 1 to 180 days ahead."))
    before = {name: getattr(row, name) for name in changes}
    for name, value in changes.items():
        setattr(row, name, int(value))
    row.save()
    changed = {
        name: [before[name], getattr(row, name)]
        for name in changes
        if before[name] != getattr(row, name)
    }
    if changed:
        audit.record(
            ContractsAction.SETTINGS_CHANGED,
            company_id=company.pk,
            actor=_user(by),
            target=row,
            required_perm=Perm.FINANCE_VIEW,
            changes=changed,
        )
        # The "ending" status reads the warning days.
        today = local_today(company)
        for contract in BusinessContract.objects.for_company(company).filter(
            status__in=BusinessContract.IN_FORCE
        ):
            refresh_status(contract, today, row)
    _bump(company)
    return row


# The recurring payment --------------------------------------------------------------------------


def money_ready(contract: BusinessContract) -> bool:
    """Whether its payment can be a recurring payment: an amount and a repeating period."""
    return bool(contract.amount) and contract.amount > 0 and contract.period in FREQUENCY


def _rule_end(contract: BusinessContract) -> date | None:
    if contract.terminated_on is not None:
        return contract.terminated_on
    return None if contract.auto_renews else contract.ends_on


def _sync_rule(contract: BusinessContract, *, by: Membership, money: RuleChoice | None) -> bool:
    """Make Finance's recurring payment match the contract. True when it changed one."""
    from apps.finance import recurring
    from apps.finance.models import RecurringRule

    wants = contract.in_forecast and contract.status in BusinessContract.IN_FORCE
    linking = money is not None and money.rule is not None
    if linking and contract.rule_id is not None and contract.rule_id != money.rule.pk:
        raise DomainError(_("This contract already has its recurring payment."))
    if not wants:
        if linking and contract.rule_id is None:
            raise DomainError(
                _("Only a contract in force with its payment in the forecast can take one over.")
            )
        return _stop_rule(contract, by=by)
    if not contract.company.has_feature("finance"):
        raise DomainError(_("Switch Finance on to put this payment in the cash forecast."))
    if not money_ready(contract):
        raise DomainError(
            _("Give the amount and how often it is paid to put it in the cash forecast.")
        )
    rule = contract.rule if contract.rule_id is not None else None
    if rule is None and linking:
        rule = money.rule
        if rule.company_id != contract.company_id:
            raise DomainError(_("Pick a recurring payment of this company."))
        if rule.business_contracts.exclude(pk=contract.pk).exists():
            raise DomainError(_("That recurring payment belongs to another contract."))
    if rule is not None:
        rule = RecurringRule.objects.select_related(
            "company", "category", "counterparty", "account", "branch"
        ).get(pk=rule.pk)
        if rule.currency != contract.currency:
            raise DomainError(
                _("The recurring payment is in %(currency)s, like its account.")
                % {"currency": rule.currency}
            )
        values = _rule_values(contract, rule)
        if money is not None and money.category is not None:
            values["category"] = money.category
        if money is not None and money.account is not None:
            values["account"] = money.account
        changes = {key: value for key, value in values.items() if _differs(rule, key, value)}
        if not rule.is_active:
            changes["is_active"] = True
        if changes:
            recurring.update_rule(rule, by=by, **changes)
        if contract.rule_id != rule.pk:
            contract.rule = rule
            contract.save(update_fields=["rule", "updated_at"])
        return bool(changes) or linking
    account = money.account if money is not None else None
    account = account or _default_account(contract)
    if account is not None and account.currency != contract.currency:
        raise DomainError(
            _("%(account)s holds %(currency)s.")
            % {"account": account.name, "currency": account.currency}
        )
    category = (money.category if money is not None else None) or _default_category(contract)
    if category is None:
        raise DomainError(_("Pick the expense category of this payment."))
    payer = contract.responsible
    if payer is not None and payer.status != Membership.Status.APPROVED:
        payer = None
    rule = recurring.create_rule(
        contract.company,
        by=by,
        name=contract.title[:100],
        kind="expense",
        mode="bill",
        category=category,
        account=account,
        starts_on=contract.starts_on or local_today(contract.company),
        payer=payer,
        **_rule_values(contract, None),
    )
    contract.rule = rule
    contract.save(update_fields=["rule", "updated_at"])
    return True


def _rule_values(contract: BusinessContract, rule) -> dict:
    day = contract.payment_day
    if day is None:
        day = (
            rule.day
            if rule is not None
            else (contract.starts_on or local_today(contract.company)).day
        )
    values = {
        "frequency": FREQUENCY[contract.period],
        "interval": 1,
        "day": day,
        "counterparty": contract.counterparty,
        "branch": contract.branch,
        "ends_on": _rule_end(contract),
    }
    if rule is None or not rule.amount_varies:
        values["amount"] = quantize(contract.amount)
    return values


def _differs(rule, key: str, value) -> bool:
    current = getattr(rule, key)
    if hasattr(value, "pk") or hasattr(current, "pk"):
        return getattr(current, "pk", None) != getattr(value, "pk", None)
    if isinstance(value, Decimal):
        return quantize(current or 0) != value
    return current != value


def _stop_rule(contract: BusinessContract, *, by: Membership) -> bool:
    from apps.finance import recurring

    if contract.rule_id is None:
        return False
    rule = contract.rule
    if not rule.is_active:
        return False
    recurring.stop_rule(rule, by=by)
    return True


def _default_category(contract: BusinessContract):
    from apps.finance.models import Category

    code = KIND_CATEGORY.get(contract.kind, "other_expense")
    rows = Category.objects.for_company(contract.company).filter(
        kind=Category.Kind.EXPENSE, is_active=True
    )
    return rows.filter(system_code=code).first() or rows.filter(system_code="other_expense").first()


def _default_account(contract: BusinessContract):
    """No account picked: none for the base currency (a bill of the company), the first
    active account in a foreign currency (a USD lease is paid from dollars)."""
    from apps.finance.models import MoneyAccount

    if contract.currency == contract.company.base_currency:
        return None
    rows = MoneyAccount.objects.for_company(contract.company).filter(
        currency=contract.currency, is_active=True
    )
    if contract.branch_id is not None:
        found = rows.filter(branch_id=contract.branch_id).order_by("pk").first()
        if found is not None:
            return found
    found = rows.order_by("pk").first()
    if found is None:
        raise DomainError(
            _("Add a %(currency)s account in Finance first: the rent is paid from it.")
            % {"currency": contract.currency}
        )
    return found


# Helpers ----------------------------------------------------------------------------------------


def _known(fields: dict) -> None:
    unknown = set(fields) - set(FIELDS)
    if unknown:
        raise ValueError(f"Unknown contract fields: {sorted(unknown)}")


def _apply(contract: BusinessContract, fields: dict, *, by: Membership, creating: bool) -> None:
    """Check `fields` and set them on `contract` (every rule a contract keeps)."""
    company = contract.company
    fields = dict(fields)
    party_name = " ".join(str(fields.pop("counterparty_name", "") or "").split())[:200]
    for key in ("branch", "counterparty", "responsible"):
        value = fields.get(key)
        if value is not None and value.company_id != company.pk:
            raise DomainError(_("Must belong to the same company."))
    if "responsible" in fields:
        person = fields["responsible"]
        if (
            person is not None
            and person.pk != contract.responsible_id
            and person.status != Membership.Status.APPROVED
        ):
            raise DomainError(_("Pick someone who works here."))
    if "status" in fields:
        status = fields["status"]
        if status not in WRITABLE_STATUSES:
            raise DomainError(
                _("A contract is drafted or made active by hand; the rest follows its dates.")
            )
        if status == Status.ACTIVE and contract.status == Status.TERMINATED:
            # Brought back: the termination is undone.
            contract.terminated_on = None
            contract.termination_reason = ""
    for key, value in fields.items():
        setattr(contract, key, value)
    if party_name and fields.get("counterparty") is None:
        contract.counterparty = _party(company, party_name, contract.kind, by=by)
    contract.title = " ".join(str(contract.title or "").split())[:200]
    if not contract.title:
        raise DomainError(_("Give the contract a name, like Lease of the Chilonzor pharmacy."))
    contract.number = " ".join(str(contract.number or "").split())[:64]
    contract.notes = str(contract.notes or "").strip()
    if contract.kind not in Kind.values:
        raise DomainError(_("Pick a kind from the list."))
    if contract.period not in Period.values:
        raise DomainError(_("Pick how often it is paid."))
    if contract.currency not in Currency.values:
        raise DomainError(_("Pick a currency from the list."))
    if contract.starts_on and contract.ends_on and contract.ends_on < contract.starts_on:
        raise DomainError(_("It can't end before it starts."))
    if contract.amount is not None:
        if contract.amount < 0:
            raise DomainError(_("The amount can't be negative."))
        contract.amount = quantize(contract.amount)
    if contract.payment_day is not None and not 1 <= int(contract.payment_day) <= 31:
        raise DomainError(_("Pick a day of the month from 1 to 31."))
    if not 0 <= int(contract.notice_days) <= 365:
        raise DomainError(_("Notice is 0 to 365 days."))
    if not 1 <= int(contract.renewal_months) <= 120:
        raise DomainError(_("A renewal lasts 1 to 120 months."))
    if contract.auto_renews and contract.ends_on is None:
        raise DomainError(_("A contract that renews by itself needs its end date."))
    if contract.status != Status.DRAFT and contract.starts_on is None:
        raise DomainError(_("Pick the day it starts."))
    if contract.in_forecast and contract.period == Period.ONCE:
        raise DomainError(_("A one-off payment doesn't repeat: keep it out of the forecast."))


def _party(company, name: str, kind: str, *, by: Membership):
    """The counterparty called `name`, or a new one in the party directory."""
    from apps.finance import services as finance
    from apps.finance.models import Counterparty

    found = Counterparty.objects.for_company(company).filter(name__iexact=name).first()
    if found is not None:
        return found
    party_kind = (
        Counterparty.Kind.SUPPLIER
        if kind in (Kind.SUPPLY, Kind.SERVICE)
        else Counterparty.Kind.OTHER
    )
    return finance.create_counterparty(company, by=by, name=name, kind=party_kind)


def _lock(contract: BusinessContract) -> BusinessContract:
    return (
        BusinessContract.objects.select_for_update(of=("self",))
        .select_related("company", "branch", "counterparty", "responsible", "rule")
        .get(pk=contract.pk)
    )


def _iso(day: date | None) -> str | None:
    return day.isoformat() if day else None


def reminder_key(what: str, day: date, step: str) -> str:
    """How `reminders_sent` names a reminder: "end:2026-12-31:soon"."""
    return f"{what}:{day.isoformat()}:{step}"


def _snapshot(contract: BusinessContract) -> dict:
    return {
        "kind": contract.kind,
        "title": contract.title,
        "branch": contract.branch_id,
        "counterparty": contract.counterparty_id,
        "number": contract.number,
        "signed_on": _iso(contract.signed_on),
        "starts_on": _iso(contract.starts_on),
        "ends_on": _iso(contract.ends_on),
        "ends_on_date": contract.ends_on,
        "auto_renews": contract.auto_renews,
        "renewal_months": contract.renewal_months,
        "notice_days": contract.notice_days,
        "amount": str(contract.amount) if contract.amount is not None else None,
        "period": contract.period,
        "currency": contract.currency,
        "payment_day": contract.payment_day,
        "notes": contract.notes,
        "status": contract.status,
        "responsible": contract.responsible_id,
        "in_forecast": contract.in_forecast,
        "rule": contract.rule_id,
    }


def _diff(before: dict, after: dict) -> dict:
    return {
        key: [before[key], after[key]]
        for key in before
        if key != "ends_on_date" and before[key] != after[key]
    }


def _user(by: Membership | None):
    return by.user if by is not None else None


def _audit(action, contract: BusinessContract, by: Membership | None, **details) -> None:
    """Only people who see money see a contract's history (amounts and payments)."""
    audit.record(
        action,
        company_id=contract.company_id,
        actor=_user(by),
        target=contract,
        required_perm=Perm.FINANCE_VIEW,
        title=contract.title,
        **details,
    )


def _bump(company, *, ledger: bool = False) -> None:
    keys = (PULSE, LEDGER) if ledger else (PULSE,)
    transaction.on_commit(lambda: pulse.bump(company.pk, *keys))
