"""Backtest portfolio accounting (Feature 005 step 2): cash and whole-share positions, exact Decimal, immutable.

Long-only, cash-funded, no costs, no partial fills, no shorting or leverage. Every operation validates its inputs and
returns a NEW `Portfolio`; nothing is ever mutated, clamped, rounded or repaired. Arithmetic runs in `EXACT_CONTEXT`
(wide, traps Inexact), so a rounding attempt would raise rather than silently lose digits. Every monetary value must stay
strictly below `MAX_AMOUNT`.

Errors: malformed values and bound violations raise `PortfolioError` (a `BacktestInputError`); the two business
rejections the execution model turns into `Rejection` records, `InsufficientCash` and `InsufficientPosition`, are
subclasses so callers can tell them apart.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from app.domain.instrument import Instrument
from app.domain.numeric import EXACT_CONTEXT, MAX_AMOUNT, MAX_INPUT_EXPONENT, MIN_INPUT_EXPONENT
from .config import BacktestInputError

_ZERO = Decimal(0)


class PortfolioError(BacktestInputError):
    """An invalid accounting operation or value (malformed input or a MAX_AMOUNT bound)."""


class InsufficientCash(PortfolioError):
    """A buy whose notional exceeds cash. The whole order is rejected."""


class InsufficientPosition(PortfolioError):
    """A sell larger than the held quantity (including an instrument not held). The whole order is rejected."""


# ---- exact arithmetic and validation helpers ------------------------------------------------------------------------


def _exact(op: str, *args: Decimal) -> Decimal:
    try:
        return getattr(EXACT_CONTEXT, op)(*args)
    except ArithmeticError as exc:  # Inexact / Overflow / InvalidOperation are trapped by EXACT_CONTEXT
        raise PortfolioError(f"exact arithmetic failed ({op}): {exc.__class__.__name__}") from exc


def _finite_decimal(name: str, value: object) -> Decimal:
    if not isinstance(value, Decimal):
        raise PortfolioError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise PortfolioError(f"{name} must be finite")
    return value


def _below_max(name: str, value: Decimal) -> Decimal:
    if not value < MAX_AMOUNT:
        raise PortfolioError(f"{name} must be below {MAX_AMOUNT}")
    return value


def _check_exponent(name: str, value: Decimal) -> None:
    exponent = value.as_tuple().exponent
    if not (MIN_INPUT_EXPONENT <= exponent <= MAX_INPUT_EXPONENT):
        raise PortfolioError(f"{name} exponent {exponent} is outside [{MIN_INPUT_EXPONENT}, {MAX_INPUT_EXPONENT}]")


def _amount(name: str, value: object) -> Decimal:
    """A money value that may be zero: finite, not negative (-0 included), below MAX_AMOUNT, exponent in range."""
    value = _finite_decimal(name, value)
    if value.is_signed():
        raise PortfolioError(f"{name} must not be negative")
    _check_exponent(name, value)
    return _below_max(name, value)


def _price(name: str, value: object) -> Decimal:
    value = _finite_decimal(name, value)
    if not (0 < value < MAX_AMOUNT):
        raise PortfolioError(f"{name} must be above 0 and below {MAX_AMOUNT}")
    _check_exponent(name, value)
    return value


def _whole_shares(name: str, value: object) -> Decimal:
    """A positive whole number of shares, returned as a plain integer Decimal. Never rounds a fraction away."""
    value = _finite_decimal(name, value)
    if not (0 < value < MAX_AMOUNT):
        raise PortfolioError(f"{name} must be above 0 and below {MAX_AMOUNT}")
    _check_exponent(name, value)
    if value != value.to_integral_value():
        raise PortfolioError(f"{name} must be a whole number of shares")
    return Decimal(int(value))


def _instrument(value: object) -> Instrument:
    if not isinstance(value, Instrument):
        raise PortfolioError("instrument must be an Instrument")
    return value


def _order_key(instrument: Instrument) -> tuple[str, str]:
    return (instrument.exchange.value, instrument.symbol)


# ---- valuation ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Valuation:
    """A mark-to-market snapshot from explicit prices. `equity` is exactly `cash + positions_value`."""

    cash: Decimal
    positions_value: Decimal
    equity: Decimal

    def __post_init__(self) -> None:
        _amount("cash", self.cash)
        _amount("positions_value", self.positions_value)
        _amount("equity", self.equity)
        if _exact("add", self.cash, self.positions_value) != self.equity:
            raise PortfolioError("equity must equal cash + positions_value")


# ---- the portfolio --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Portfolio:
    """Immutable cash + whole-share positions. `positions` is a tuple of (Instrument, quantity) sorted by
    (exchange, symbol), one entry per instrument, never a zero quantity, each quantity a plain integer Decimal (an
    integral input like 5.0 is normalized on construction). Use `as_mapping()` for a read-only view."""

    cash: Decimal
    positions: tuple[tuple[Instrument, Decimal], ...] = ()

    def __post_init__(self) -> None:
        _amount("cash", self.cash)
        if not isinstance(self.positions, tuple):
            raise PortfolioError("positions must be a tuple of (Instrument, quantity) pairs")
        previous: tuple[str, str] | None = None
        canonical = []
        for pair in self.positions:
            if not (isinstance(pair, tuple) and len(pair) == 2):
                raise PortfolioError("each position must be an (Instrument, quantity) tuple")
            instrument, quantity = pair
            _instrument(instrument)
            # Finite, above zero (zero is never stored), below MAX_AMOUNT and mathematically whole. An integral value
            # such as 5.0 or 1E+2 is accepted and stored as the plain integer Decimal; a fraction is rejected.
            canonical.append((instrument, _whole_shares("quantity", quantity)))
            key = _order_key(instrument)
            if previous is not None and not previous < key:
                raise PortfolioError("positions must be unique and sorted by (exchange, symbol)")
            previous = key
        if any(new[1].as_tuple() != old[1].as_tuple() for new, old in zip(canonical, self.positions)):
            object.__setattr__(self, "positions", tuple(canonical))  # normalized once, exactly (int arithmetic only)

    @classmethod
    def initial(cls, cash: Decimal) -> "Portfolio":
        return cls(cash=cash)

    # ---- read-only access -------------------------------------------------------------------------------------------

    def quantity(self, instrument: Instrument) -> Decimal:
        """Held shares of `instrument`; an instrument not held is a real zero quantity (not a missing value)."""
        _instrument(instrument)
        for held, quantity in self.positions:
            if held == instrument:
                return quantity
        return _ZERO

    def as_mapping(self) -> Mapping[Instrument, Decimal]:
        """A fresh read-only view over a copy: callers cannot reach or change this portfolio through it."""
        return MappingProxyType(dict(self.positions))

    # ---- operations (each returns a new Portfolio) ------------------------------------------------------------------

    def buy(self, instrument: Instrument, quantity: Decimal, price: Decimal) -> "Portfolio":
        instrument = _instrument(instrument)
        quantity = _whole_shares("quantity", quantity)
        price = _price("price", price)
        notional = _below_max("notional", _exact("multiply", quantity, price))
        if notional > self.cash:
            raise InsufficientCash(f"notional {notional} exceeds cash {self.cash}")
        new_quantity = _below_max("position quantity", _exact("add", self.quantity(instrument), quantity))
        return Portfolio(cash=_exact("subtract", self.cash, notional), positions=self._with(instrument, new_quantity))

    def sell(self, instrument: Instrument, quantity: Decimal, price: Decimal) -> "Portfolio":
        instrument = _instrument(instrument)
        quantity = _whole_shares("quantity", quantity)
        price = _price("price", price)
        held = self.quantity(instrument)
        if quantity > held:
            raise InsufficientPosition(f"cannot sell {quantity}: only {held} held")
        notional = _below_max("notional", _exact("multiply", quantity, price))
        new_cash = _below_max("cash", _exact("add", self.cash, notional))
        return Portfolio(cash=new_cash, positions=self._with(instrument, _exact("subtract", held, quantity)))

    def mark(self, prices: Mapping[Instrument, Decimal]) -> Valuation:
        """Value held positions at caller-supplied prices. Exactly one valid price per held instrument is required:
        a missing price raises (never zero) and so does a price for an instrument that is not held."""
        if not isinstance(prices, Mapping):
            raise PortfolioError("prices must be a mapping of Instrument to Decimal")
        checked = {_instrument(i): _price(f"price for {i.symbol}", p) for i, p in prices.items()}
        held = {instrument for instrument, _ in self.positions}
        extra = checked.keys() - held
        if extra:
            raise PortfolioError(f"prices supplied for instruments not held: {sorted(i.symbol for i in extra)}")
        total = _ZERO
        for instrument, quantity in self.positions:
            if instrument not in checked:
                raise PortfolioError(f"no price supplied for held instrument {instrument.symbol}")
            value = _below_max("position value", _exact("multiply", quantity, checked[instrument]))
            total = _below_max("positions value", _exact("add", total, value))
        equity = _below_max("equity", _exact("add", self.cash, total))
        return Valuation(cash=self.cash, positions_value=total, equity=equity)

    # ---- internals --------------------------------------------------------------------------------------------------

    def _with(self, instrument: Instrument, quantity: Decimal) -> tuple[tuple[Instrument, Decimal], ...]:
        """Positions with `instrument` set to `quantity` (0 removes it), kept sorted by (exchange, symbol)."""
        rest = [(i, q) for i, q in self.positions if i != instrument]
        if quantity > 0:
            rest.append((instrument, quantity))
        return tuple(sorted(rest, key=lambda pair: _order_key(pair[0])))
