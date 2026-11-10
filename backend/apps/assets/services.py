"""Everything that changes fixed assets goes through here: the owner API, the mini app, the bots
and Celery. Keyword-only, `by: Membership` (None = the system), audited, and what changed is
posted at once (`posting`), so the asset's value is right the moment the page reloads.

Facts that depreciation depends on (cost, life, method, residual value, the day it was put into
service) can be corrected freely until a month of it is in Finance. After that, history stays:
a change of estimate, an improvement added to the cost or a write-down applies from the first
month not posted yet (NSBU No. 5), and the asset page shows each of them on its timeline.
"""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.assets import conf, engine, posting
from apps.assets.audit_actions import AssetAction
from apps.assets.models import (
    Asset,
    AssetAssignment,
    AssetCategory,
    AssetCount,
    AssetCountLine,
    AssetEvent,
    AssetFile,
    DepreciationEntry,
    Method,
    Permit,
    StartRule,
)
from apps.audit import services as audit
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.core.money import Currency, quantize
from apps.members.models import Membership
from apps.members.permissions import Perm

PULSE = "assets"
MAX_MONEY = Decimal("1000000000000000")  # 10^15: more than any pharmacy owns
FACT_FIELDS = (
    "cost",
    "price",
    "price_currency",
    "price_rate",
    "salvage_value",
    "life_months",
    "method",
    "declining_factor",
    "total_units",
    "in_service_on",
    "purchased_on",
    "opening_accumulated",
    "books_depreciation",
)
PLAIN_FIELDS = (
    "name",
    "model",
    "serial",
    "notes",
    "condition",
    "number",
    "category",
    "responsible",
    "warranty_until",
    "insurance_until",
    "service_months",
    "next_service_on",
    "verify_months",
    "next_verification_on",
    "supplier",
    "supplier_name",
    "unit",
    "branch",
)


# Helpers --------------------------------------------------------------------------------------


def _user(by: Membership | None):
    return by.user if by is not None else None


def _audit(action: str, company, by: Membership | None, target, **details) -> None:
    audit.record(
        action,
        company_id=company.pk,
        actor=_user(by),
        target=target,
        required_perm=Perm.ASSETS_MANAGE,
        **details,
    )


def _bump(company) -> None:
    company_id = company.pk
    # The lifecycle's Equipment page shows who holds what: it refreshes with every change here
    # (a confirmation in the app included).
    transaction.on_commit(lambda: pulse.bump(company_id, PULSE, "lifecycle.equipment"))


def _money(value, *, name: str, allow_zero: bool = False) -> Decimal:
    try:
        amount = quantize(Decimal(str(value).replace(" ", "").replace(",", ".")))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise DomainError(_("%(field)s: give an amount.") % {"field": name}) from exc
    if amount < 0 or (amount == 0 and not allow_zero):
        raise DomainError(_("%(field)s: give an amount above zero.") % {"field": name})
    if amount >= MAX_MONEY:
        raise DomainError(_("%(field)s: that amount is too large.") % {"field": name})
    return amount


def _same_company(company, *objects) -> None:
    for item in objects:
        if item is not None and getattr(item, "company_id", company.pk) != company.pk:
            raise DomainError(_("Pick something of this company."))


def _today(company) -> date:
    return posting.local_today(company)


def _check_day(company, day: date | None, *, name: str, future_days: int = 0) -> None:
    if day is None:
        return
    if day > _today(company) + timedelta(days=future_days):
        raise DomainError(_("%(field)s can't be in the future.") % {"field": name})
    if day.year < 1980:
        raise DomainError(_("%(field)s: check the year.") % {"field": name})


def _member(company, membership: Membership | None) -> Membership | None:
    if membership is None:
        return None
    _same_company(company, membership)
    if membership.status != Membership.Status.APPROVED:
        raise DomainError(_("%(person)s isn't an active member.") % {"person": membership})
    return membership


def _event(asset: Asset, kind: str, *, by, on: date, **fields) -> AssetEvent:
    return AssetEvent.objects.create(
        company=asset.company, asset=asset, kind=kind, on=on, created_by=_user(by), **fields
    )


def _booked(asset: Asset) -> bool:
    """Is any month of its depreciation, or its disposal, sale or write-down, in Finance?"""
    from apps.finance.models import LIVE_STATUSES, Transaction

    return (
        asset.entries.filter(transaction__isnull=False).exists()
        or asset.disposal_transaction_id is not None
        # Its own rows (written off, written down) point back at it only by their source.
        or Transaction.objects.filter(
            company_id=asset.company_id,
            source_type=posting.SOURCE_ASSET,
            source_id=asset.pk,
            status__in=LIVE_STATUSES,
        ).exists()
    )


def _repost(asset: Asset) -> None:
    """Post what is due, then book what Finance doesn't have yet."""
    posting.post_asset(asset)
    posting.book_company(asset.company)


def _lock(asset: Asset) -> Asset:
    return Asset.objects.select_for_update().select_related("company", "category").get(pk=asset.pk)


def _live(asset: Asset) -> None:
    if asset.status == Asset.Status.DISPOSED:
        raise DomainError(_("This asset was disposed of."))


def _next_on_cadence(company, start: date, months: int) -> date:
    """The first date of the cadence (every `months` from `start`) from today on: an asset
    entered with years of history isn't "overdue since 2022" for a service nobody recorded."""
    today = _today(company)
    day = _add_months(start, months)
    steps = 1
    while day < today and steps < 1200:
        steps += 1
        day = _add_months(start, months * steps)
    return day


def _add_months(day: date, months: int) -> date:
    first = engine.add_months(day.replace(day=1), months)
    return first.replace(day=min(day.day, engine.days_in(first)))


# Settings and categories ----------------------------------------------------------------------

SETTINGS_FIELDS = (
    "start_rule",
    "number_prefix",
    "next_number",
    "capitalization_threshold",
    "replacement_inflation",
    "tax_book",
    "remind_days",
)


@transaction.atomic
def update_settings(company, *, by: Membership, **fields):
    row = conf.get_settings(company)
    row = type(row).objects.select_for_update().get(pk=row.pk)
    unknown = set(fields) - set(SETTINGS_FIELDS)
    if unknown:
        raise ValueError(f"Unknown asset settings: {sorted(unknown)}")
    before = {name: str(getattr(row, name)) for name in fields}
    if "start_rule" in fields and fields["start_rule"] != row.start_rule:
        if fields["start_rule"] not in StartRule.values:
            raise DomainError(_("Pick a rule from the list."))
        posted = DepreciationEntry.objects.filter(company=company, opening=False).exists()
        if posted:
            raise DomainError(
                _(
                    "Depreciation was already posted under the current rule; the rule can change "
                    "only before the first month is posted."
                )
            )
    if "number_prefix" in fields:
        prefix = str(fields["number_prefix"]).strip().upper()
        if not prefix or len(prefix) > 8 or not prefix.replace("-", "").isalnum():
            raise DomainError(_("A prefix is 1–8 letters or digits."))
        fields["number_prefix"] = prefix
    if "next_number" in fields and int(fields["next_number"]) < 1:
        raise DomainError(_("The next number starts at 1."))
    if fields.get("capitalization_threshold") not in (None, ""):
        fields["capitalization_threshold"] = _money(
            fields["capitalization_threshold"], name=_("Threshold"), allow_zero=True
        )
    elif "capitalization_threshold" in fields:
        fields["capitalization_threshold"] = None
    if "replacement_inflation" in fields:
        value = Decimal(str(fields["replacement_inflation"]))
        if not 0 <= value <= 100:
            raise DomainError(_("Give a percentage from 0 to 100."))
    if "remind_days" in fields and not 1 <= int(fields["remind_days"]) <= 180:
        raise DomainError(_("Warn 1 to 180 days ahead."))
    for name, value in fields.items():
        setattr(row, name, value)
    row.save()
    after = {name: str(getattr(row, name)) for name in fields}
    changes = {name: [before[name], after[name]] for name in fields if before[name] != after[name]}
    if changes:
        _audit(AssetAction.SETTINGS_CHANGED, company, by, row, changes=changes)
        _bump(company)
    return row


