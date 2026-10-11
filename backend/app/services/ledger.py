"""Trade ledger service: record, correct, void, list, get, holdings. Append-only; user-scoped."""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.enums import (
    AssetType,
    Currency,
    Exchange,
    MarketSession,
    TradeSide,
    TradeSource,
    TradeStatus,
)
from app.domain import limits
from app.domain.instrument import Instrument
from app.domain.numeric import EXACT_CONTEXT, MAX_AMOUNT, MAX_INPUT_EXPONENT, MIN_INPUT_EXPONENT, SCALE
from app.models.trade import Trade
from app.repositories.trade_repository import TradeRepository
from app.services.errors import (
    AlreadySupersededError,
    DuplicateTradeError,
    InvalidTradeError,
    NumericLimitError,
    OversellError,
    TradeNotFoundError,
)
from app.services.holdings import Holding, LedgerEntry, find_oversell, fold_holdings

_MAX_INTEGER_DIGITS = 14  # NUMERIC(20, 6)
_ZERO = Decimal(0)


def _decimal(name: str, value: object) -> Decimal:
    if not isinstance(value, Decimal):
        raise InvalidTradeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise InvalidTradeError(f"{name} must be finite")
    exponent = value.as_tuple().exponent
    if not MIN_INPUT_EXPONENT <= exponent <= MAX_INPUT_EXPONENT:
        raise InvalidTradeError(
            f"{name} has an exponent ({exponent}) outside the supported range "
            f"[{MIN_INPUT_EXPONENT}, {MAX_INPUT_EXPONENT}]"
        )
    if value.normalize().as_tuple().exponent < -SCALE:
        raise InvalidTradeError(f"{name} has more than {SCALE} decimal places")
    if value and value.adjusted() + 1 > _MAX_INTEGER_DIGITS:
        raise InvalidTradeError(f"{name} is too large")
    return value


def _text(name: str, value: object, max_length: int, *, required: bool = False) -> None:
    if value is None and not required:
        return
    if not isinstance(value, str):
        raise InvalidTradeError(f"{name} must be a string")
    if "\x00" in value:
        raise InvalidTradeError(f"{name} must not contain NUL characters")
    if required and not value.strip():
        raise InvalidTradeError(f"{name} must not be empty")
    if len(value) > max_length:
        raise InvalidTradeError(f"{name} is longer than {max_length} characters")


def _enum(name: str, value: object, cls: type) -> None:
    if not isinstance(value, cls):
        raise InvalidTradeError(f"{name} must be a {cls.__name__}")


