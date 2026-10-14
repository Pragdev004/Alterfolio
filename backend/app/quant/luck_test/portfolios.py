"""Random portfolio construction (spec section 6). Weights are exact Decimals summing to 1; returns stay `Decimal`.

Baseline A weights the selected alternatives (all of them, k = their count). Baseline B first samples distinct stocks
without replacement from an ISIN-sorted pool, then weights them. Draw order inside one portfolio is fixed: sample, then weights.
"""

from collections.abc import Sequence
from decimal import Decimal

from .numeric_boundary import CALC
from .rng import SplitMix64, sample_without_replacement, simplex_weights


def weighted_return(weights: Sequence[Decimal], returns: Sequence[Decimal]) -> Decimal:
    total = Decimal(0)
    for w, r in zip(weights, returns, strict=True):
        total = CALC.add(total, CALC.multiply(w, r))
    return total


def alt_portfolio_returns(rng: SplitMix64, alternative_returns: Sequence[Decimal], count: int) -> tuple[Decimal, ...]:
    """`count` random-weight portfolios over ALL given alternatives (each portfolio draws k fresh simplex weights)."""
    k = len(alternative_returns)
    return tuple(weighted_return(simplex_weights(rng, k), alternative_returns) for _ in range(count))


def nifty_portfolio_returns(
    rng: SplitMix64, pool_returns: Sequence[Decimal], size: int, count: int
) -> tuple[Decimal, ...]:
    """`count` portfolios of `size` distinct stocks from the pool (given in ISIN order), each with random weights."""
    out = []
    for _ in range(count):
        chosen = sample_without_replacement(rng, list(range(len(pool_returns))), size)
        out.append(weighted_return(simplex_weights(rng, size), [pool_returns[i] for i in chosen]))
    return tuple(out)


def compare(actual: Decimal, portfolio_returns: Sequence[Decimal]) -> tuple[int, int, Decimal]:
    """(portfolios the actual return exceeded, portfolios equal to it, mean portfolio return); exact Decimal comparisons."""
    beaten = sum(1 for p in portfolio_returns if p < actual)
    ties = sum(1 for p in portfolio_returns if p == actual)
    total = Decimal(0)
    for p in portfolio_returns:
        total = CALC.add(total, p)
    return beaten, ties, CALC.divide(total, Decimal(len(portfolio_returns)))
