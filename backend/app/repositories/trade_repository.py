from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session, aliased

from app.domain.enums import Exchange, TradeStatus
from app.domain.instrument import Instrument
from app.models.trade import Trade
from app.models.user import User


class TradeRepository:
    """Insert and select only. Every method is scoped to a user; there is no update or delete."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def lock_user_ledger(self, *, user_id: UUID) -> bool:
        """Take the user's write lock: `SELECT ... FOR UPDATE NOWAIT` on the users row (no wait; a no-op on SQLite).

        Returns False when the user row does not exist. Held until the transaction ends. PostgreSQL raises an
        OperationalError (sqlstate 55P03) when another transaction holds it; the service translates that.
        """
        row = self._session.execute(select(User.id).where(User.id == user_id).with_for_update(nowait=True)).first()
        return row is not None

    def add(self, *, user_id: UUID, **fields) -> Trade:
        """Insert in a savepoint: a constraint violation undoes only this row and leaves the session usable."""
        trade = Trade(user_id=user_id, **fields)
        with self._session.begin_nested():
            self._session.add(trade)
            self._session.flush()
        return trade

    def original_by_key(
        self, *, user_id: UUID, broker: str, exchange: Exchange, broker_trade_id: str
    ) -> Trade | None:
        """The user's original (non-correction) row for the dedupe key; mirrors `uq_trades_dedupe`."""
        return self._session.scalars(
            select(Trade).where(
                Trade.user_id == user_id,
                Trade.broker == broker,
                Trade.exchange == exchange,
                Trade.broker_trade_id == broker_trade_id,
                Trade.supersedes_trade_id.is_(None),
            )
        ).one_or_none()

    def get(self, *, user_id: UUID, trade_id: UUID) -> Trade | None:
        return self._session.scalars(
            select(Trade).where(Trade.user_id == user_id, Trade.id == trade_id)
        ).one_or_none()

    def list_for_user(self, *, user_id: UUID) -> list[Trade]:
        rows = self._session.scalars(select(Trade).where(Trade.user_id == user_id)).all()
        return sorted(rows, key=lambda t: (t.trade_timestamp, t.recorded_at, t.id))

    def list_effective(
        self,
        *,
        user_id: UUID,
        instruments: Iterable[Instrument] | None = None,
        as_of: datetime | None = None,
    ) -> list[Trade]:
        child = aliased(Trade)
        stmt = select(Trade).where(
            Trade.user_id == user_id,
            Trade.status == TradeStatus.EXECUTED,
            ~exists().where(child.user_id == user_id, child.supersedes_trade_id == Trade.id),
        )
        if instruments is not None:
            keys = [and_(Trade.symbol == i.symbol, Trade.exchange == i.exchange) for i in instruments]
            if not keys:
                return []
            stmt = stmt.where(or_(*keys))
        if as_of is not None:
            stmt = stmt.where(Trade.trade_timestamp <= as_of)
        rows = self._session.scalars(stmt).all()
        return sorted(rows, key=lambda t: (t.trade_timestamp, t.recorded_at, t.id))

    def list_effective_for_isins(self, *, user_id: UUID, isins: Iterable[str]) -> list[Trade]:
        """Effective rows of the user whose ISIN is in `isins`, across exchanges (legacy NULL-ISIN rows never match)."""
        wanted = sorted(set(isins))
        if not wanted:
            return []
        child = aliased(Trade)
        rows = self._session.scalars(
            select(Trade).where(
                Trade.user_id == user_id,
                Trade.status == TradeStatus.EXECUTED,
                Trade.isin.in_(wanted),
                ~exists().where(child.user_id == user_id, child.supersedes_trade_id == Trade.id),
            )
        ).all()
        return sorted(rows, key=lambda t: (t.trade_timestamp, t.recorded_at, t.id))

    def superseder_of(self, *, user_id: UUID, trade_id: UUID) -> Trade | None:
        return self._session.scalars(
            select(Trade).where(Trade.user_id == user_id, Trade.supersedes_trade_id == trade_id)
        ).one_or_none()
