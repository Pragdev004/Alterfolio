from dataclasses import dataclass

from app.domain.enums import Exchange


@dataclass(frozen=True)
class Instrument:
    """Instrument identity is (symbol, exchange); NSE and BSE listings are distinct."""

    symbol: str
    exchange: Exchange

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty")
