"""Zerodha tradebook import service (plan 002, Feature 002c): parse result -> ledger rows in one locked transaction.

Pipeline: parse (no database) -> user lock -> batch -> pass 1 in file order (duplicates, conflicts, in-file repeats)
-> pass 2 in canonical order (ISIN quarantine, oversell, insert). Oversell is judged by replaying the user's WHOLE
effective ledger for the touched ISINs plus the new rows in trade-time order (timestamp, BUY before SELL, recorded_at, id),
never in insertion order, so any split of one history into uploads gives the same ledger once every upload is feasible -> batch counters -> commit. Any exception rolls back
the whole upload, including the batch. A row outcome is a result (imported, duplicate, rejected), never an exception.
"""
import hashlib
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import limits
from app.domain.enums import Currency, Exchange, TradeSide, TradeSource, TradeStatus
from app.domain.holding_key import HoldingKey
from app.domain.instrument import Instrument
from app.models.trade import Trade
from app.repositories.import_batch_repository import ImportBatchRepository
from app.repositories.trade_repository import TradeRepository
from app.models.import_batch import ImportBatch
from app.services.errors import NumericLimitError
from app.services.holdings import LedgerEntry, find_oversell
from app.services.ledger import LedgerService
from app.services.tradebook_parser import BROKER, ParsedTradeRow, RowRejection, parse_tradebook

CONFLICTING_DUPLICATE = "conflicting_duplicate"
OVERSELL = "oversell"
AFTER_OVERSELL = "after_oversell"
NUMERIC_LIMIT_EXCEEDED = "numeric_limit_exceeded"

_ZERO = Decimal(0)


@dataclass(frozen=True)
class BatchSummary:
    batch: ImportBatch
    superseded: bool  # a newer upload of the byte-identical file exists, so this batch's rejections no longer count


@dataclass(frozen=True)
class ImportStatus:
    batches: tuple[BatchSummary, ...]  # newest first
    rejected_rows_total: int  # rejected rows of the newest batch of each distinct file


@dataclass(frozen=True)
class ImportResult:
    """`rejected` lists the first MAX_LISTED_REJECTIONS in ascending file line; `rejected_total` is always exact."""

    import_batch_id: UUID
    file_name: str
    file_sha256: str
    total_rows: int
    imported: int
    duplicates: int
    rejected_total: int
    rejected: tuple[RowRejection, ...]
    quarantined_isins: tuple[str, ...]
    fees_taxes_provided: bool = False  # imported rows carry no fees or taxes (stored 0, charges_provided=false)


def _differences_from_row(row: ParsedTradeRow, other: ParsedTradeRow) -> list[str]:
    pairs = (
        ("isin", row.isin, other.isin), ("symbol", row.symbol, other.symbol), ("side", row.side, other.side),
        ("quantity", row.quantity, other.quantity), ("price", row.price_per_unit, other.price_per_unit),
        ("timestamp", row.trade_timestamp, other.trade_timestamp), ("order_id", row.order_id, other.order_id),
    )
    return [name for name, a, b in pairs if a != b]


def _differences_from_trade(row: ParsedTradeRow, trade: Trade) -> list[str]:
    """Comparable source fields (OPEN-6) against the ORIGINAL row; an existing NULL never conflicts."""
    pairs = (
        ("isin", row.isin, trade.isin, True), ("symbol", row.symbol, trade.symbol, False),
        ("side", row.side, trade.side, False), ("quantity", row.quantity, trade.quantity, False),
        ("price", row.price_per_unit, trade.price_per_unit, False),
        ("timestamp", row.trade_timestamp, trade.trade_timestamp, False),
        ("order_id", row.order_id, trade.order_id, True),
    )
    return [name for name, a, b, nullable in pairs if not (nullable and b is None) and a != b]


def _entry(trade: Trade) -> LedgerEntry:
    return LedgerEntry(
        id=trade.id, instrument=Instrument(trade.symbol, trade.exchange), side=trade.side, quantity=trade.quantity,
        price_per_unit=trade.price_per_unit, brokerage_fee=trade.brokerage_fee, taxes=trade.taxes,
        trade_timestamp=trade.trade_timestamp, recorded_at=trade.recorded_at,
    )


def _canonical_key(row: ParsedTradeRow) -> tuple:
    """Ledger order (timestamp, BUY before SELL) then int(trade_id); the file line only makes ties total."""
    return (row.trade_timestamp, 0 if row.side is TradeSide.BUY else 1, int(row.broker_trade_id), row.line)


