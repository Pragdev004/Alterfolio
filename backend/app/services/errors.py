from decimal import Decimal
from uuid import UUID

from app.domain.instrument import Instrument


class LedgerError(Exception):
    """Base for rule violations raised by the ledger and holdings services."""

    code = "ledger_error"


class OversellError(LedgerError):
    code = "oversell"

    def __init__(self, instrument: Instrument, trade_id: UUID, held: Decimal, requested: Decimal):
        self.instrument = instrument
        self.trade_id = trade_id
        self.held = held
        self.requested = requested
        super().__init__(
            f"sell of {requested} {instrument.symbol} ({instrument.exchange.value}) exceeds held {held}"
        )


class AlreadySupersededError(LedgerError):
    code = "already_superseded"

    def __init__(self, trade_id: UUID):
        self.trade_id = trade_id
        super().__init__(f"trade {trade_id} is already superseded; correct the latest row instead")


class TradeNotFoundError(LedgerError):
    code = "trade_not_found"

    def __init__(self, trade_id: UUID):
        self.trade_id = trade_id
        super().__init__("trade not found")


class InvalidTradeError(LedgerError):
    code = "invalid_trade"


class NumericLimitError(InvalidTradeError):
    """A trade or running total would leave the range the Decimal calculations can represent exactly."""

    code = "numeric_limit_exceeded"


class DuplicateTradeError(LedgerError):
    """The user already has an original trade with this (broker, broker_trade_id)."""

    code = "duplicate_trade"

    def __init__(self, broker: str, broker_trade_id: str, existing_trade_id: UUID | None = None):
        self.existing_trade_id = existing_trade_id
        super().__init__(f"a trade with broker {broker!r} and broker_trade_id {broker_trade_id!r} already exists")
