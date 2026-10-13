"""Candle validation rules.

Each rule looks at one candle (plus context) and returns an Issue or None.
A "reject" issue sends the candle to quarantine; a "flag" issue keeps it but
records why it looked unusual, e.g. a big jump explained by a bonus issue.
"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .entities import Candle, Issue, ValidationResult


@dataclass(frozen=True)
class ValidationContext:
    trading_date: date
    is_trading_day: bool
    price_band_percent: Decimal = Decimal("10")
    cross_source_tolerance_percent: Decimal = Decimal("0.5")
    # Closes from a second source, by symbol, for cross-checking. Optional.
    reference_closes: dict[str, Decimal] = field(default_factory=dict)
    # Symbols with a corporate action (bonus, rights, split) around this date.
    adjusted_symbols: frozenset[str] = frozenset()
    # Previous close by symbol, used when the source didn't report one.
    previous_closes: dict[str, Decimal] = field(default_factory=dict)


def ohlc_consistent(c: Candle, ctx):
    if min(c.open, c.high, c.low, c.close) <= 0:
        return Issue("ohlc_positive", f"non-positive price o={c.open} h={c.high} l={c.low} c={c.close}")
    if not (c.low <= min(c.open, c.close) and max(c.open, c.close) <= c.high):
        return Issue("ohlc_consistent", f"prices outside high/low range o={c.open} h={c.high} l={c.low} c={c.close}")
    return None


def volume_sane(c: Candle, ctx):
    if c.volume < 0:
        return Issue("volume_non_negative", f"volume {c.volume}")
    if c.trades is not None and c.trades < 0:
        return Issue("trades_non_negative", f"trades {c.trades}")
    return None


def turnover_matches(c: Candle, ctx):
    """Turnover must sit between low*volume and high*volume (5% slack for rounding)."""
    if c.turnover is None or c.volume <= 0:
        return None
    lower = c.low * c.volume * Decimal("0.95")
    upper = c.high * c.volume * Decimal("1.05")
    if not (lower <= c.turnover <= upper):
        return Issue("turnover_matches", f"turnover {c.turnover} outside {lower:.0f}-{upper:.0f} for volume {c.volume}")
    return None


def within_price_band(c: Candle, ctx):
    previous = c.previous_close or ctx.previous_closes.get(c.symbol)
    if not previous:
        return None
    move = abs(c.close - previous) / previous * 100
    # Small allowance above the band for rounding of tick sizes.
    if move <= ctx.price_band_percent + Decimal("0.5"):
        return None
    if c.symbol in ctx.adjusted_symbols:
        return Issue("price_band", f"{move:.2f}% move explained by corporate action", severity="flag")
    return Issue("price_band", f"{move:.2f}% move from previous close {previous} exceeds the {ctx.price_band_percent}% band")


def valid_trading_date(c: Candle, ctx):
    if not ctx.is_trading_day:
        return Issue("trading_day", f"{c.trading_date} is not a trading day")
    if c.trading_date > ctx.trading_date:
        return Issue("future_date", f"{c.trading_date} is after {ctx.trading_date}")
    return None


def agrees_with_reference(c: Candle, ctx):
    reference = ctx.reference_closes.get(c.symbol)
    if not reference:
        return None
    diff = abs(c.close - reference) / reference * 100
    if diff > ctx.cross_source_tolerance_percent:
        return Issue("cross_source", f"close {c.close} differs {diff:.2f}% from reference {reference}", severity="flag")
    return None


RULES = [ohlc_consistent, volume_sane, turnover_matches, within_price_band, valid_trading_date, agrees_with_reference]


def validate(candles: list[Candle], ctx: ValidationContext, rules=RULES) -> ValidationResult:
    result = ValidationResult()
    counts = Counter((c.symbol, c.timeframe, c.ts) for c in candles)
    for candle in candles:
        issues = [issue for rule in rules if (issue := rule(candle, ctx))]
        copies = counts[(candle.symbol, candle.timeframe, candle.ts)]
        if copies > 1:
            issues.append(Issue("duplicate_symbol", f"{candle.symbol} appears {copies} times in one fetch"))
        if any(i.severity == "reject" for i in issues):
            result.quarantined.append((candle, issues))
            continue
        result.accepted.append(candle)
        if issues:
            result.flagged.append((candle, issues))
    return result
