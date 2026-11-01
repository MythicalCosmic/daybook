"""What a Claude call costs (docs/PLAN-OWNER.md §8.6), from the 2026-10-06 price list.

Prices are USD per million tokens, so tokens x price is micro-dollars. A call is priced by the
model that answered (`response.model`): a server-side fallback may have served it. With
fallbacks `usage.iterations` is the per-attempt truth, each attempt at its own model's price.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float
    cache_write: float  # 5-minute cache writes: 1.25 x input


def _price(input_: float, output: float, cache_read: float) -> Price:
    return Price(input_, output, cache_read, input_ * 1.25)


PRICES = {
    "claude-fable-5-1": _price(10.00, 50.00, 0.25),
    "claude-fable-5": _price(10.00, 50.00, 0.25),
    "claude-opus-5-5": _price(4.00, 20.00, 0.20),
    "claude-opus-5": _price(5.00, 25.00, 0.50),
    "claude-opus-4-8": _price(5.00, 25.00, 0.50),
    "claude-sonnet-5-5": _price(2.00, 10.00, 0.20),
    "claude-sonnet-5": _price(2.00, 10.00, 0.20),
    "claude-haiku-5-5": _price(0.10, 0.50, 0.01),
}
# An unknown model (a new fallback target) is priced like the dearest current one, so the
# budget errs on the safe side.
UNKNOWN = PRICES["claude-fable-5-1"]


def price_of(model: str) -> Price:
    return PRICES.get(model, UNKNOWN)


def cost_micro_usd(
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> int:
    price = price_of(model)
    return round(
        input_tokens * price.input
        + output_tokens * price.output
        + cache_read_tokens * price.cache_read
        + cache_write_tokens * price.cache_write
    )
