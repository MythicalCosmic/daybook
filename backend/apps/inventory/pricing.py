"""Retail prices and the legal caps (docs/PLAN-OWNER.md §14.4 rows 13-14, §14.6.2).

Prices are per pack and per batch, because a prescription medicine's cap is a markup on that
batch's purchase price. A new batch's price is its cost times one plus the markup (the first
matching pricing rule, else the company's OTC markup), rounded **up** to `price_rounding`;
for a prescription medicine it is then capped at cost x (1 + the Rx cap, or the socially
significant one), rounded **down**, and at the product's reference price when one is set.

    OTC cost 10 340 at 25 %                → 12 925 → 13 000
    Rx cost 10 340 (cap 20 %)              → 12 408 → 12 400
    the same with a reference price 12 000 →          12 000
    socially significant cost 10 340       → 11 374 → 11 300
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from apps.core.money import quantize

HUNDRED = Decimal(100)


def round_up(amount, step) -> Decimal:
    amount, step = Decimal(amount), Decimal(step or 0)
    if step <= 0:
        return quantize(amount)
    return quantize((amount / step).to_integral_value(rounding=ROUND_CEILING) * step)


def round_down(amount, step) -> Decimal:
    amount, step = Decimal(amount), Decimal(step or 0)
    if step <= 0:
        return quantize(amount)
    return quantize((amount / step).to_integral_value(rounding=ROUND_FLOOR) * step)


def cap_percent(product, settings) -> Decimal:
    if product.socially_significant:
        return Decimal(settings.social_max_markup_percent)
    return Decimal(settings.rx_max_markup_percent)


def legal_cap(product, unit_cost, settings) -> Decimal | None:
    """The legal maximum price of one pack, unrounded; None when the law sets none (an OTC
    item, or a prescription item with neither a cost nor a reference price)."""
    if not product.rx_required:
        return None
    caps = []
    if unit_cost is not None:
        caps.append(quantize(Decimal(unit_cost) * (1 + cap_percent(product, settings) / HUNDRED)))
    if product.reference_price is not None:
        caps.append(Decimal(product.reference_price))
    return min(caps) if caps else None


def price_ceiling(product, unit_cost, settings) -> Decimal | None:
    """The highest price the shop may put on a pack: the markup cap rounded down to the
    rounding step, never above the reference price (which is used as it is)."""
    if not product.rx_required:
        return None
    caps = []
    if unit_cost is not None:
        raw = Decimal(unit_cost) * (1 + cap_percent(product, settings) / HUNDRED)
        caps.append(round_down(raw, settings.price_rounding))
    if product.reference_price is not None:
        caps.append(Decimal(product.reference_price))
    return min(caps) if caps else None


def markup_for(product, unit_cost, settings, rules=None) -> Decimal:
    """The first active pricing rule for the product's category (or its group, or every
    category) whose cost band holds `unit_cost`; else the company's OTC markup."""
    if rules is None:
        from apps.inventory.models import PricingRule

        rules = PricingRule.objects.for_company(product.company_id).filter(is_active=True)
    category = product.category
    categories = {None}
    if category is not None:
        categories |= {category.pk, category.parent_id}
    cost = Decimal(unit_cost)
    for rule in sorted(rules, key=lambda rule: (rule.order, rule.pk)):
        if not rule.is_active or rule.category_id not in categories:
            continue
        if rule.cost_from is not None and cost < rule.cost_from:
            continue
        if rule.cost_to is not None and cost > rule.cost_to:
            continue
        return Decimal(rule.markup_percent)
    return Decimal(settings.default_markup_percent)


def suggest_price(product, unit_cost, settings, *, wanted=None, rules=None) -> tuple[Decimal, bool]:
    """The retail price of a new batch costing `unit_cost` a pack, and whether a legal cap
    lowered it. `wanted` is a price someone typed (kept unless it crosses the cap)."""
    if wanted is not None:
        price = quantize(Decimal(wanted))
    else:
        markup = markup_for(product, unit_cost, settings, rules)
        price = round_up(Decimal(unit_cost) * (1 + markup / HUNDRED), settings.price_rounding)
    ceiling = price_ceiling(product, unit_cost, settings)
    if ceiling is not None and price > ceiling:
        return ceiling, True
    return price, False


def part_price(product, batch=None, settings=None) -> Decimal:
    """The price of one part: the product's own part price, else the pack price divided by
    the parts and rounded up; for a prescription item rounded down instead when rounding up
    would put the part above its share of the cap.

        pack 24 000, 2 parts                       → 12 000
        pack 25 150, 10 parts                      → 2 515 → 2 600
        Rx pack 12 400 at cost 10 340, 3 parts     → 4 133.33 (cap 4 136) → 4 100
    """
    if product.part_price is not None:
        return product.part_price
    if settings is None:
        from apps.inventory import conf

        settings = conf.get_settings(product.company)
    pack = batch.retail_price if batch is not None else product.sale_price
    count = max(product.units_per_pack, 1)
    if count == 1:
        return quantize(pack)
    raw = Decimal(pack) / count
    up = round_up(raw, settings.price_rounding)
    if product.rx_required:
        cap = legal_cap(product, batch.unit_cost if batch is not None else None, settings)
        if cap is not None and up > cap / count:
            return round_down(raw, settings.price_rounding)
    return up
