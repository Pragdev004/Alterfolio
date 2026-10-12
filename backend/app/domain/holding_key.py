"""Holding identity (plan 002a OPEN-1, 1b). stdlib only; used by the later ledger/holdings step, not wired in yet."""
from dataclasses import dataclass

from app.domain.enums import Exchange


@dataclass(frozen=True)
class HoldingKey:
    """The ISIN for an ISIN holding, or (symbol, exchange) for a legacy trade that has no ISIN.

    An ISIN key never equals a legacy key, so NULL-ISIN trades are never merged into an ISIN holding.
    """

    isin: str | None = None
    symbol: str | None = None
    exchange: Exchange | None = None

    def __post_init__(self) -> None:
        if self.isin is not None:
            if not isinstance(self.isin, str) or not self.isin.strip():
                raise ValueError("isin must be a non-empty string")
            if self.symbol is not None or self.exchange is not None:
                raise ValueError("an ISIN key carries no symbol or exchange")
        else:
            if not isinstance(self.symbol, str) or not self.symbol.strip():
                raise ValueError("a legacy key needs a non-empty symbol")
            if not isinstance(self.exchange, Exchange):
                raise ValueError("a legacy key needs an exchange")

    @classmethod
    def for_isin(cls, isin: str) -> "HoldingKey":
        return cls(isin=isin)

    @classmethod
    def legacy(cls, symbol: str, exchange: Exchange) -> "HoldingKey":
        return cls(symbol=symbol, exchange=exchange)

    @classmethod
    def of(cls, isin: str | None, symbol: str, exchange: Exchange) -> "HoldingKey":
        """The key of a trade's fields: its ISIN when it has one, else its legacy (symbol, exchange)."""
        return cls.for_isin(isin) if isin is not None else cls.legacy(symbol, exchange)

    @property
    def sort_key(self) -> tuple:
        """ISIN holdings first by ISIN ascending, then legacy holdings by (symbol, exchange)."""
        if self.isin is not None:
            return (0, self.isin, "", "")
        return (1, "", self.symbol, self.exchange.value)