class TradebookImportService:
    def __init__(
        self,
        session: Session,
        ledger: LedgerService,
        trades: TradeRepository,
        batches: ImportBatchRepository,
        *,
        clock: Callable[[], datetime],
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._session = session
        self._ledger = ledger
        self._trades = trades
        self._batches = batches
        self._clock = clock
        self._new_id = id_factory

    @classmethod
    def for_session(
        cls, session: Session, *, clock: Callable[[], datetime], id_factory: Callable[[], UUID] = uuid4
    ) -> "TradebookImportService":
        return cls(
            session,
            LedgerService.for_session(session, clock=clock, id_factory=id_factory),
            TradeRepository(session),
            ImportBatchRepository(session),
            clock=clock,
            id_factory=id_factory,
        )

    def status(self, *, user_id: UUID) -> ImportStatus:
        """Rejected rows are not stored, only counted. A re-upload of the same file replaces that file's earlier count (the
        re-upload is the retry), so only the newest batch per file hash counts; a different file's rejections always count."""
        seen: set[str] = set()
        out: list[BatchSummary] = []
        total = 0
        for batch in self._batches.list_for_user(user_id=user_id):
            superseded = batch.file_sha256 in seen
            seen.add(batch.file_sha256)
            if not superseded:
                total += batch.rejected_total
            out.append(BatchSummary(batch, superseded))
        return ImportStatus(tuple(out), total)

    def import_tradebook(self, *, user_id: UUID, file_name: str, content: bytes) -> ImportResult:
        """Import one upload. File-level problems raise InvalidImportFileError before anything is written;
        a held user lock raises LedgerBusyError before the batch is created."""
        file_sha256 = hashlib.sha256(content).hexdigest()
        parsed = parse_tradebook(content)  # no database access; raises InvalidImportFileError
        try:
            self._ledger.lock_user(user_id=user_id)
            batch = self._batches.add(
                user_id=user_id, id=self._new_id(), file_name=file_name, file_sha256=file_sha256,
                created_at=self._clock(),
            )
            batch_id = batch.id
            rows = sorted(parsed.rows, key=lambda r: r.line)
            counts = _Counts()
            new_rows = self._classify_in_file_order(user_id, rows, counts)
            self._insert_in_canonical_order(user_id, batch_id, new_rows, counts)

            rejected_total = len(parsed.rejections) + len(counts.rejections)
            if counts.imported + counts.duplicates + rejected_total != parsed.total_rows:
                raise RuntimeError("import counters do not add up to total_rows")
            self._batches.update_counts(
                user_id=user_id, batch_id=batch_id, total_rows=parsed.total_rows, imported=counts.imported,
                duplicates=counts.duplicates, rejected_total=rejected_total,
            )
            self._session.commit()
        except BaseException:
            self._session.rollback()
            raise

        rejected = sorted([*parsed.rejections, *counts.rejections], key=lambda r: r.line)
        return ImportResult(
            import_batch_id=batch_id, file_name=file_name, file_sha256=file_sha256, total_rows=parsed.total_rows,
            imported=counts.imported, duplicates=counts.duplicates, rejected_total=rejected_total,
            rejected=tuple(rejected[: limits.MAX_LISTED_REJECTIONS]),
            quarantined_isins=tuple(sorted(counts.quarantined)),
        )

    # ---- pass 1: file order --------------------------------------------------

    def _classify_in_file_order(
        self, user_id: UUID, rows: list[ParsedTradeRow], counts: "_Counts"
    ) -> list[ParsedTradeRow]:
        """Duplicates and conflicts, before quarantine (7a). Returns the genuinely new rows, in file order.

        A repeated key is always compared with the FIRST occurrence's values, whatever became of that occurrence.
        """
        first_seen: dict[tuple[Exchange, str], ParsedTradeRow] = {}
        new_rows: list[ParsedTradeRow] = []
        for row in rows:
            key = (row.exchange, row.broker_trade_id)
            first = first_seen.get(key)
            if first is not None:
                counts.classify(row, _differences_from_row(row, first), earlier="earlier in this file")
                continue
            first_seen[key] = row
            existing = self._trades.original_by_key(
                user_id=user_id, broker=BROKER, exchange=row.exchange, broker_trade_id=row.broker_trade_id
            )
            if existing is None:
                new_rows.append(row)
            else:
                counts.classify(row, _differences_from_trade(row, existing), earlier="already in the ledger")
        return new_rows

    # ---- pass 2: canonical order ---------------------------------------------

    def _insert_in_canonical_order(
        self, user_id: UUID, batch_id: UUID, new_rows: list[ParsedTradeRow], counts: "_Counts"
    ) -> None:
        history: dict[str, list[LedgerEntry]] = defaultdict(list)
        keys: dict[UUID, HoldingKey] = {}
        for trade in self._trades.list_effective_for_isins(user_id=user_id, isins={r.isin for r in new_rows}):
            history[trade.isin].append(_entry(trade))
            keys[trade.id] = HoldingKey.for_isin(trade.isin)

        for row in sorted(new_rows, key=_canonical_key):
            if row.isin in counts.quarantined:
                counts.reject(row, AFTER_OVERSELL, f"{row.isin} had an oversell earlier in this import; row not imported")
                continue
            trade_id = self._new_id()
            candidate = LedgerEntry(
                id=trade_id, instrument=Instrument(row.symbol, row.exchange), side=row.side, quantity=row.quantity,
                price_per_unit=row.price_per_unit, brokerage_fee=_ZERO, taxes=_ZERO,
                trade_timestamp=row.trade_timestamp, recorded_at=self._clock(),
            )
            keys[trade_id] = HoldingKey.for_isin(row.isin)
            try:
                over = find_oversell([*history[row.isin], candidate], group_key=lambda e: keys[e.id])
            except NumericLimitError as exc:
                del keys[trade_id]
                counts.reject(row, NUMERIC_LIMIT_EXCEEDED, str(exc))
                continue
            if over is not None:
                del keys[trade_id]
                counts.quarantined.add(row.isin)
                counts.reject(
                    row, OVERSELL,
                    f"{over.requested} of {row.isin} would be sold while only {over.held} is held at that point "
                    "(the ledger is replayed in trade-time order; if the earlier tradebook is not uploaded yet, "
                    "upload it first and then re-upload this file)",
                )
                continue
            winner = self._insert(user_id, batch_id, row, candidate)
            if winner is None:
                history[row.isin].append(candidate)
            else:  # lost a unique-index race: classify against the row that won, never assume a duplicate
                del keys[trade_id]
                counts.classify(row, _differences_from_trade(row, winner), earlier="already in the ledger")
                continue
            counts.imported += 1

    def _insert(self, user_id: UUID, batch_id: UUID, row: ParsedTradeRow, candidate: LedgerEntry) -> Trade | None:
        """Insert in a savepoint. Returns None on success, or the existing original if the dedupe index refused it."""
        try:
            self._trades.add(
                user_id=user_id, id=candidate.id, symbol=row.symbol, name=None, asset_type=None, exchange=row.exchange,
                currency=Currency.INR, side=row.side, quantity=row.quantity, price_per_unit=row.price_per_unit,
                brokerage_fee=_ZERO, taxes=_ZERO, trade_timestamp=row.trade_timestamp,
                recorded_at=candidate.recorded_at, broker=BROKER, broker_trade_id=row.broker_trade_id,
                order_id=row.order_id, supersedes_trade_id=None, source=TradeSource.IMPORT, market_session=None,
                status=TradeStatus.EXECUTED, notes=None, isin=row.isin, charges_provided=False,
                import_batch_id=batch_id,
            )
        except IntegrityError:
            winner = self._trades.original_by_key(
                user_id=user_id, broker=BROKER, exchange=row.exchange, broker_trade_id=row.broker_trade_id
            )
            if winner is None:
                raise
            return winner
        return None


class _Counts:
    """Exactly one outcome per row: imported, duplicate, or rejected (service-side rejections are kept for the list)."""

    def __init__(self) -> None:
        self.imported = 0
        self.duplicates = 0
        self.rejections: list[RowRejection] = []
        self.quarantined: set[str] = set()

    def reject(self, row: ParsedTradeRow, code: str, message: str) -> None:
        self.rejections.append(RowRejection(row.line, code, message))

    def classify(self, row: ParsedTradeRow, differences: list[str], *, earlier: str) -> None:
        if not differences:
            self.duplicates += 1
            return
        self.reject(
            row, CONFLICTING_DUPLICATE,
            f"trade_id {row.broker_trade_id} on {row.exchange.value} is {earlier} with different "
            f"{', '.join(differences)}; row not imported",
        )