CATEGORY_FIELDS = (
    "name",
    "kind",
    "life_months",
    "method",
    "salvage_percent",
    "tax_group",
    "tax_rate",
    "service_months",
    "verify_months",
    "icon",
    "order",
    "is_active",
)


def _clean_category(company, fields: dict, *, current: AssetCategory | None = None) -> dict:
    from apps.assets.defaults import TAX_GROUPS

    if "name" in fields:
        name = " ".join(str(fields["name"]).split())[:100]
        if not name:
            raise DomainError(_("Give the category a name."))
        same = AssetCategory.objects.filter(company=company, name__iexact=name)
        if current is not None:
            same = same.exclude(pk=current.pk)
        if same.exists():
            raise DomainError(_("There is already a category with this name."))
        fields["name"] = name
    kind = fields.get("kind", current.kind if current else AssetCategory.Kind.FIXED)
    if kind not in AssetCategory.Kind.values:
        raise DomainError(_("Pick a kind from the list."))
    method = fields.get("method", current.method if current else Method.STRAIGHT_LINE)
    if method not in Method.values:
        raise DomainError(_("Pick a method from the list."))
    if kind == AssetCategory.Kind.LOW_VALUE:
        fields["method"] = Method.NONE
        fields["life_months"] = None
    life = fields.get("life_months", current.life_months if current else None)
    if life is not None and not 1 <= int(life) <= 1200:
        raise DomainError(_("A useful life is 1 to 1200 months."))
    if "salvage_percent" in fields:
        value = Decimal(str(fields["salvage_percent"] or 0))
        if not 0 <= value < 100:
            raise DomainError(_("A residual value is 0 to 99 percent."))
        fields["salvage_percent"] = value
    group = fields.get("tax_group", current.tax_group if current else "")
    if group and group not in TAX_GROUPS:
        raise DomainError(_("Pick a Tax Code group from the list."))
    rate = fields.get("tax_rate", current.tax_rate if current else None)
    if rate not in (None, ""):
        rate = Decimal(str(rate))
        cap = Decimal(TAX_GROUPS[group][0]) if group else Decimal(100)
        if not 0 < rate <= cap:
            raise DomainError(
                _("The Tax Code allows at most %(rate)s%% a year for this group.") % {"rate": cap}
            )
        fields["tax_rate"] = rate
    elif "tax_rate" in fields:
        fields["tax_rate"] = None
    for name in ("service_months", "verify_months"):
        if fields.get(name) not in (None, "") and not 1 <= int(fields[name]) <= 120:
            raise DomainError(_("Give 1 to 120 months."))
        if fields.get(name) == "":
            fields[name] = None
    return fields


@transaction.atomic
def create_category(company, *, by: Membership, **fields) -> AssetCategory:
    unknown = set(fields) - set(CATEGORY_FIELDS)
    if unknown:
        raise ValueError(f"Unknown category fields: {sorted(unknown)}")
    if "name" not in fields:
        raise DomainError(_("Give the category a name."))
    fields = _clean_category(company, dict(fields))
    category = AssetCategory.objects.create(company=company, **fields)
    _audit(AssetAction.CATEGORY_CREATED, company, by, category, name=category.name)
    _bump(company)
    return category


@transaction.atomic
def update_category(category: AssetCategory, *, by: Membership, **fields) -> AssetCategory:
    unknown = set(fields) - set(CATEGORY_FIELDS)
    if unknown:
        raise ValueError(f"Unknown category fields: {sorted(unknown)}")
    category = AssetCategory.objects.select_for_update().get(pk=category.pk)
    if "kind" in fields and fields["kind"] != category.kind and category.assets.exists():
        raise DomainError(_("This category has assets: its kind can't change."))
    fields = _clean_category(category.company, dict(fields), current=category)
    before = {name: str(getattr(category, name)) for name in fields}
    for name, value in fields.items():
        setattr(category, name, value)
    category.save()
    changes = {
        name: [before[name], str(getattr(category, name))]
        for name in fields
        if before[name] != str(getattr(category, name))
    }
    if changes:
        _audit(AssetAction.CATEGORY_CHANGED, category.company, by, category, changes=changes)
        _bump(category.company)
    return category


@transaction.atomic
def delete_category(category: AssetCategory, *, by: Membership) -> None:
    if category.assets.exists():
        raise DomainError(_("This category has assets: move them first, or switch it off."))
    _audit(AssetAction.CATEGORY_DELETED, category.company, by, category, name=category.name)
    company = category.company
    category.delete()
    _bump(company)


# Creating and changing assets -------------------------------------------------------------------


def next_number(company) -> str:
    """The next free inventory number (AV-0001), taken under the settings row's lock."""
    row = conf.get_settings(company)
    row = type(row).objects.select_for_update().get(pk=row.pk)
    number = row.next_number
    while True:
        candidate = f"{row.number_prefix}-{number:04d}"
        if not Asset.objects.filter(company=company, number=candidate).exists():
            break
        number += 1
    row.next_number = number + 1
    row.save(update_fields=["next_number", "updated_at"])
    return candidate


def _clean_number(company, number: str, *, current: Asset | None = None) -> str:
    number = " ".join(str(number or "").split())[:24]
    if not number:
        raise DomainError(_("Give an inventory number."))
    same = Asset.objects.filter(company=company, number=number)
    if current is not None:
        same = same.exclude(pk=current.pk)
    if same.exists():
        raise DomainError(_("Inventory number %(number)s is taken.") % {"number": number})
    return number


def _purchase(company, txn):
    """The ledger row an asset was bought with: a live expense of this company."""
    from apps.finance.models import Transaction

    if txn is None:
        return None
    if not isinstance(txn, Transaction):
        txn = Transaction.objects.filter(company=company, pk=txn).first()
        if txn is None:
            raise DomainError(_("That purchase isn't in Finance."))
    _same_company(company, txn)
    sensitive = txn.category_id is not None and txn.category.is_sensitive  # salaries
    if txn.kind != Transaction.Kind.EXPENSE or txn.is_contra or sensitive:
        raise DomainError(_("Pick an expense: the money paid for it."))
    if txn.status not in (Transaction.Status.POSTED, Transaction.Status.PENDING):
        raise DomainError(_("That expense was voided or rejected."))
    # One expense buys one thing once: used again (another asset, another improvement) its cost
    # would come back twice as depreciation while it left the P&L only once.
    if (
        txn.capitalized
        or Asset.objects.filter(company=company, purchase_transaction=txn).exists()
        or AssetEvent.objects.filter(company=company, transaction=txn).exists()
    ):
        raise DomainError(_("This expense already bought an asset."))
    return txn


