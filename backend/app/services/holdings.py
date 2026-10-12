"""Pure holdings fold (weighted-average cost). No ORM, framework, clock or I/O."""
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.domain.enums import TradeSide
from app.domain.holding_key import HoldingKey
from app.domain.instrument import Instrument
from app.domain.numeric import MAX_AMOUNT, MONEY_CONTEXT
from app.services.errors import NumericLimitError, OversellError

_ZERO = Decimal(0)


@dataclass(frozen=True)
class LedgerEntry:
    id: UUID
    instrument: Instrument
    side: TradeSide
    quantity: Decimal
    price_per_unit: Decimal
    brokerage_fee: Decimal
    taxes: Decimal
    trade_timestamp: datetime
    recorded_at: datetime
    isin: str | None = None  # NULL only on legacy rows; the holding key is the ISIN, else (symbol, exchange)
    name: str | None = None
    charges_provided: bool = True  # False: the stored 0 fees/taxes are unknown (imported rows)


def holding_key(entry: LedgerEntry) -> HoldingKey:
    return HoldingKey.of(entry.isin, entry.instrument.symbol, entry.instrument.exchange)


@dataclass(frozen=True)
class Holding:
    """One holding per key. `average_buy_price` and `invested_amount` are acquisition cost: buy-side fees and taxes included.

    `listings` and `name` come from ALL effective entries at or before `as_of`; `cost_basis_complete` only from the
    current position epoch (since the last time the quantity was exactly zero), and only BUY charges count.
    """

    key: HoldingKey
    listings: tuple[Instrument, ...]
    name: str | None
    quantity: Decimal
    average_buy_price: Decimal
    invested_amount: Decimal
    cost_basis_complete: bool


@dataclass(frozen=True)
class RealizedPnl:
    """Realized result of a holding's sells: net proceeds are after sell-side fees and taxes."""

    key: HoldingKey
    net_sale_proceeds: Decimal
    cost_of_sold: Decimal
    realized_pnl: Decimal


@dataclass(frozen=True)
class LedgerSummary:
    holdings: list[Holding]
    realized: list[RealizedPnl]


@dataclass(frozen=True)
class Oversell:
    instrument: Instrument
    entry_id: UUID
    held: Decimal
    requested: Decimal


class _State:
    __slots__ = ("quantity", "cost", "net_proceeds", "cost_sold", "sold", "listings", "name", "complete")

    def __init__(self) -> None:
        self.quantity = _ZERO
        self.cost = _ZERO
        self.net_proceeds = _ZERO
        self.cost_sold = _ZERO
        self.sold = False
        self.listings: set[Instrument] = set()
        self.name: str | None = None
        self.complete = True  # no BUY with unknown charges in the current position epoch


def _within_range(*values: Decimal) -> None:
    """Refuse (never round or clamp) a running total that leaves the exactly representable range."""
    for value in values:
        if abs(value) >= MAX_AMOUNT:
            raise NumericLimitError(f"running total {value} reaches the calculation limit {MAX_AMOUNT}")


def _side_rank(side: TradeSide) -> int:
    return 0 if side is TradeSide.BUY else 1


def canonical_order(entries: list[LedgerEntry]) -> list[LedgerEntry]:
    """Deterministic order: timestamp, BUY before SELL, recorded_at, id."""
    return sorted(
        entries,
        key=lambda e: (e.trade_timestamp, _side_rank(e.side), e.recorded_at, e.id),
    )


def _fold(
    entries: list[LedgerEntry], group_key: Callable[[LedgerEntry], Hashable] | None = None
) -> tuple[Oversell | None, dict]:
    """Fold in canonical order. BUY fees and taxes join the cost; SELL fees and taxes reduce net proceeds only.

    Entries are grouped by `group_key` (default: the holding key, i.e. the ISIN, else the legacy (symbol, exchange)).
    """
    ctx = MONEY_CONTEXT
    states: dict = {}
    for e in canonical_order(entries):
        st = states.setdefault(holding_key(e) if group_key is None else group_key(e), _State())
        st.listings.add(e.instrument)
        if e.name is not None:
            st.name = e.name  # canonical order: the last non-null name wins
        charges = ctx.add(e.brokerage_fee, e.taxes)
        gross = ctx.multiply(e.quantity, e.price_per_unit)
        if e.side is TradeSide.BUY:
            if not e.charges_provided:
                st.complete = False
            st.quantity = ctx.add(st.quantity, e.quantity)
            st.cost = ctx.add(st.cost, ctx.add(gross, charges))
            _within_range(st.quantity, st.cost)
            continue
        if e.quantity > st.quantity:
            return Oversell(e.instrument, e.id, st.quantity, e.quantity), states
        if e.quantity == st.quantity:
            cost_sold = st.cost  # exact full exit, no dust
            st.quantity = _ZERO
            st.cost = _ZERO
            st.complete = True  # the position epoch ends here; a later buy starts a new one
        else:
            cost_sold = ctx.multiply(ctx.divide(st.cost, st.quantity), e.quantity)
            st.quantity = ctx.subtract(st.quantity, e.quantity)
            st.cost = ctx.subtract(st.cost, cost_sold)
        st.net_proceeds = ctx.add(st.net_proceeds, ctx.subtract(gross, charges))
        st.cost_sold = ctx.add(st.cost_sold, cost_sold)
        st.sold = True
        _within_range(st.net_proceeds, st.cost_sold)
    return None, states


def find_oversell(
    entries: list[LedgerEntry], *, group_key: Callable[[LedgerEntry], Hashable] | None = None
) -> Oversell | None:
    """The first sell that exceeds what its group holds. `group_key` lets a caller group by something other than listing."""
    return _fold(entries, group_key)[0]


def fold_ledger(entries: list[LedgerEntry], as_of: datetime | None = None) -> LedgerSummary:
    if as_of is not None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        entries = [e for e in entries if e.trade_timestamp <= as_of]
    oversell, states = _fold(entries)
    if oversell is not None:
        raise OversellError(oversell.instrument, oversell.entry_id, oversell.held, oversell.requested)

    def order(item):
        return item.key.sort_key

    holdings = [
        Holding(
            key=key,
            listings=tuple(sorted(st.listings, key=lambda i: (i.exchange.value, i.symbol))),
            name=st.name,
            quantity=st.quantity,
            average_buy_price=MONEY_CONTEXT.divide(st.cost, st.quantity),
            invested_amount=st.cost,
            cost_basis_complete=st.complete,
        )
        for key, st in states.items()
        if st.quantity > _ZERO
    ]
    realized = [
        RealizedPnl(
            key=key,
            net_sale_proceeds=st.net_proceeds,
            cost_of_sold=st.cost_sold,
            realized_pnl=MONEY_CONTEXT.subtract(st.net_proceeds, st.cost_sold),
        )
        for key, st in states.items()
        if st.sold
    ]
    return LedgerSummary(sorted(holdings, key=order), sorted(realized, key=order))


def fold_holdings(entries: list[LedgerEntry], as_of: datetime | None = None) -> list[Holding]:
    return fold_ledger(entries, as_of).holdings