@dataclass(frozen=True)
class TradeInput:
    """The FR-1 field set a caller may supply. Validates, never repairs."""

    symbol: str
    name: str
    asset_type: AssetType
    exchange: Exchange
    side: TradeSide
    quantity: Decimal
    price_per_unit: Decimal
    trade_timestamp: datetime
    market_session: MarketSession
    currency: Currency = Currency.INR
    brokerage_fee: Decimal = _ZERO
    taxes: Decimal = _ZERO
    status: TradeStatus = TradeStatus.EXECUTED
    broker: str | None = None
    broker_trade_id: str | None = None
    order_id: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        for field, cls in (
            ("asset_type", AssetType), ("exchange", Exchange), ("side", TradeSide),
            ("market_session", MarketSession), ("currency", Currency), ("status", TradeStatus),
        ):
            _enum(field, getattr(self, field), cls)
        _text("symbol", self.symbol, limits.MAX_SYMBOL_LENGTH, required=True)
        _text("name", self.name, limits.MAX_NAME_LENGTH, required=True)
        _text("broker", self.broker, limits.MAX_BROKER_LENGTH)
        _text("broker_trade_id", self.broker_trade_id, limits.MAX_BROKER_TRADE_ID_LENGTH)
        _text("order_id", self.order_id, limits.MAX_ORDER_ID_LENGTH)
        _text("notes", self.notes, limits.MAX_NOTES_LENGTH)
        quantity = _decimal("quantity", self.quantity)
        price = _decimal("price_per_unit", self.price_per_unit)
        fee = _decimal("brokerage_fee", self.brokerage_fee)
        taxes = _decimal("taxes", self.taxes)
        if quantity <= 0:
            raise InvalidTradeError("quantity must be greater than zero")
        if price <= 0:
            raise InvalidTradeError("price_per_unit must be greater than zero")
        if fee < 0 or taxes < 0:
            raise InvalidTradeError("fees and taxes must not be negative")
        notional = EXACT_CONTEXT.add(EXACT_CONTEXT.multiply(quantity, price), EXACT_CONTEXT.add(fee, taxes))
        if notional >= MAX_AMOUNT:
            raise NumericLimitError(f"quantity x price + fees + taxes must be below {MAX_AMOUNT}")
        ts = self.trade_timestamp
        if not isinstance(ts, datetime) or ts.tzinfo is None or ts.utcoffset() is None:
            raise InvalidTradeError("trade_timestamp must be timezone-aware")
        try:
            utc_ts = ts.astimezone(timezone.utc)
        except (OverflowError, ValueError):  # the offset pushes the UTC instant outside years 1..9999
            raise InvalidTradeError("trade_timestamp is outside the supported date range once converted to UTC") from None
        if not limits.MIN_TRADE_TIMESTAMP <= utc_ts <= limits.MAX_TRADE_TIMESTAMP:
            raise InvalidTradeError(
                f"trade_timestamp must be between {limits.MIN_TRADE_TIMESTAMP.isoformat()} "
                f"and {limits.MAX_TRADE_TIMESTAMP.isoformat()} (UTC)"
            )
        object.__setattr__(self, "trade_timestamp", utc_ts)


def _to_entry(trade: Trade) -> LedgerEntry:
    return LedgerEntry(
        id=trade.id,
        instrument=Instrument(trade.symbol, trade.exchange),
        side=trade.side,
        quantity=trade.quantity,
        price_per_unit=trade.price_per_unit,
        brokerage_fee=trade.brokerage_fee,
        taxes=trade.taxes,
        trade_timestamp=trade.trade_timestamp,
        recorded_at=trade.recorded_at,
    )