def _check_facts(asset: Asset) -> None:
    """The depreciation facts make sense together."""
    if asset.cost < 0:
        raise DomainError(_("The cost can't be below zero."))
    if asset.category.kind == AssetCategory.Kind.LOW_VALUE:
        # Never depreciated: its cost was an expense when bought, so Finance books nothing more.
        asset.method = Method.NONE
        asset.books_depreciation = False
    if asset.method not in Method.values:
        raise DomainError(_("Pick a method from the list."))
    if asset.method != Method.NONE:
        if asset.method != Method.UNITS and not asset.life_months:
            raise DomainError(_("Give its useful life in months."))
        if asset.life_months is not None and not 1 <= asset.life_months <= 1200:
            raise DomainError(_("A useful life is 1 to 1200 months."))
        if asset.method == Method.UNITS and not asset.total_units:
            raise DomainError(_("Give everything it will produce in its life (units)."))
        if asset.method == Method.DECLINING and not 1 <= asset.declining_factor <= 3:
            raise DomainError(_("The declining balance factor is 1 to 3."))
    if asset.salvage_value < 0 or (asset.cost and asset.salvage_value >= asset.cost):
        raise DomainError(_("The residual value must be below the cost."))
    if asset.in_service_on and asset.purchased_on and asset.in_service_on < asset.purchased_on:
        raise DomainError(_("It can't be put into service before it was bought."))
    if asset.opening_accumulated is not None:
        if asset.purchase_transaction_id:
            raise DomainError(
                _("A purchase in Finance starts from zero: leave earlier depreciation empty.")
            )
        if asset.opening_accumulated < 0 or asset.opening_accumulated > (
            asset.cost - asset.salvage_value
        ):
            raise DomainError(
                _("Earlier depreciation is at most the cost minus the residual value.")
            )
        this_month = engine.first_of(_today(asset.company))
        if asset.in_service_on is None or engine.first_of(asset.in_service_on) >= this_month:
            raise DomainError(_("Earlier depreciation needs a start before this month."))


