from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.enums import AssetType, Currency, Exchange
from app.models.market_snapshot import MarketSnapshot


class MarketSnapshotRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        user_id: UUID,
        source: str,
        asset_symbol: str,
        currency: Currency,
        asset_price: Decimal,
        price_timestamp: datetime,
        market_data: dict,
        captured_at: datetime | None = None,
        exchange: Exchange | None = None,
        asset_type: AssetType | None = None,
        volume: Decimal | None = None,
        market_cap: Decimal | None = None,
    ) -> MarketSnapshot:
        snapshot = MarketSnapshot(
            user_id=user_id,
            source=source,
            asset_symbol=asset_symbol,
            exchange=exchange,
            asset_type=asset_type,
            currency=currency,
            asset_price=asset_price,
            price_timestamp=price_timestamp,
            volume=volume,
            market_cap=market_cap,
            market_data=market_data,
        )

        if captured_at is not None:
            snapshot.captured_at = captured_at

        self.db.add(snapshot)
        self.db.flush()
        self.db.refresh(snapshot)

        return snapshot

    def get_by_id(self, user_id: UUID, snapshot_id: UUID) -> MarketSnapshot | None:
        return (
            self.db.query(MarketSnapshot)
            .filter(
                MarketSnapshot.user_id == user_id,
                MarketSnapshot.id == snapshot_id,
            )
            .first()
        )

    def list_for_user(
        self,
        user_id: UUID,
        *,
        asset_symbol: str | None = None,
        captured_at_from: datetime | None = None,
        captured_at_to: datetime | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[MarketSnapshot]:
        query = self.db.query(MarketSnapshot).filter(MarketSnapshot.user_id == user_id)

        if asset_symbol is not None:
            query = query.filter(MarketSnapshot.asset_symbol == asset_symbol)

        if captured_at_from is not None:
            query = query.filter(MarketSnapshot.captured_at >= captured_at_from)

        if captured_at_to is not None:
            query = query.filter(MarketSnapshot.captured_at <= captured_at_to)

        query = query.order_by(MarketSnapshot.captured_at.desc())

        if offset:
            query = query.offset(offset)

        if limit is not None:
            query = query.limit(limit)

        return query.all()
