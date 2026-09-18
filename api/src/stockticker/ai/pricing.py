"""List prices for the Claude models `AI_MODEL` may name, in USD per million tokens.

Source: the `claude-api` skill's model table (cached 2026-06-24) and its prompt
caching notes: a 5-minute cache write is 1.25x base input, a cache read is
0.1x (0.025x on Claude Fable 5.1). Ask only writes 5-minute cache entries.

A model missing from `PRICES` has no known cost, so the spend cap cannot be
enforced for it: Ask stays off until a price is added here.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

_PER_TOKEN = Decimal(1_000_000)
_USD_PLACES = Decimal("0.000001")


@dataclass(frozen=True)
class ModelPrice:
    input: Decimal
    cache_write_5m: Decimal
    cache_read: Decimal
    output: Decimal


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_input_tokens(self) -> int:
        return self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.output_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            self.input_tokens + other.input_tokens,
            self.cache_creation_input_tokens + other.cache_creation_input_tokens,
            self.cache_read_input_tokens + other.cache_read_input_tokens,
            self.output_tokens + other.output_tokens,
        )


def _price(input_usd: str, output_usd: str, cache_read_usd: str | None = None) -> ModelPrice:
    base = Decimal(input_usd)
    return ModelPrice(
        input=base,
        cache_write_5m=base * Decimal("1.25"),
        cache_read=Decimal(cache_read_usd) if cache_read_usd is not None else base * Decimal("0.1"),
        output=Decimal(output_usd),
    )


PRICES: dict[str, ModelPrice] = {
    "claude-fable-5-1": _price("10", "50", cache_read_usd="0.25"),
    "claude-fable-5": _price("10", "50"),
    "claude-opus-5": _price("5", "25"),
    "claude-opus-4-8": _price("5", "25"),
    "claude-opus-4-7": _price("5", "25"),
    "claude-opus-4-6": _price("5", "25"),
    "claude-sonnet-5": _price("2", "10"),
    "claude-sonnet-4-6": _price("3", "15"),
    "claude-haiku-4-5": _price("1", "5"),
}


def price_for(model: str) -> ModelPrice | None:
    return PRICES.get(model)


def cost_usd(price: ModelPrice, usage: TokenUsage) -> Decimal:
    """Rounded up to the micro-dollar, so the ledger never under-counts."""
    total = (
        usage.input_tokens * price.input
        + usage.cache_creation_input_tokens * price.cache_write_5m
        + usage.cache_read_input_tokens * price.cache_read
        + usage.output_tokens * price.output
    ) / _PER_TOKEN
    return total.quantize(_USD_PLACES, rounding=ROUND_CEILING)


def worst_case_cost_usd(price: ModelPrice, *, max_input_tokens: int, max_output_tokens: int) -> Decimal:
    """Every input token priced at the most expensive input rate (a cache
    write), plus the full `max_tokens` of output."""
    highest_input_rate = max(price.input, price.cache_write_5m, price.cache_read)
    total = (max_input_tokens * highest_input_rate + max_output_tokens * price.output) / _PER_TOKEN
    return total.quantize(_USD_PLACES, rounding=ROUND_CEILING)