@transaction.atomic
def create_asset(company, *, by: Membership | None, category: AssetCategory, name: str, **fields):
    """Add an asset. Defaults come from its category (useful life, method, residual value,
    service and check intervals); its number from the settings unless given. With a
    `purchase_transaction` (the expense it was bought with) the cost, price, day, branch and
    supplier default to that row's, and the row leaves the P&L: the depreciation brings it in
    month by month. Earlier months are posted at once."""
    allowed = set(FACT_FIELDS) | set(PLAIN_FIELDS) | {"purchase_transaction", "custodian", "status"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown asset fields: {sorted(unknown)}")
    _same_company(company, category, fields.get("branch"), fields.get("supplier"))
    fields.pop("category", None)
    if not category.is_active:
        raise DomainError(_("This category is switched off."))
    name = " ".join(str(name or "").split())[:120]
    if not name:
        raise DomainError(_("Give the asset a name."))
    txn = _purchase(company, fields.pop("purchase_transaction", None))
    custodian = _member(company, fields.pop("custodian", None))
    responsible = _member(company, fields.get("responsible"))
    if txn is not None:
        fields.setdefault("cost", -txn.base_amount)
        fields.setdefault("price", -txn.amount)
        fields.setdefault("price_currency", txn.currency)
        fields.setdefault("price_rate", txn.rate)
        fields.setdefault("purchased_on", txn.occurred_on)
        fields.setdefault("branch", txn.branch)
        fields.setdefault("supplier", txn.counterparty)
    price = fields.pop("price", None)
    price = None if price in (None, "") else _money(price, name=_("Price"), allow_zero=True)
    currency = fields.pop("price_currency", None) or company.base_currency
    if currency not in Currency.values:
        raise DomainError(_("Pick a currency from the list."))
    rate = fields.pop("price_rate", None)
    cost = fields.pop("cost", None)
    if cost in (None, "") and price is not None:
        if currency == company.base_currency:
            rate = Decimal(1)
        elif rate in (None, ""):
            rate = _rate_for(company, currency, fields.get("purchased_on") or _today(company))
        cost = quantize(price * Decimal(str(rate)))
    if cost in (None, ""):
        raise DomainError(_("Give what it cost."))
    cost = _money(cost, name=_("Cost"), allow_zero=category.kind == AssetCategory.Kind.LOW_VALUE)
    if txn is not None and cost != -txn.base_amount:
        raise DomainError(
            _("The cost must be the whole expense (%(amount)s); split a mixed purchase first.")
            % {"amount": -txn.base_amount}
        )
    for day_field in ("purchased_on",):
        _check_day(company, fields.get(day_field), name=_("The purchase day"))
    _check_day(company, fields.get("in_service_on"), name=_("The start"), future_days=366)

    number = fields.pop("number", "") or next_number(company)
    number = _clean_number(company, number)
    salvage = fields.pop("salvage_value", None)
    if salvage in (None, ""):
        salvage = quantize(cost * category.salvage_percent / 100)
    else:
        salvage = _money(salvage, name=_("Residual value"), allow_zero=True)
    life = fields.pop("life_months", None) or category.life_months
    method = fields.pop("method", None) or category.method
    in_service_on = fields.pop("in_service_on", None)
    status = fields.pop("status", None) or (
        Asset.Status.IN_USE if in_service_on else Asset.Status.IN_STORAGE
    )
    if status not in (Asset.Status.IN_USE, Asset.Status.IN_STORAGE, Asset.Status.REPAIR):
        raise DomainError(_("A new asset is in use, in storage or under repair."))
    opening = fields.pop("opening_accumulated", None)
    if opening not in (None, ""):
        opening = _money(opening, name=_("Earlier depreciation"), allow_zero=True)
    else:
        opening = None
    for name_ in ("total_units", "declining_factor"):
        if fields.get(name_) in ("", None):
            fields.pop(name_, None)
    asset = Asset(
        company=company,
        category=category,
        name=name,
        number=number,
        cost=cost,
        price=price,
        price_currency=currency,
        price_rate=Decimal(str(rate)) if rate not in (None, "") else Decimal(1),
        salvage_value=salvage,
        life_months=life,
        method=method,
        in_service_on=in_service_on,
        status=status,
        opening_accumulated=opening,
        purchase_transaction=txn,
        custodian=custodian,
        responsible=responsible,
        created_by=_user(by),
        **{key: value for key, value in fields.items() if key != "responsible"},
    )
    if asset.service_months is None:
        asset.service_months = category.service_months
    if asset.verify_months is None:
        asset.verify_months = category.verify_months
    if asset.in_service_on and asset.service_months and not asset.next_service_on:
        asset.next_service_on = _next_on_cadence(company, asset.in_service_on, asset.service_months)
    if asset.in_service_on and asset.verify_months and not asset.next_verification_on:
        asset.next_verification_on = _next_on_cadence(
            company, asset.in_service_on, asset.verify_months
        )
    _check_facts(asset)
    asset.save()
    details = {}
    # Its purchase leaves the P&L only when its depreciation brings the cost back.
    if txn is not None and asset.books_depreciation:
        from apps.finance import services as finance

        try:
            finance.capitalize(txn, by=by)
        except DomainError:
            # Its month is closed: that profit was reported with the purchase as a cost, so
            # depreciating it as well would count it twice.
            asset.books_depreciation = False
            asset.save(update_fields=["books_depreciation", "updated_at"])
            details["closed_books"] = True
    _event(asset, AssetEvent.Kind.CREATED, by=by, on=_today(company), details=details)
    if in_service_on:
        _event(asset, AssetEvent.Kind.IN_SERVICE, by=by, on=in_service_on)
    if custodian is not None:
        _open_assignment(asset, custodian, by=by, on=_today(company), condition=asset.condition)
    _audit(
        AssetAction.CREATED,
        company,
        by,
        asset,
        number=asset.number,
        cost=str(asset.cost),
        category=category.name,
    )
    _repost(asset)
    _bump(company)
    return asset


def _rate_for(company, currency: str, day: date) -> Decimal:
    if company.has_feature("finance"):
        from apps.finance.rates import rate_for

        return rate_for(company, currency, day).rate
    raise DomainError(_("Give the exchange rate of that day."))


@transaction.atomic
def update_asset(asset: Asset, *, by: Membership, **fields) -> Asset:
    """Correct an asset. Plain details change at any time; the depreciation facts only until a
    month is in Finance (then: change of estimate, add to cost, write down)."""
    unknown = set(fields) - set(FACT_FIELDS) - set(PLAIN_FIELDS)
    if unknown:
        raise ValueError(f"Unknown asset fields: {sorted(unknown)}")
    asset = _lock(asset)
    company = asset.company
    facts = set(fields) & set(FACT_FIELDS)
    if facts and _booked(asset):
        raise DomainError(
            _(
                "Its depreciation is already in the books: use Change estimate, Add to cost or "
                "Write down instead."
            )
        )
    if "category" in fields:
        _same_company(company, fields["category"])
        low = AssetCategory.Kind.LOW_VALUE
        if (fields["category"].kind == low) != (asset.category.kind == low):
            # A low-value item never depreciates: the move changes every month of it.
            if _booked(asset) or _purchases_of(asset):
                raise DomainError(
                    _(
                        "It is in Finance already: it can't become a low-value item or stop "
                        "being one."
                    )
                )
            facts.add("category")
    if "branch" in fields:
        _same_company(company, fields["branch"])
    if "supplier" in fields:
        _same_company(company, fields["supplier"])
    if "responsible" in fields:
        fields["responsible"] = _member(company, fields["responsible"])
    if "number" in fields:
        fields["number"] = _clean_number(company, fields["number"], current=asset)
    if "name" in fields:
        fields["name"] = " ".join(str(fields["name"]).split())[:120]
        if not fields["name"]:
            raise DomainError(_("Give the asset a name."))
    for money_field, label in (("cost", _("Cost")), ("salvage_value", _("Residual value"))):
        if money_field in fields:
            fields[money_field] = _money(fields[money_field], name=label, allow_zero=True)
    txn = asset.purchase_transaction
    # The purchase left the P&L whole: depreciating another cost would lose or add money.
    if (
        "cost" in fields
        and txn is not None
        and txn.capitalized
        and fields["cost"] != -txn.base_amount
    ):
        raise DomainError(
            _("The cost must be the whole expense (%(amount)s); split a mixed purchase first.")
            % {"amount": -txn.base_amount}
        )
    if "opening_accumulated" in fields and fields["opening_accumulated"] not in (None, ""):
        fields["opening_accumulated"] = _money(
            fields["opening_accumulated"], name=_("Earlier depreciation"), allow_zero=True
        )
    elif "opening_accumulated" in fields:
        fields["opening_accumulated"] = None
    if "purchased_on" in fields:
        _check_day(company, fields["purchased_on"], name=_("The purchase day"))
    if "in_service_on" in fields:
        _check_day(company, fields["in_service_on"], name=_("The start"), future_days=366)
    if "books_depreciation" in fields:
        _check_books_switch(asset, on=bool(fields["books_depreciation"]))
    old_branch = asset.branch
    before = {name: _plain(getattr(asset, name)) for name in fields}
    for name, value in fields.items():
        setattr(asset, name, value)
    _check_facts(asset)
    asset.save()
    if "branch" in fields and old_branch != asset.branch:
        _event(
            asset,
            AssetEvent.Kind.MOVED,
            by=by,
            on=_today(company),
            from_branch=old_branch,
            to_branch=asset.branch,
        )
    changes = {
        name: [before[name], _plain(getattr(asset, name))]
        for name in fields
        if before[name] != _plain(getattr(asset, name))
    }
    if facts:
        # Nothing is booked yet: the entries follow the corrected facts.
        asset.entries.all().delete()
        if asset.in_service_on and not asset.events.filter(kind=AssetEvent.Kind.IN_SERVICE):
            _event(asset, AssetEvent.Kind.IN_SERVICE, by=by, on=asset.in_service_on)
    if changes:
        _audit(AssetAction.CHANGED, company, by, asset, changes=changes)
    _repost(asset)
    _bump(company)
    return asset


def _purchases_of(asset: Asset) -> list:
    """The Finance expenses it was bought or improved with."""
    rows = [asset.purchase_transaction] if asset.purchase_transaction_id else []
    events = asset.events.filter(transaction__isnull=False).select_related("transaction")
    return rows + [event.transaction for event in events]


def _check_books_switch(asset: Asset, *, on: bool) -> None:
    """Booking its depreciation follows its purchases in Finance: a capitalized one comes back
    to the P&L only through depreciation, and one still an expense must not come back twice."""
    if on == asset.books_depreciation:
        return
    purchases = _purchases_of(asset)
    if not on and any(txn.capitalized for txn in purchases):
        raise DomainError(
            _(
                "Its purchase left the P&L and comes back as depreciation: booking it can't be "
                "switched off."
            )
        )
    if on and any(not txn.capitalized for txn in purchases):
        raise DomainError(
            _(
                "Its purchase is already a cost in the P&L: booking its depreciation too would "
                "count it twice."
            )
        )


def _plain(value) -> str:
    if hasattr(value, "pk"):
        return str(value.pk)
    return "" if value is None else str(value)


@transaction.atomic
def put_into_service(asset: Asset, *, by: Membership, on: date) -> Asset:
    asset = _lock(asset)
    _live(asset)
    _check_day(asset.company, on, name=_("The start"), future_days=366)
    if asset.in_service_on is not None and _booked(asset):
        raise DomainError(_("It is already in service and depreciating."))
    asset.in_service_on = on
    if asset.purchased_on and on < asset.purchased_on:
        raise DomainError(_("It can't be put into service before it was bought."))
    asset.status = Asset.Status.IN_USE
    if asset.service_months and not asset.next_service_on:
        asset.next_service_on = _add_months(on, asset.service_months)
    if asset.verify_months and not asset.next_verification_on:
        asset.next_verification_on = _add_months(on, asset.verify_months)
    asset.save()
    asset.entries.filter(transaction__isnull=True).delete()
    _event(asset, AssetEvent.Kind.IN_SERVICE, by=by, on=on)
    _audit(AssetAction.EVENT, asset.company, by, asset, kind="in_service", on=str(on))
    _repost(asset)
    _bump(asset.company)
    return asset


@transaction.atomic
def set_status(asset: Asset, *, by: Membership, status: str, on: date, note: str = "") -> Asset:
    """In use, in storage or under repair (mothballing and disposal have their own steps)."""
    asset = _lock(asset)
    _check_day(asset.company, on, name=_("The day"))
    _live(asset)
    allowed = (Asset.Status.IN_USE, Asset.Status.IN_STORAGE, Asset.Status.REPAIR)
    if status not in allowed:
        raise DomainError(_("Pick in use, in storage or under repair."))
    if asset.status == Asset.Status.SUSPENDED:
        raise DomainError(_("It is mothballed: bring it back into use first."))
    if status == asset.status:
        return asset
    before = asset.status
    asset.status = status
    asset.save(update_fields=["status", "updated_at"])
    kind = AssetEvent.Kind.PROBLEM if status == Asset.Status.REPAIR else AssetEvent.Kind.NOTE
    _event(asset, kind, by=by, on=on, note=note[:500], details={"status": [before, status]})
    _audit(AssetAction.EVENT, asset.company, by, asset, kind="status", status=[before, status])
    _bump(asset.company)
    return asset


@transaction.atomic
def move(asset: Asset, *, by: Membership, branch, on: date, note: str = "") -> Asset:
    asset = _lock(asset)
    _check_day(asset.company, on, name=_("The day"))
    _live(asset)
    _same_company(asset.company, branch)
    if branch == asset.branch:
        raise DomainError(_("It is already there."))
    old = asset.branch
    asset.branch = branch
    asset.save(update_fields=["branch", "updated_at"])
    _event(asset, AssetEvent.Kind.MOVED, by=by, on=on, from_branch=old, to_branch=branch, note=note)
    _audit(
        AssetAction.EVENT,
        asset.company,
        by,
        asset,
        kind="moved",
        branch=[old.name if old else "", branch.name if branch else ""],
    )
    _bump(asset.company)
    return asset


# Who holds it -----------------------------------------------------------------------------------


def handout_photo(file):
    """A photo taken when something is given or comes back, decoded and re-encoded (nothing of
    the original file is kept). Raises `InvalidUpload` for anything that isn't a picture."""
    from apps.core.uploads import sanitize_image

    return sanitize_image(file)


def _save_photo(assignment: AssetAssignment, field: str, photo) -> None:
    """`photo`: a file `handout_photo` made, or the name of one already stored (the photo of
    several things given in one go is stored once)."""
    if photo in (None, ""):
        return
    target = getattr(assignment, field)
    if isinstance(photo, str):
        target.name = photo
    else:
        target.save(photo.name, photo, save=False)
    assignment.save(update_fields=[field, "updated_at"])


def _open_assignment(
    asset, membership, *, by, on, condition="", note="", photo=None, notify=True
) -> AssetAssignment:
    assignment = AssetAssignment.objects.create(
        company=asset.company,
        asset=asset,
        membership=membership,
        issued_on=on,
        issued_by=_user(by),
        condition_out=condition or asset.condition,
        note_out=note[:300],
    )
    _save_photo(assignment, "photo_out", photo)
    _event(asset, AssetEvent.Kind.ISSUED, by=by, on=on, membership=membership, note=note[:500])
    if notify:
        from apps.assets import notify as notices

        transaction.on_commit(lambda: notices.issued(assignment.pk))
    return assignment


@transaction.atomic
def issue(
    asset: Asset,
    *,
    by: Membership,
    membership: Membership,
    on: date,
    condition="",
    note="",
    photo=None,
    notify: bool = True,
) -> AssetAssignment:
    """Give the asset to someone (a laptop, the keys, a uniform): they confirm in the app.
    `photo` is how it looked when given (`handout_photo`); `notify=False` when the caller
    tells the person about several things at once (`notify.issued_many`)."""
    asset = _lock(asset)
    _check_day(asset.company, on, name=_("The day"))
    _live(asset)
    membership = _member(asset.company, membership)
    holder = asset.assignments.filter(returned_on__isnull=True).first()
    if holder is not None:
        raise DomainError(
            _("%(person)s has it now: take it back first.") % {"person": holder.membership}
        )
    if condition and condition not in Asset.Condition.values:
        raise DomainError(_("Pick a condition from the list."))
    assignment = _open_assignment(
        asset,
        membership,
        by=by,
        on=on,
        condition=condition,
        note=note,
        photo=photo,
        notify=notify,
    )
    asset.custodian = membership
    if condition:
        asset.condition = condition
    asset.save(update_fields=["custodian", "condition", "updated_at"])
    _audit(AssetAction.ISSUED, asset.company, by, asset, to=str(membership), on=str(on))
    _bump(asset.company)
    return assignment


@transaction.atomic
def acknowledge(assignment: AssetAssignment, *, by: Membership) -> AssetAssignment:
    """The holder confirms they got it, in the state written down."""
    assignment = AssetAssignment.objects.select_for_update().get(pk=assignment.pk)
    if by is None or assignment.membership_id != by.pk:
        raise DomainError(_("Only the person who got it can confirm it."))
    if assignment.returned_on is not None:
        raise DomainError(_("It was already handed back."))
    if assignment.acknowledged_at is None:
        assignment.acknowledged_at = timezone.now()
        assignment.save(update_fields=["acknowledged_at", "updated_at"])
        _bump(assignment.company)
    return assignment


@transaction.atomic
def take_back(
    asset: Asset, *, by: Membership, on: date, condition="", note="", photo=None
) -> AssetAssignment:
    """It comes back, in `condition` (`photo`: how it looked, `handout_photo`)."""
    asset = _lock(asset)
    _check_day(asset.company, on, name=_("The day"))
    assignment = asset.assignments.select_for_update().filter(returned_on__isnull=True).first()
    if assignment is None:
        raise DomainError(_("Nobody holds it."))
    if condition and condition not in Asset.Condition.values:
        raise DomainError(_("Pick a condition from the list."))
    if on < assignment.issued_on:
        raise DomainError(_("It can't come back before it was given."))
    assignment.returned_on = on
    assignment.condition_in = condition or asset.condition
    assignment.note_in = note[:300]
    assignment.received_by = _user(by)
    assignment.save()
    _save_photo(assignment, "photo_in", photo)
    asset.custodian = None
    if condition:
        asset.condition = condition
    asset.save(update_fields=["custodian", "condition", "updated_at"])
    _event(
        asset,
        AssetEvent.Kind.RETURNED,
        by=by,
        on=on,
        membership=assignment.membership,
        note=note[:500],
    )
    _audit(AssetAction.RETURNED, asset.company, by, asset, by_whom=str(assignment.membership))
    _bump(asset.company)
    return assignment


@transaction.atomic
def link_deduction(assignment: AssetAssignment, *, by: Membership, deduction_id: int):
    """Remember the deduction proposed to payroll for what was lost or damaged on this
    hand-out (a payroll Adjustment's id; payroll decides it)."""
    assignment = AssetAssignment.objects.select_for_update().get(pk=assignment.pk)
    assignment.deduction_id = deduction_id
    assignment.save(update_fields=["deduction_id", "updated_at"])
    _audit(
        AssetAction.EVENT,
        assignment.company,
        by,
        assignment.asset,
        kind="deduction",
        person=str(assignment.membership),
    )
    _bump(assignment.company)
    return assignment


# Upkeep -----------------------------------------------------------------------------------------


@transaction.atomic
def record_service(asset: Asset, *, by: Membership, on: date, note="", amount=None) -> AssetEvent:
    asset = _lock(asset)
    _live(asset)
    _check_day(asset.company, on, name=_("The day"))
    cost = _money(amount, name=_("Cost"), allow_zero=True) if amount not in (None, "") else None
    event = _event(asset, AssetEvent.Kind.SERVICE, by=by, on=on, amount=cost, note=note[:500])
    if asset.service_months:
        asset.next_service_on = _add_months(on, asset.service_months)
        asset.save(update_fields=["next_service_on", "updated_at"])
    _audit(AssetAction.EVENT, asset.company, by, asset, kind="service", on=str(on))
    _bump(asset.company)
    return event


@transaction.atomic
def record_verification(
    asset: Asset, *, by: Membership, on: date, valid_until: date | None = None, note=""
) -> AssetEvent:
    """An official check of a measuring instrument (thermometer, hygrometer, scales)."""
    asset = _lock(asset)
    _live(asset)
    _check_day(asset.company, on, name=_("The day"))
    if valid_until is None and asset.verify_months:
        valid_until = _add_months(on, asset.verify_months)
    if valid_until is not None and valid_until <= on:
        raise DomainError(_("Valid until is after the check."))
    event = _event(
        asset,
        AssetEvent.Kind.VERIFICATION,
        by=by,
        on=on,
        note=note[:500],
        details={"valid_until": valid_until.isoformat() if valid_until else None},
    )
    asset.next_verification_on = valid_until
    asset.save(update_fields=["next_verification_on", "updated_at"])
    _audit(AssetAction.EVENT, asset.company, by, asset, kind="verification", on=str(on))
    _bump(asset.company)
    return event


@transaction.atomic
def record_repair(
    asset: Asset, *, by: Membership, on: date, amount=None, note="", improves: bool = False
) -> AssetEvent:
    """A repair. An ordinary one is a cost of its month (record the payment in Finance under
    Repairs); one that improves the asset or makes it last longer adds to its cost instead."""
    asset = _lock(asset)
    _live(asset)
    _check_day(asset.company, on, name=_("The day"))
    cost = _money(amount, name=_("Cost"), allow_zero=True) if amount not in (None, "") else None
    if improves and not cost:
        raise DomainError(_("Give what the improvement cost."))
    event = _event(
        asset,
        AssetEvent.Kind.REPAIR,
        by=by,
        on=on,
        amount=cost,
        note=note[:500],
        details={"improves": improves},
    )
    if improves:
        _event(asset, AssetEvent.Kind.ADDITION, by=by, on=on, amount=cost, note=note[:500])
    if asset.status == Asset.Status.REPAIR:
        asset.status = Asset.Status.IN_USE
        asset.save(update_fields=["status", "updated_at"])
    _audit(AssetAction.EVENT, asset.company, by, asset, kind="repair", amount=str(cost or ""))
    _repost(asset)
    _bump(asset.company)
    return event


# Value -----------------------------------------------------------------------------------------


def months_used(asset: Asset) -> int:
    """Months of its life already depreciated (posted, or before it was entered here)."""
    entries = asset.entries.all()
    if asset.opening_accumulated is not None and asset.in_service_on:
        lump = entries.filter(opening=True).first()
        first = engine.first_month(posting.facts_of(asset))
        before = engine.months_between(first, engine.add_months(lump.month, 1)) if lump else 0
        return max(before, 0) + entries.filter(opening=False).count()
    return entries.count()


def book_value(asset: Asset) -> Decimal:
    """Its value now: cost, plus improvements, minus write-downs and depreciation posted."""
    from django.db.models import Sum

    entries = asset.entries.aggregate(total=Sum("amount"))["total"] or Decimal(0)
    sums = {
        kind: asset.events.filter(kind=kind).aggregate(total=Sum("amount"))["total"] or Decimal(0)
        for kind in (AssetEvent.Kind.ADDITION, AssetEvent.Kind.IMPAIRMENT)
    }
    return quantize(
        asset.cost + sums[AssetEvent.Kind.ADDITION] - sums[AssetEvent.Kind.IMPAIRMENT] - entries
    )


@transaction.atomic
def add_to_cost(asset: Asset, *, by: Membership, on: date, amount, note="", purchase=None):
    """An improvement (a new compressor, an extra shelf section): its cost joins the asset's
    and depreciates over the life left, from the next month. With `purchase`, that expense
    leaves the P&L like the asset's own purchase."""
    asset = _lock(asset)
    _live(asset)
    _check_day(asset.company, on, name=_("The day"))
    value = _money(amount, name=_("Cost"))
    txn = _purchase(asset.company, purchase)
    if txn is not None and value != -txn.base_amount:
        raise DomainError(_("The amount must be the whole expense."))
    event = _event(
        asset,
        AssetEvent.Kind.ADDITION,
        by=by,
        on=on,
        amount=value,
        note=note[:500],
        transaction=txn,
    )
    if txn is not None and asset.books_depreciation:
        from apps.finance import services as finance

        finance.capitalize(txn, by=by)
    _audit(AssetAction.EVENT, asset.company, by, asset, kind="addition", amount=str(value))
    _repost(asset)
    _bump(asset.company)
    return event


@transaction.atomic
def write_down(asset: Asset, *, by: Membership, on: date, amount, note="") -> AssetEvent:
    """Its value fell for good (damage, a cheaper model on the market): the loss is a cost of
    this month, and later months depreciate the lower value."""
    asset = _lock(asset)
    _live(asset)
    _check_day(asset.company, on, name=_("The day"))
    value = _money(amount, name=_("Amount"))
    posting.post_asset(asset)
    if value > book_value(asset):
        raise DomainError(
            _("It is worth %(value)s now: write down at most that.") % {"value": book_value(asset)}
        )
    event = _event(asset, AssetEvent.Kind.IMPAIRMENT, by=by, on=on, amount=value, note=note[:500])
    posting.book_asset_cost(
        asset,
        amount=value,
        day=on,
        key=f"w:{event.pk}",
        description=posting.text_written_down(asset),
    )
    _audit(AssetAction.EVENT, asset.company, by, asset, kind="impairment", amount=str(value))
    _repost(asset)
    _bump(asset.company)
    return event


@transaction.atomic
def change_estimate(
    asset: Asset,
    *,
    by: Membership,
    on: date,
    life_months: int | None = None,
    salvage_value=None,
    method: str | None = None,
    note: str = "",
) -> AssetEvent:
    """A new useful life (in total, from the start), residual value or method, from the first
    month not posted yet. Earlier months stay as they were."""
    asset = _lock(asset)
    _check_day(asset.company, on, name=_("The day"))
    _live(asset)
    if life_months is None and salvage_value in (None, "") and method is None:
        raise DomainError(_("Change the useful life, the residual value or the method."))
    old, new = {}, {}
    if life_months is not None:
        life_months = int(life_months)
        used = months_used(asset)
        if not 1 <= life_months <= 1200:
            raise DomainError(_("A useful life is 1 to 1200 months."))
        if life_months <= used:
            raise DomainError(
                _("It has depreciated for %(months)s months already: give a longer life.")
                % {"months": used}
            )
        old["life_months"], new["life_months"] = asset.life_months, life_months
        asset.life_months = life_months
    if salvage_value not in (None, ""):
        value = _money(salvage_value, name=_("Residual value"), allow_zero=True)
        if value > book_value(asset):
            raise DomainError(_("The residual value can't be above what it is worth now."))
        old["salvage_value"], new["salvage_value"] = str(asset.salvage_value), str(value)
        asset.salvage_value = value
    if method is not None:
        if method not in Method.values or (method == Method.UNITS and not asset.total_units):
            raise DomainError(_("Pick a method from the list."))
        old["method"], new["method"] = asset.method, method
        asset.method = method
    _check_facts(asset)
    asset.save()
    event = _event(
        asset,
        AssetEvent.Kind.ESTIMATE,
        by=by,
        on=on,
        note=note[:500],
        details={"old": old, "new": new},
    )
    _audit(
        AssetAction.EVENT,
        asset.company,
        by,
        asset,
        kind="estimate",
        changes={key: [str(old[key]), str(new[key])] for key in new},
    )
    _repost(asset)
    _bump(asset.company)
    return event


@transaction.atomic
def suspend(asset: Asset, *, by: Membership, on: date, note="") -> AssetEvent:
    """Mothballed (konservatsiya): no depreciation from the next month, and its life waits."""
    asset = _lock(asset)
    _check_day(asset.company, on, name=_("The day"))
    _live(asset)
    if asset.status == Asset.Status.SUSPENDED:
        raise DomainError(_("It is already mothballed."))
    asset.status = Asset.Status.SUSPENDED
    asset.save(update_fields=["status", "updated_at"])
    event = _event(asset, AssetEvent.Kind.SUSPENDED, by=by, on=on, note=note[:500])
    _audit(AssetAction.EVENT, asset.company, by, asset, kind="suspended", on=str(on))
    _bump(asset.company)
    return event


@transaction.atomic
def resume(asset: Asset, *, by: Membership, on: date, note="") -> AssetEvent:
    asset = _lock(asset)
    _check_day(asset.company, on, name=_("The day"))
    if asset.status != Asset.Status.SUSPENDED:
        raise DomainError(_("It isn't mothballed."))
    suspended = asset.events.filter(kind=AssetEvent.Kind.SUSPENDED).order_by("-on").first()
    if suspended is not None and on < suspended.on:
        raise DomainError(_("It can't come back before it was mothballed."))
    asset.status = Asset.Status.IN_USE
    asset.save(update_fields=["status", "updated_at"])
    event = _event(asset, AssetEvent.Kind.RESUMED, by=by, on=on, note=note[:500])
    _audit(AssetAction.EVENT, asset.company, by, asset, kind="resumed", on=str(on))
    _repost(asset)
    _bump(asset.company)
    return event


@transaction.atomic
def record_usage(asset: Asset, *, by: Membership, on: date, units) -> AssetEvent:
    """Units of output in a month (kilometres, hours) for the units method."""
    asset = _lock(asset)
    _check_day(asset.company, on, name=_("The day"))
    _live(asset)
    if asset.method != Method.UNITS:
        raise DomainError(_("Only an asset depreciated by units of output records units."))
    try:
        value = Decimal(str(units).replace(",", "."))
    except InvalidOperation as exc:
        raise DomainError(_("Give a number.")) from exc
    if value <= 0:
        raise DomainError(_("Give a number above zero."))
    month = engine.first_of(on)
    if asset.entries.filter(month=month).exists():
        raise DomainError(_("That month is already posted."))
    event = _event(asset, AssetEvent.Kind.USAGE, by=by, on=on, units=value)
    _audit(AssetAction.EVENT, asset.company, by, asset, kind="usage", units=str(value))
    _bump(asset.company)
    return event


# Disposal and deletion --------------------------------------------------------------------------


@transaction.atomic
def dispose(
    asset: Asset,
    *,
    by: Membership,
    on: date,
    kind: str,
    amount=None,
    account=None,
    reason: str = "",
) -> Asset:
    """Sold, written off, lost or given away. Its depreciation runs through the month (the
    company's rule), what it was still worth becomes a cost of that day, and a sale's money
    comes in on `account` as income: the P&L shows the gain or the loss."""
    asset = _lock(asset)
    _live(asset)
    company = asset.company
    if kind not in Asset.Disposal.values:
        raise DomainError(_("Pick how it left from the list."))
    _check_day(company, on, name=_("The day"))
    start = asset.in_service_on or asset.purchased_on
    if start and on < start:
        raise DomainError(_("It can't leave before it arrived."))
    proceeds = None
    if amount not in (None, ""):
        proceeds = _money(amount, name=_("Amount"), allow_zero=True)
    if kind == Asset.Disposal.SOLD and not proceeds:
        raise DomainError(_("Give what it was sold for."))
    if proceeds and kind != Asset.Disposal.SOLD:
        raise DomainError(_("Only a sale brings money in."))
    if account is not None:
        _same_company(company, account)
    if not reason.strip() and kind != Asset.Disposal.SOLD:
        raise DomainError(_("Say why it is written off."))
    last = asset.entries.order_by("-month").values_list("month", flat=True).first()
    if last is not None and engine.first_of(on) < last:
        raise DomainError(_("Its depreciation is posted after that day: pick a later day."))
    asset.disposed_on = on
    asset.disposal = kind
    asset.disposal_amount = proceeds
    asset.disposal_reason = reason.strip()[:300]
    asset.status = Asset.Status.DISPOSED
    asset.save()
    posting.post_asset(asset, through=engine.first_of(on))
    posting.book_company(company)
    value = book_value(asset)
    posting.book_asset_cost(
        asset, amount=value, day=on, key="disposal", description=posting.text_written_off(asset)
    )
    # The money comes in whether or not its depreciation is booked (an asset whose purchase was
    # an expense sells at a gain of all of it).
    if proceeds and account is not None and posting.finance_on(company):
        from apps.finance import services as finance
        from apps.finance.sources import Source

        row = finance.record_transaction(
            company,
            by=by,
            kind="income",
            amount=proceeds,
            occurred_on=posting.booking_day(company, on),
            account=account,
            category="asset_sale",
            branch=asset.branch,
            description=_("Sold: %(asset)s") % {"asset": f"{asset.number} {asset.name}"},
            source=Source(posting.SOURCE_ASSET, asset.pk, "sale"),
        )
        asset.disposal_transaction = row
        asset.save(update_fields=["disposal_transaction", "updated_at"])
    holder = asset.assignments.filter(returned_on__isnull=True).first()
    if holder is not None:
        holder.returned_on = on
        holder.note_in = _("Disposed of")
        holder.save(update_fields=["returned_on", "note_in", "updated_at"])
        asset.custodian = None
        asset.save(update_fields=["custodian", "updated_at"])
    result = (proceeds or Decimal(0)) - value
    _event(
        asset,
        AssetEvent.Kind.DISPOSED,
        by=by,
        on=on,
        amount=proceeds,
        note=asset.disposal_reason,
        details={"kind": kind, "book_value": str(value), "result": str(quantize(result))},
    )
    _audit(
        AssetAction.DISPOSED,
        company,
        by,
        asset,
        kind=kind,
        book_value=str(value),
        amount=str(proceeds or ""),
    )
    _bump(company)
    return asset


@transaction.atomic
def delete_asset(asset: Asset, *, by: Membership) -> None:
    """Remove an asset entered by mistake: only while nothing of it is in Finance."""
    asset = _lock(asset)
    if _booked(asset):
        raise DomainError(
            _("Its depreciation is in the books: dispose of it instead of deleting it.")
        )
    txn = asset.purchase_transaction
    if txn is not None and txn.capitalized:
        from apps.finance import services as finance

        try:
            finance.capitalize(txn, by=by, capitalized=False)
        except DomainError as exc:
            raise DomainError(
                _("Its purchase is in closed books: dispose of it instead of deleting it.")
            ) from exc
    for event in asset.events.filter(transaction__isnull=False).select_related("transaction"):
        if event.kind == AssetEvent.Kind.ADDITION and event.transaction.capitalized:
            from apps.finance import services as finance

            finance.capitalize(event.transaction, by=by, capitalized=False)
    company = asset.company
    files = [row.file.name for row in asset.files.all() if row.file]
    _audit(AssetAction.DELETED, company, by, asset, number=asset.number, name=asset.name)
    asset.entries.all().delete()
    asset.delete()
    if files:
        from apps.core.storage import private_storage

        transaction.on_commit(lambda: [private_storage.delete(name) for name in files])
    _bump(company)


# Files -----------------------------------------------------------------------------------------


@transaction.atomic
def add_file(asset: Asset, *, by: Membership, file, kind: str, label: str = "") -> AssetFile:
    from apps.core.uploads import accept_document, sanitize_image

    if kind not in AssetFile.Kind.values:
        raise DomainError(_("A photo or a document."))
    if asset.files.count() >= 30:
        raise DomainError(_("At most 30 files per asset."))
    clean = (
        sanitize_image(file)
        if kind == AssetFile.Kind.PHOTO
        else accept_document(file, allowed=("pdf", "image"))
    )
    row = AssetFile.objects.create(
        company=asset.company,
        asset=asset,
        kind=kind,
        label=" ".join(str(label or "").split())[:120],
        uploaded_by=_user(by),
    )
    row.file.save(clean.name, clean, save=True)
    _audit(AssetAction.FILE_ADDED, asset.company, by, asset, kind=kind)
    _bump(asset.company)
    return row


@transaction.atomic
def remove_file(row: AssetFile, *, by: Membership) -> None:
    name = row.file.name
    asset = row.asset
    row.delete()
    if name:
        from apps.core.storage import private_storage

        transaction.on_commit(lambda: private_storage.delete(name))
    _audit(AssetAction.FILE_REMOVED, asset.company, by, asset, kind=row.kind)
    _bump(asset.company)


# Counts (inventarizatsiya) -----------------------------------------------------------------------


@transaction.atomic
def start_count(company, *, by: Membership, branch=None, note: str = "") -> AssetCount:
    """A count of a branch's assets (or all of them): one line per asset that should be there."""
    _same_company(company, branch)
    open_count = AssetCount.objects.filter(
        company=company, branch=branch, status=AssetCount.Status.OPEN
    )
    if open_count.exists():
        raise DomainError(_("A count of this place is already in progress."))
    assets = Asset.objects.for_company(company).exclude(status=Asset.Status.DISPOSED)
    if branch is not None:
        assets = assets.filter(branch=branch)
    if not assets.exists():
        raise DomainError(_("There is nothing to count here yet."))
    count = AssetCount.objects.create(
        company=company,
        branch=branch,
        started_on=_today(company),
        started_by=_user(by),
        note=note[:300],
    )
    AssetCountLine.objects.bulk_create(
        [AssetCountLine(company=company, count=count, asset=asset) for asset in assets]
    )
    _audit(AssetAction.COUNT_STARTED, company, by, count, branch=branch.name if branch else "")
    _bump(company)
    return count


@transaction.atomic
def mark(line: AssetCountLine, *, by: Membership, result: str, note: str = "") -> AssetCountLine:
    line = AssetCountLine.objects.select_for_update().select_related("count").get(pk=line.pk)
    if line.count.status != AssetCount.Status.OPEN:
        raise DomainError(_("This count is closed."))
    if result not in AssetCountLine.Result.values:
        raise DomainError(_("Pick a result from the list."))
    line.result = result
    line.note = note[:300]
    line.checked_by = by
    line.checked_at = timezone.now() if result != AssetCountLine.Result.PENDING else None
    line.save()
    _bump(line.company)
    return line


@transaction.atomic
def close_count(count: AssetCount, *, by: Membership) -> dict:
    """Close a count: found ones get a line on their timeline, damaged ones their condition,
    missing ones stay for the owner to decide (write off as lost, or look further)."""
    count = AssetCount.objects.select_for_update().get(pk=count.pk)
    if count.status != AssetCount.Status.OPEN:
        raise DomainError(_("This count is closed."))
    today = _today(count.company)
    summary = {"found": 0, "damaged": 0, "missing": 0, "pending": 0}
    for line in count.lines.select_related("asset"):
        summary[line.result] += 1
        if line.result in (AssetCountLine.Result.FOUND, AssetCountLine.Result.DAMAGED):
            _event(line.asset, AssetEvent.Kind.COUNTED, by=by, on=today, note=line.note)
        if line.result == AssetCountLine.Result.DAMAGED:
            line.asset.condition = Asset.Condition.DAMAGED
            line.asset.save(update_fields=["condition", "updated_at"])
        if line.result == AssetCountLine.Result.MISSING:
            _event(
                line.asset,
                AssetEvent.Kind.NOTE,
                by=by,
                on=today,
                note=_("Not found in the count of %(day)s.") % {"day": today.strftime("%d.%m.%Y")},
                details={"count": count.pk, "missing": True},
            )
    count.status = AssetCount.Status.CLOSED
    count.closed_at = timezone.now()
    count.closed_by = _user(by)
    count.save()
    _audit(AssetAction.COUNT_CLOSED, count.company, by, count, **summary)
    _bump(count.company)
    return summary


# Licences and permits ---------------------------------------------------------------------------

PERMIT_FIELDS = (
    "kind",
    "name",
    "number",
    "issuer",
    "issued_on",
    "valid_until",
    "remind_days",
    "responsible",
    "notes",
    "branch",
)


@transaction.atomic
def save_permit(company, *, by: Membership, permit: Permit | None = None, **fields) -> Permit:
    """Add a licence or permit, or change one (what it is, where, until when)."""
    unknown = set(fields) - set(PERMIT_FIELDS)
    if unknown:
        raise ValueError(f"Unknown permit fields: {sorted(unknown)}")
    _same_company(company, fields.get("branch"))
    if "responsible" in fields:
        fields["responsible"] = _member(company, fields["responsible"])
    if "name" in fields:
        fields["name"] = " ".join(str(fields["name"] or "").split())[:120]
    if (permit is None and not fields.get("name")) or ("name" in fields and not fields["name"]):
        raise DomainError(_("Give it a name."))
    if "kind" in fields and fields["kind"] not in Permit.Kind.values:
        raise DomainError(_("Pick a kind from the list."))
    if "remind_days" in fields and not 1 <= int(fields["remind_days"]) <= 365:
        raise DomainError(_("Warn 1 to 365 days ahead."))
    issued = fields.get("issued_on", permit.issued_on if permit else None)
    until = fields.get("valid_until", permit.valid_until if permit else None)
    if issued and until and until <= issued:
        raise DomainError(_("It ends after it was issued."))
    created = permit is None
    if created:
        permit = Permit(company=company, created_by=_user(by))
    before = {name: _plain(getattr(permit, name)) for name in fields} if not created else {}
    for name, value in fields.items():
        setattr(permit, name, value)
    permit.save()
    changes = {
        name: [before[name], _plain(getattr(permit, name))]
        for name in before
        if before[name] != _plain(getattr(permit, name))
    }
    _audit(
        AssetAction.PERMIT_SAVED,
        company,
        by,
        permit,
        name=permit.name,
        created=created,
        changes=changes,
    )
    _bump(company)
    return permit


@transaction.atomic
def attach_permit_file(permit: Permit, *, by: Membership, file) -> Permit:
    from apps.core.uploads import accept_document

    clean = accept_document(file, allowed=("pdf", "image"))
    old = permit.file.name if permit.file else ""
    permit.file.save(clean.name, clean, save=True)
    if old:
        from apps.core.storage import private_storage

        transaction.on_commit(lambda: private_storage.delete(old))
    _audit(AssetAction.PERMIT_SAVED, permit.company, by, permit, name=permit.name, file=True)
    _bump(permit.company)
    return permit


@transaction.atomic
def delete_permit(permit: Permit, *, by: Membership) -> None:
    company = permit.company
    name = permit.file.name if permit.file else ""
    _audit(AssetAction.PERMIT_DELETED, company, by, permit, name=permit.name)
    permit.delete()
    if name:
        from apps.core.storage import private_storage

        transaction.on_commit(lambda: private_storage.delete(name))
    _bump(company)