class LedgerService:
    def __init__(
        self,
        repository: TradeRepository,
        *,
        clock: Callable[[], datetime],
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._repo = repository
        self._clock = clock
        self._new_id = id_factory

    @classmethod
    def for_session(
        cls,
        session: Session,
        *,
        clock: Callable[[], datetime],
        id_factory: Callable[[], UUID] = uuid4,
    ) -> "LedgerService":
        return cls(TradeRepository(session), clock=clock, id_factory=id_factory)

    # ---- reads ---------------------------------------------------------------

    def list_trades(self, *, user_id: UUID) -> list[Trade]:
        return self._repo.list_for_user(user_id=user_id)

    def get_trade(self, *, user_id: UUID, trade_id: UUID) -> Trade:
        trade = self._repo.get(user_id=user_id, trade_id=trade_id)
        if trade is None:
            raise TradeNotFoundError(trade_id)
        return trade

    def holdings(self, *, user_id: UUID, as_of: datetime | None = None) -> list[Holding]:
        if as_of is not None and (as_of.tzinfo is None or as_of.utcoffset() is None):
            raise InvalidTradeError("as_of must be timezone-aware")
        entries = [_to_entry(t) for t in self._repo.list_effective(user_id=user_id)]
        return fold_holdings(entries, as_of=as_of)

    # ---- writes --------------------------------------------------------------

    def record(self, *, user_id: UUID, data: TradeInput) -> Trade:
        return self._append(user_id=user_id, fields=self._fields(data), target=None)

    def correct(self, *, user_id: UUID, trade_id: UUID, data: TradeInput) -> Trade:
        target = self._load_target(user_id, trade_id)
        return self._append(user_id=user_id, fields=self._fields(data), target=target)

    def void(self, *, user_id: UUID, trade_id: UUID) -> Trade:
        target = self._load_target(user_id, trade_id)
        fields = {
            name: getattr(target, name)
            for name in (
                "symbol", "name", "asset_type", "exchange", "currency", "side", "quantity",
                "price_per_unit", "brokerage_fee", "taxes", "trade_timestamp", "broker",
                "broker_trade_id", "order_id", "market_session", "notes",
            )
        }
        fields["status"] = TradeStatus.CANCELLED
        return self._append(user_id=user_id, fields=fields, target=target)

    # ---- internals -----------------------------------------------------------

    @staticmethod
    def _fields(data: TradeInput) -> dict:
        return {
            "symbol": data.symbol, "name": data.name, "asset_type": data.asset_type,
            "exchange": data.exchange, "currency": data.currency, "side": data.side,
            "quantity": data.quantity, "price_per_unit": data.price_per_unit,
            "brokerage_fee": data.brokerage_fee, "taxes": data.taxes,
            "trade_timestamp": data.trade_timestamp, "broker": data.broker,
            "broker_trade_id": data.broker_trade_id, "order_id": data.order_id,
            "market_session": data.market_session, "status": data.status, "notes": data.notes,
        }

    def _load_target(self, user_id: UUID, trade_id: UUID) -> Trade:
        target = self._repo.get(user_id=user_id, trade_id=trade_id)
        if target is None:
            raise TradeNotFoundError(trade_id)
        if self._repo.superseder_of(user_id=user_id, trade_id=trade_id) is not None:
            raise AlreadySupersededError(trade_id)
        return target

    def _append(self, *, user_id: UUID, fields: dict, target: Trade | None) -> Trade:
        new_id = self._new_id()
        recorded_at = self._clock()
        candidate = Trade(
            id=new_id,
            user_id=user_id,
            recorded_at=recorded_at,
            source=TradeSource.MANUAL,
            supersedes_trade_id=target.id if target is not None else None,
            **fields,
        )
        self._check_no_oversell(user_id=user_id, candidate=candidate, replaced=target)
        self._refuse_duplicate(user_id=user_id, candidate=candidate)
        try:
            return self._repo.add(
                user_id=user_id,
                **{c.name: getattr(candidate, c.name) for c in Trade.__table__.columns if c.name != "user_id"},
            )
        except IntegrityError:
            # Race: another request inserted the same original between our check and our insert. The unique
            # index is the final authority; translate only that case and let any other violation surface.
            self._refuse_duplicate(user_id=user_id, candidate=candidate)
            raise

    def _refuse_duplicate(self, *, user_id: UUID, candidate: Trade) -> None:
        """Mirror of the dedupe index: originals only, and only when broker and broker_trade_id are not NULL ('' is a value)."""
        if candidate.supersedes_trade_id is not None or candidate.broker is None or candidate.broker_trade_id is None:
            return
        existing = self._repo.original_by_broker_trade_id(
            user_id=user_id, broker=candidate.broker, broker_trade_id=candidate.broker_trade_id
        )
        if existing is not None:
            raise DuplicateTradeError(candidate.broker, candidate.broker_trade_id, existing.id) from None

    def _check_no_oversell(self, *, user_id: UUID, candidate: Trade, replaced: Trade | None) -> None:
        """One mechanism for create, correct and void: fold the candidate effective set."""
        instruments = {Instrument(candidate.symbol, candidate.exchange)}
        if replaced is not None:
            instruments.add(Instrument(replaced.symbol, replaced.exchange))
        entries = [
            _to_entry(t)
            for t in self._repo.list_effective(user_id=user_id, instruments=instruments)
            if replaced is None or t.id != replaced.id
        ]
        if candidate.status is TradeStatus.EXECUTED:
            entries.append(_to_entry(candidate))
        over = find_oversell(entries)
        if over is not None:
            raise OversellError(over.instrument, over.entry_id, over.held, over.requested)
