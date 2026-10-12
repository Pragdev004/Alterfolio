"""Pure Zerodha Console equity tradebook parser (plan 002, 002a OPEN-1..12, 002b row codes).

Bytes in, value objects out: no database, framework, clock or I/O. File-level problems (encoding, header, column count, row
cap, CSV syntax) raise `InvalidImportFileError`; every row-level problem becomes a `RowRejection` and the other rows
still parse. Nothing is repaired, rounded or defaulted. Deduplication, quarantine and persistence are not done here.

Row numbers are physical file lines, 1-based, where the record starts (the header is normally line 1). Blank lines are
skipped and never counted as data rows. A row is rejected with the FIRST failing check, in this order: missing_isin (empty
isin), missing_field (any other required cell empty), unsupported_exchange, invalid_side, unsupported_segment, unsupported_series, unsupported_auction,
then invalid_trade (isin format, symbol, trade_id, order_id), invalid_number / invalid_trade (quantity,
price), invalid_timestamp (execution time, trade_date shape), date_mismatch, numeric_limit_exceeded.
"""
import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.domain import limits
from app.domain.enums import Exchange, TradeSide
from app.domain.numeric import EXACT_CONTEXT, MAX_AMOUNT, SCALE
from app.services.errors import InvalidImportFileError

BROKER = "ZERODHA"
COLUMNS = (
    "symbol", "isin", "trade_date", "exchange", "segment", "series", "trade_type", "auction", "quantity", "price",
    "trade_id", "order_id", "order_execution_time",
)

IST = timezone(timedelta(hours=5, minutes=30))  # fixed offset: India has no DST; no tzdata dependency (OPEN-5)
_SERIES_BY_EXCHANGE = {Exchange.NSE: "EQ", Exchange.BSE: "A"}
_SIDES = {"buy": TradeSide.BUY, "sell": TradeSide.SELL}
_MAX_INTEGER_DIGITS = 14  # NUMERIC(20, 6), same bound as the 001 validator

_ISIN = re.compile(r"[A-Z0-9]{12}")
_DIGITS = re.compile(r"[0-9]+")
_DECIMAL = re.compile(r"([0-9]+)(?:\.([0-9]+))?")
_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_TIMESTAMP = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})")

# Row-level codes (002b normative table; `duplicate` is a count, not a rejection).
MISSING_FIELD = "missing_field"
MISSING_ISIN = "missing_isin"
UNSUPPORTED_EXCHANGE = "unsupported_exchange"
INVALID_SIDE = "invalid_side"
UNSUPPORTED_SEGMENT = "unsupported_segment"
UNSUPPORTED_SERIES = "unsupported_series"
UNSUPPORTED_AUCTION = "unsupported_auction"
INVALID_NUMBER = "invalid_number"
INVALID_TIMESTAMP = "invalid_timestamp"
DATE_MISMATCH = "date_mismatch"
INVALID_TRADE = "invalid_trade"
NUMERIC_LIMIT_EXCEEDED = "numeric_limit_exceeded"


@dataclass(frozen=True)
class ParsedTradeRow:
    """A validated, normalized row. `trade_timestamp` is an aware UTC instant; `broker_trade_id` is the raw digits."""

    line: int
    symbol: str
    isin: str
    exchange: Exchange
    side: TradeSide
    quantity: Decimal
    price_per_unit: Decimal
    trade_timestamp: datetime
    broker_trade_id: str
    order_id: str
    broker: str = BROKER


@dataclass(frozen=True)
class RowRejection:
    line: int
    code: str
    message: str


@dataclass(frozen=True)
class ParseResult:
    """`total_rows` counts data records (blank lines excluded) = len(rows) + len(rejections)."""

    total_rows: int
    rows: tuple[ParsedTradeRow, ...]
    rejections: tuple[RowRejection, ...]


