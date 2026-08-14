from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID

from app.models.enums import AssetType, Currency, Exchange
from app.repositories.portfolio_repository import PortfolioRepository
from app.repositories.position_repository import PositionRepository
from app.schemas.portfolio import HoldingSummary, PortfolioSummary
from app.services.market_service import MarketService


class PortfolioService:
    def __init__(
        self,
        portfolio_repository: PortfolioRepository,
        position_repository: PositionRepository,
        market_service: MarketService,
    ):
        self.portfolio_repository = portfolio_repository
        self.position_repository = position_repository
        self.market_service = market_service

    def get_summary(self, user_id: UUID) -> PortfolioSummary:
        total_trades = self.portfolio_repository.get_total_trades(user_id)
        active_positions = self.position_repository.list_active_positions(user_id=user_id)
        all_positions = self.position_repository.list_all_positions(user_id=user_id)

        holdings: list[HoldingSummary] = []
        total_invested = Decimal("0")
        total_realized_profit_loss = sum(
            (position.cumulative_realized_profit_loss for position in all_positions),
            Decimal("0"),
        )

        available_quote_count = 0
        total_active_positions = len(active_positions)
        total_market_value = Decimal("0")
        total_unrealized_profit_loss = Decimal("0")

        for position in active_positions:
            invested_amount = position.remaining_cost_basis
            total_invested += invested_amount

            current_price = self._get_validated_quote_price(position)
            if current_price is not None:
                available_quote_count += 1
                market_value = position.remaining_quantity * current_price
                unrealized_profit_loss = market_value - invested_amount
                quote_status = "AVAILABLE"
                total_market_value += market_value
                total_unrealized_profit_loss += unrealized_profit_loss
            else:
                market_value = None
                unrealized_profit_loss = None
                quote_status = "UNAVAILABLE"

            holdings.append(
                HoldingSummary(
                    symbol=position.asset_symbol,
                    quantity=position.remaining_quantity,
                    average_buy_price=position.average_cost,
                    invested_amount=invested_amount,
                    exchange=position.exchange.value,
                    asset_type=position.asset_type.value,
                    currency=position.currency.value,
                    current_price=current_price,
                    market_value=market_value,
                    unrealized_profit_loss=unrealized_profit_loss,
                    realized_profit_loss=position.cumulative_realized_profit_loss,
                    quote_status=quote_status,
                )
            )

        if total_active_positions == 0:
            valuation_status = "UNAVAILABLE"
            valued_at = None
            summary_market_value = None
            summary_unrealized_profit_loss = None
        elif available_quote_count == total_active_positions:
            valuation_status = "COMPLETE"
            valued_at = datetime.now(timezone.utc)
            summary_market_value = total_market_value
            summary_unrealized_profit_loss = total_unrealized_profit_loss
        elif available_quote_count > 0:
            valuation_status = "PARTIAL"
            valued_at = datetime.now(timezone.utc)
            summary_market_value = None
            summary_unrealized_profit_loss = None
        else:
            valuation_status = "UNAVAILABLE"
            valued_at = None
            summary_market_value = None
            summary_unrealized_profit_loss = None

        return PortfolioSummary(
            total_trades=total_trades,
            total_invested=total_invested,
            total_market_value=summary_market_value,
            total_unrealized_profit_loss=summary_unrealized_profit_loss,
            total_realized_profit_loss=total_realized_profit_loss,
            valuation_status=valuation_status,
            valued_at=valued_at,
            holdings=holdings,
        )

    def _get_validated_quote_price(self, position) -> Decimal | None:
        provider_symbol = self._resolve_provider_symbol(position)
        if provider_symbol is None:
            return None

        try:
            quote = self.market_service.get_stock_quote(provider_symbol)
        except Exception:
            return None

        if not self._is_quote_identity_valid(
            provider_symbol=provider_symbol,
            position=position,
            quote=quote,
        ):
            return None

        raw_price = getattr(quote, "current_price", None)
        if raw_price is None:
            return None

        try:
            price = Decimal(str(raw_price))
        except (InvalidOperation, ValueError):
            return None

        if not price.is_finite() or price <= Decimal("0"):
            return None

        return price

    def _resolve_provider_symbol(self, position) -> str | None:
        if position.asset_type != AssetType.STOCK:
            return None

        if position.currency != Currency.INR:
            return None

        if position.exchange == Exchange.NSE:
            suffix = ".NS"
        elif position.exchange == Exchange.BSE:
            suffix = ".BO"
        else:
            return None

        base_symbol = str(position.asset_symbol).strip().upper()
        if not base_symbol:
            return None

        if base_symbol.endswith(".NS") or base_symbol.endswith(".BO"):
            base_symbol = base_symbol.rsplit(".", 1)[0]

        return f"{base_symbol}{suffix}"

    def _normalize_provider_identity_symbol(self, symbol: str | None) -> str | None:
        if not isinstance(symbol, str):
            return None

        normalized = symbol.strip().upper()
        return normalized or None

    def _is_quote_identity_valid(self, *, provider_symbol: str, position, quote) -> bool:
        normalized_provider_symbol = provider_symbol.upper()
        normalized_quote_symbol = self._normalize_provider_identity_symbol(
            getattr(quote, "symbol", None)
        )

        if normalized_quote_symbol is None:
            return False

        if normalized_quote_symbol != normalized_provider_symbol:
            return False

        quote_currency = getattr(quote, "currency", None)
        if not isinstance(quote_currency, str):
            return False

        normalized_quote_currency = quote_currency.strip().upper()
        if not normalized_quote_currency:
            return False

        return normalized_quote_currency == position.currency.value.upper()