class _Reject(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message


def _excerpt(value: str, limit: int = 40) -> str:
    """A short, printable-safe quote of a cell for messages."""
    safe = "".join(ch if ch.isprintable() else "?" for ch in value)
    return repr(safe if len(safe) <= limit else safe[:limit] + "...")


def _decode(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InvalidImportFileError("the file is not valid UTF-8") from None


def _header_map(record: list[str]) -> dict[str, int]:
    names = [cell.strip().casefold() for cell in record]
    duplicated = sorted({n for n in names if names.count(n) > 1})
    if duplicated:
        raise InvalidImportFileError(f"the header repeats column(s): {', '.join(duplicated)}")
    missing = [c for c in COLUMNS if c not in names]
    extra = [n for n in names if n not in COLUMNS]
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing {', '.join(missing)}")
        if extra:
            parts.append(f"unexpected {', '.join(_excerpt(n) for n in extra)}")
        raise InvalidImportFileError("the header does not match the 13 expected columns: " + "; ".join(parts))
    return {name: index for index, name in enumerate(names)}


def _decimal(name: str, text: str) -> Decimal:
    match = _DECIMAL.fullmatch(text)
    if match is None:
        raise _Reject(INVALID_NUMBER, f"{name} must be a plain unsigned decimal number, got {_excerpt(text)}")
    integer, fraction = match.groups()
    if fraction is not None and len(fraction) > SCALE:
        raise _Reject(INVALID_NUMBER, f"{name} has more than {SCALE} decimal places: {_excerpt(text)}")
    if len(integer.lstrip("0")) > _MAX_INTEGER_DIGITS:
        raise _Reject(INVALID_TRADE, f"{name} is too large: {_excerpt(text)}")
    value = Decimal(text)
    if value <= 0:
        raise _Reject(INVALID_TRADE, f"{name} must be greater than zero")
    return value


def _text(name: str, value: str, max_length: int) -> None:
    if "\x00" in value:
        raise _Reject(INVALID_TRADE, f"{name} must not contain NUL characters")
    if len(value) > max_length:
        raise _Reject(INVALID_TRADE, f"{name} is longer than {max_length} characters")


def _ist_date(year: int, month: int, day: int, text: str, field: str) -> datetime:
    try:
        return datetime(year, month, day)
    except ValueError:
        raise _Reject(INVALID_TIMESTAMP, f"{field} is not a real date: {_excerpt(text)}") from None


def _timestamp(text: str) -> tuple[datetime, datetime]:
    """Return (naive IST datetime, aware UTC instant). Only `YYYY-MM-DDTHH:MM:SS`; any zone, fraction or other shape fails."""
    match = _TIMESTAMP.fullmatch(text)
    if match is None:
        raise _Reject(INVALID_TIMESTAMP, f"order_execution_time must be YYYY-MM-DDTHH:MM:SS, got {_excerpt(text)}")
    year, month, day, hour, minute, second = (int(g) for g in match.groups())
    try:
        local = datetime(year, month, day, hour, minute, second)
        utc = local.replace(tzinfo=IST).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise _Reject(INVALID_TIMESTAMP, f"order_execution_time is not a supported instant: {_excerpt(text)}") from None
    if not limits.MIN_TRADE_TIMESTAMP <= utc <= limits.MAX_TRADE_TIMESTAMP:
        raise _Reject(INVALID_TIMESTAMP, f"order_execution_time is outside the supported window: {_excerpt(text)}")
    return local, utc


def _validate(line: int, cells: dict[str, str]) -> ParsedTradeRow:
    if not cells["isin"].strip():  # checked before the generic pass so that an empty ISIN is always missing_isin
        raise _Reject(MISSING_ISIN, "isin is empty")
    for name in COLUMNS:
        if name != "isin" and not cells[name].strip():
            raise _Reject(MISSING_FIELD, f"{name} is empty")

    try:
        exchange = Exchange(cells["exchange"])
    except ValueError:
        raise _Reject(UNSUPPORTED_EXCHANGE, f"exchange must be NSE or BSE, got {_excerpt(cells['exchange'])}") from None
    side = _SIDES.get(cells["trade_type"].casefold())
    if side is None:
        raise _Reject(INVALID_SIDE, f"trade_type must be buy or sell, got {_excerpt(cells['trade_type'])}")
    if cells["segment"] != "EQ":
        raise _Reject(UNSUPPORTED_SEGMENT, f"segment must be EQ, got {_excerpt(cells['segment'])}")
    expected_series = _SERIES_BY_EXCHANGE[exchange]
    if cells["series"] != expected_series:
        raise _Reject(
            UNSUPPORTED_SERIES,
            f"series must be {expected_series} on {exchange.value}, got {_excerpt(cells['series'])}",
        )
    if cells["auction"] != "false":
        raise _Reject(UNSUPPORTED_AUCTION, f"auction must be false, got {_excerpt(cells['auction'])}")

    isin = cells["isin"]
    if _ISIN.fullmatch(isin) is None:
        raise _Reject(INVALID_TRADE, f"isin must be 12 characters of A-Z and 0-9, got {_excerpt(isin)}")
    symbol = cells["symbol"].strip()
    _text("symbol", symbol, limits.MAX_SYMBOL_LENGTH)
    trade_id = cells["trade_id"]
    if _DIGITS.fullmatch(trade_id) is None:
        raise _Reject(INVALID_TRADE, f"trade_id must be digits, got {_excerpt(trade_id)}")
    _text("trade_id", trade_id, limits.MAX_BROKER_TRADE_ID_LENGTH)
    order_id = cells["order_id"]
    _text("order_id", order_id, limits.MAX_ORDER_ID_LENGTH)

    quantity = _decimal("quantity", cells["quantity"])
    price = _decimal("price", cells["price"])

    local, utc = _timestamp(cells["order_execution_time"])
    date_text = cells["trade_date"]
    date_match = _DATE.fullmatch(date_text)
    if date_match is None:
        raise _Reject(INVALID_TIMESTAMP, f"trade_date must be YYYY-MM-DD, got {_excerpt(date_text)}")
    trade_date = _ist_date(*(int(g) for g in date_match.groups()), date_text, "trade_date").date()
    if trade_date != local.date():
        raise _Reject(DATE_MISMATCH, f"trade_date {_excerpt(date_text)} differs from the execution date {local.date()}")

    if EXACT_CONTEXT.multiply(quantity, price) >= MAX_AMOUNT:
        raise _Reject(NUMERIC_LIMIT_EXCEEDED, f"quantity x price must be below {MAX_AMOUNT}")

    return ParsedTradeRow(
        line=line, symbol=symbol, isin=isin, exchange=exchange, side=side, quantity=quantity, price_per_unit=price,
        trade_timestamp=utc, broker_trade_id=trade_id, order_id=order_id,
    )


def parse_tradebook(content: bytes, *, max_rows: int = limits.MAX_IMPORT_ROWS) -> ParseResult:
    """Parse a whole tradebook. Raises InvalidImportFileError for file-level failures; otherwise never raises."""
    text = _decode(content)
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    header: dict[str, int] | None = None
    rows: list[ParsedTradeRow] = []
    rejections: list[RowRejection] = []
    total = 0
    previous_line = 0
    while True:
        try:
            record = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            raise InvalidImportFileError(f"the file is not valid CSV near line {previous_line + 1}: {exc}") from None
        start = previous_line + 1
        previous_line = reader.line_num
        if not record or (len(record) == 1 and not record[0].strip()):
            continue  # blank line
        if header is None:
            header = _header_map(record)
            continue
        if len(record) != len(COLUMNS):
            raise InvalidImportFileError(f"line {start} has {len(record)} columns; the header has {len(COLUMNS)}")
        total += 1
        if total > max_rows:
            raise InvalidImportFileError(f"the file has more than {max_rows} data rows")
        cells = {name: record[index] for name, index in header.items()}
        try:
            rows.append(_validate(start, cells))
        except _Reject as rejected:
            rejections.append(RowRejection(start, rejected.code, rejected.message))
    if header is None:
        raise InvalidImportFileError("the file has no header")
    if total == 0:
        raise InvalidImportFileError("the file has a header but no data rows")
    return ParseResult(total_rows=total, rows=tuple(rows), rejections=tuple(rejections))
