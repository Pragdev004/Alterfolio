"""Pure tradebook parser (plan 002/002a/002b). Synthetic data only; no real Zerodha values appear here."""
import csv
import io
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.domain import limits
from app.domain.enums import Exchange, TradeSide
from app.services.errors import InvalidImportFileError
from app.services.tradebook_parser import COLUMNS, parse_tradebook

FIXTURE = Path(__file__).parent / "fixtures" / "tradebook_synthetic.csv"

GOOD = {
    "symbol": "ALPHACO", "isin": "ZZ0ALPHA0001", "trade_date": "2020-03-02", "exchange": "NSE", "segment": "EQ",
    "series": "EQ", "trade_type": "buy", "auction": "false", "quantity": "10.000000", "price": "100.500000",
    "trade_id": "900001", "order_id": "1000000000000001", "order_execution_time": "2020-03-02T09:30:00",
}


def make(*rows: dict, header=COLUMNS, newline="\n") -> bytes:
    """CSV bytes; each row is a dict overriding GOOD (a value of None removes nothing; use '' for empty)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator=newline)
    writer.writerow(header)
    for overrides in rows:
        cells = {**GOOD, **overrides}
        writer.writerow([cells[name] for name in header])
    return buffer.getvalue().encode("utf-8")


def only_rejection(**overrides):
    result = parse_tradebook(make(overrides))
    assert result.total_rows == 1 and result.rows == (), result
    (rejection,) = result.rejections
    assert rejection.line == 2
    return rejection


def only_row(**overrides):
    result = parse_tradebook(make(overrides))
    assert result.rejections == (), result.rejections
    (row,) = result.rows
    return row


# ---- the synthetic fixture ------------------------------------------------------------------------------------------

def test_fixture_parses_into_valid_rows_and_one_malformed_row():
    result = parse_tradebook(FIXTURE.read_bytes())
    assert result.total_rows == 7 and len(result.rows) == 6
    assert [(r.line, r.code) for r in result.rejections] == [(8, "invalid_side")]
    first = result.rows[0]
    assert (first.line, first.symbol, first.isin, first.exchange, first.side) == (
        2, "ALPHACO", "ZZ0ALPHA0001", Exchange.NSE, TradeSide.BUY,
    )
    assert first.broker == "ZERODHA" and first.broker_trade_id == "900001"
    assert first.trade_timestamp == datetime(2020, 3, 2, 4, 0, tzinfo=timezone.utc)


def test_fixture_partial_fills_and_two_exchanges_stay_separate_rows():
    rows = parse_tradebook(FIXTURE.read_bytes()).rows
    assert rows[0].order_id == rows[1].order_id and rows[0].broker_trade_id != rows[1].broker_trade_id
    assert rows[2].exchange is Exchange.BSE and rows[2].isin == rows[0].isin
    assert rows[2].broker_trade_id == rows[0].broker_trade_id  # same id on another exchange is a different trade


# ---- numbers --------------------------------------------------------------------------------------------------------

def test_decimals_are_kept_exactly_as_written():
    row = only_row(quantity="333.799988", price="7")
    assert row.quantity == Decimal("333.799988") and str(row.quantity) == "333.799988"
    assert str(row.price_per_unit) == "7" and row.price_per_unit.as_tuple().exponent == 0
    assert str(only_row(price="100.500000").price_per_unit) == "100.500000"


@pytest.mark.parametrize("text", ["1.0000000", "0.1234567", "1e3", "1E3", "+1", "-1", "NaN", "Infinity", ".5", "5.", "1,5",
                                  "1 000", " 1", "1 ", "١٢", "0x10", "--1"])
@pytest.mark.parametrize("column", ["quantity", "price"])
def test_non_plain_or_over_precise_numbers_are_invalid_number(column, text):
    assert only_rejection(**{column: text}).code == "invalid_number"


@pytest.mark.parametrize("text", ["0", "0.000000", "000"])
@pytest.mark.parametrize("column", ["quantity", "price"])
def test_zero_is_invalid_trade(column, text):
    assert only_rejection(**{column: text}).code == "invalid_trade"


def test_too_many_integer_digits_is_invalid_trade():
    assert only_rejection(quantity="123456789012345").code == "invalid_trade"
    assert only_row(quantity="00000000000000000001").quantity == Decimal("00000000000000000001")  # leading zeros are not size


def test_notional_at_or_above_the_limit_is_numeric_limit_exceeded():
    assert only_rejection(quantity="99999999999999", price="99999999999999").code == "numeric_limit_exceeded"
    assert only_rejection(quantity="1000000000", price="1000000").code == "numeric_limit_exceeded"  # exactly 10^15
    assert only_row(quantity="1000000000", price="999999.999999").quantity == Decimal("1000000000")


# ---- timestamps and dates -------------------------------------------------------------------------------------------

def test_ist_is_converted_to_utc_without_a_dst_or_tz_database():
    row = only_row(order_execution_time="2020-03-02T00:30:00", trade_date="2020-03-02")
    assert row.trade_timestamp == datetime(2020, 3, 1, 19, 0, tzinfo=timezone.utc)
    assert row.trade_timestamp.utcoffset().total_seconds() == 0
    row = only_row(order_execution_time="2020-07-15T23:59:59", trade_date="2020-07-15")
    assert row.trade_timestamp == datetime(2020, 7, 15, 18, 29, 59, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "text",
    ["2020-03-02", "2020-03-02T09:30:00.123", "2020-03-02T09:30:00Z", "2020-03-02T09:30:00+05:30", "2020-03-02 09:30:00",
     "2020-03-02T09:30", "2020-3-2T09:30:00", "2020-02-30T10:00:00", "2020-03-02T24:00:00", "2020-03-02T09:60:00",
     "2020-03-02T09:30:60", "20200302T093000", "2020-03-02T09:30:00 ", "٢020-03-02T09:30:00", "yesterday",
     "0001-01-01T00:00:00", "9999-12-31T23:59:59"],
)
def test_only_the_exact_ist_timestamp_shape_is_accepted(text):
    assert only_rejection(order_execution_time=text).code == "invalid_timestamp"


def test_timestamp_window_applies_after_conversion():
    assert only_rejection(order_execution_time="0001-01-02T00:00:00", trade_date="0001-01-02").code == "invalid_timestamp"
    edge = only_row(order_execution_time="0001-01-02T05:30:00", trade_date="0001-01-02")
    assert edge.trade_timestamp == limits.MIN_TRADE_TIMESTAMP


def test_trade_date_must_equal_the_ist_execution_date():
    rejection = only_rejection(trade_date="2020-03-03")
    assert rejection.code == "date_mismatch" and "2020-03-03" in rejection.message


@pytest.mark.parametrize("text", ["03/03/2020", "2020-3-3", "2020-02-30", "2020-03-02T00:00:00", "20200302"])
def test_malformed_trade_date_is_invalid_timestamp(text):
    assert only_rejection(trade_date=text).code == "invalid_timestamp"


# ---- categorical columns --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("exchange", ["nse", "NFO", "MCX", "NSE ", "Bse"])
def test_unsupported_exchange(exchange):
    assert only_rejection(exchange=exchange).code == "unsupported_exchange"


@pytest.mark.parametrize(("text", "side"), [("buy", TradeSide.BUY), ("BUY", TradeSide.BUY), ("Sell", TradeSide.SELL)])
def test_side_is_case_folded(text, side):
    assert only_row(trade_type=text).side is side


@pytest.mark.parametrize("text", ["hold", "buy ", "b", "short"])
def test_invalid_side(text):
    assert only_rejection(trade_type=text).code == "invalid_side"


@pytest.mark.parametrize("segment", ["FO", "eq", "EQ "])
def test_unsupported_segment(segment):
    assert only_rejection(segment=segment).code == "unsupported_segment"


@pytest.mark.parametrize(
    ("exchange", "series"),
    [("NSE", "A"), ("NSE", "BE"), ("NSE", "eq"), ("BSE", "EQ"), ("BSE", "B"), ("BSE", "a")],
)
def test_series_must_match_the_exchange(exchange, series):
    rejection = only_rejection(exchange=exchange, series=series)
    assert rejection.code == "unsupported_series" and series in rejection.message


def test_accepted_series_per_exchange():
    assert only_row(exchange="NSE", series="EQ").exchange is Exchange.NSE
    assert only_row(exchange="BSE", series="A").exchange is Exchange.BSE


@pytest.mark.parametrize("text", ["true", "True", "FALSE", "0", "no"])
def test_unsupported_auction(text):
    assert only_rejection(auction=text).code == "unsupported_auction"


# ---- ISIN, text, ids ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("isin", ["", "   "])
def test_empty_isin_is_missing_isin_not_missing_field(isin):
    assert only_rejection(isin=isin).code == "missing_isin"


@pytest.mark.parametrize(
    "isin",
    ["zz0alpha0001", "ZZ0ALPHA000", "ZZ0ALPHA00011", "ZZ0ALPHA000١", "ZZ0ALPHA000-", "ZZ0ALPHA0001\n", " ZZ0ALPHA0001",
     "ZZ0ALPHAÉ0001"],
)
def test_invalid_isin_is_never_normalized(isin):
    assert only_rejection(isin=isin).code == "invalid_trade"


def test_symbol_is_trimmed_and_checked():
    assert only_row(symbol="  ALPHACO ").symbol == "ALPHACO"
    assert only_rejection(symbol="A" * (limits.MAX_SYMBOL_LENGTH + 1)).code == "invalid_trade"
    assert only_rejection(symbol="AL\x00PHA").code == "invalid_trade"
    assert only_row(symbol="A" * limits.MAX_SYMBOL_LENGTH).symbol == "A" * limits.MAX_SYMBOL_LENGTH


@pytest.mark.parametrize("trade_id", ["12a", "-1", "1.5", "١", "9" * (limits.MAX_BROKER_TRADE_ID_LENGTH + 1)])
def test_trade_id_must_be_digits_within_the_limit(trade_id):
    assert only_rejection(trade_id=trade_id).code == "invalid_trade"


def test_trade_id_is_kept_as_raw_digits():
    assert only_row(trade_id="0900001").broker_trade_id == "0900001"


def test_order_id_is_stored_text_with_the_001_text_limits():
    assert only_row(order_id="ORD-1").order_id == "ORD-1"
    assert only_rejection(order_id="9" * (limits.MAX_ORDER_ID_LENGTH + 1)).code == "invalid_trade"


@pytest.mark.parametrize("empty", ["", "  ", "	"])
@pytest.mark.parametrize("other", [{}, {"quantity": ""}, {"symbol": " "}, {"exchange": "NFO"}, {"trade_type": "hold"}])
def test_empty_isin_is_missing_isin_whatever_else_is_wrong(other, empty):
    rejection = only_rejection(isin=empty, **other)
    assert rejection.code == "missing_isin" and "isin" in rejection.message


@pytest.mark.parametrize("column", [c for c in COLUMNS if c != "isin"])
@pytest.mark.parametrize("empty", ["", "  "])
def test_any_other_empty_required_value_is_missing_field(column, empty):
    rejection = only_rejection(**{column: empty})
    assert rejection.code == "missing_field" and column in rejection.message


def test_the_first_failing_check_wins_and_empty_beats_invalid():
    assert only_rejection(exchange="NFO", trade_type="hold").code == "unsupported_exchange"
    assert only_rejection(quantity="", trade_type="hold").code == "missing_field"
    assert only_rejection(isin="", trade_type="hold").code == "missing_isin"
    assert only_rejection(isin="bad", quantity="").code == "missing_field"  # a malformed (non-empty) isin comes later


def test_messages_quote_only_a_short_printable_excerpt():
    message = only_rejection(exchange="X" * 500 + "\x07").message
    assert len(message) < 120 and "\x07" not in message


# ---- row numbers, blank lines, totals --------------------------------------------------------------------------------

def test_line_numbers_are_physical_and_blank_lines_are_not_rows():
    text = ",".join(COLUMNS) + "\n\n" + ",".join(GOOD[c] for c in COLUMNS) + "\n\n\n"
    bad = {**GOOD, "trade_type": "hold", "trade_id": "900009"}
    text += ",".join(bad[c] for c in COLUMNS) + "\n   \n" + ",".join(GOOD[c] for c in COLUMNS)  # no trailing newline
    result = parse_tradebook(text.encode())
    assert result.total_rows == 3
    assert [row.line for row in result.rows] == [3, 8]
    assert [(r.line, r.code) for r in result.rejections] == [(6, "invalid_side")]


def test_blank_lines_before_the_header_are_skipped_but_still_counted_in_line_numbers():
    text = "\n\n" + make(GOOD).decode()
    assert parse_tradebook(text.encode()).rows[0].line == 4


def test_a_quoted_multiline_field_advances_the_next_row_by_its_physical_lines():
    text = make({"symbol": "A\nB\nC"}, {"trade_id": "900002"}).decode()
    result = parse_tradebook(text.encode())
    assert [row.line for row in result.rows] == [2, 5]
    assert result.rows[0].symbol == "A\nB\nC"


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_both_line_endings_and_a_utf8_bom_are_accepted(newline):
    data = b"\xef\xbb\xbf" + make(GOOD, {"trade_id": "900002"}, newline=newline)
    assert [row.line for row in parse_tradebook(data).rows] == [2, 3]


def test_rows_and_rejections_are_in_file_order_and_other_rows_still_parse():
    result = parse_tradebook(make(
        {"trade_id": "1"}, {"trade_type": "x", "trade_id": "2"}, {"trade_id": "3"}, {"auction": "true", "trade_id": "4"},
    ))
    assert [r.broker_trade_id for r in result.rows] == ["1", "3"]
    assert [(r.line, r.code) for r in result.rejections] == [(3, "invalid_side"), (5, "unsupported_auction")]
    assert result.total_rows == len(result.rows) + len(result.rejections) == 4


# ---- file-level failures --------------------------------------------------------------------------------------------

def invalid_file(data: bytes, **kwargs):
    with pytest.raises(InvalidImportFileError) as excinfo:
        parse_tradebook(data, **kwargs)
    assert excinfo.value.code == "invalid_import_file"
    return excinfo.value


def test_header_may_be_in_any_order_any_case_and_padded():
    header = [c.upper() if i % 2 else f" {c} " for i, c in enumerate(reversed(COLUMNS))]
    data = ",".join(header).encode() + b"\n" + ",".join(GOOD[c] for c in reversed(COLUMNS)).encode() + b"\n"
    assert parse_tradebook(data).rows[0].symbol == "ALPHACO"


@pytest.mark.parametrize(
    "header",
    [
        COLUMNS[:-1],
        COLUMNS + ("extra",),
        COLUMNS + ("symbol",),
        COLUMNS[:-1] + ("trade_id",),
        tuple(c if c != "series" else "serie" for c in COLUMNS),
        (),
    ],
)
def test_header_must_be_exactly_the_13_columns(header):
    body = ",".join(GOOD[c] for c in COLUMNS if c in header or True).encode() + b"\n"
    invalid_file(",".join(header).encode() + b"\n" + body)


def test_empty_blank_and_header_only_files_are_rejected():
    invalid_file(b"")
    invalid_file(b"\n\n  \n")
    invalid_file((",".join(COLUMNS) + "\n\n").encode())


def test_non_utf8_is_rejected():
    invalid_file(make(GOOD) + b"\xff\xfe")
    invalid_file(make(GOOD).decode().encode("utf-16"))


def test_a_row_with_the_wrong_number_of_columns_fails_the_whole_file():
    good = ",".join(GOOD[c] for c in COLUMNS)
    invalid_file((",".join(COLUMNS) + "\n" + good + "\n" + good + ",extra\n").encode())
    invalid_file((",".join(COLUMNS) + "\n" + good + "\n" + good.rsplit(",", 1)[0] + "\n").encode())
    assert "line 3" in str(invalid_file((",".join(COLUMNS) + "\n" + good + "\nonly,two\n").encode()))


def test_malformed_csv_quoting_fails_the_whole_file():
    good = ",".join(GOOD[c] for c in COLUMNS)
    invalid_file((",".join(COLUMNS) + "\n" + good.replace("ALPHACO", '"ALPHACO') + "\n").encode())
    invalid_file((",".join(COLUMNS) + "\n" + good.replace("ALPHACO", '"ALPHA"CO') + "\n").encode())


def test_row_cap_is_enforced_by_data_rows_not_lines():
    rows = [{"trade_id": str(900000 + i)} for i in range(limits.MAX_IMPORT_ROWS)]
    result = parse_tradebook(make(*rows))
    assert result.total_rows == limits.MAX_IMPORT_ROWS == 5000 and len(result.rows) == 5000
    invalid_file(make(*rows, {"trade_id": "1"}))
    padded = make(*rows).decode().replace("\n", "\n\n")  # blank lines never count
    assert parse_tradebook(padded.encode()).total_rows == 5000


def test_rejected_rows_count_toward_the_row_cap():
    invalid_file(make(*[{"trade_type": "x"} for _ in range(4)]), max_rows=3)


# ---- the final row-code taxonomy in one place (owner decisions, step 3 review) --------------------------------------

@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        # plain unsigned decimal text only; this is an import-format rule, independent of Feature 001's parsing
        ({"quantity": "1.0000001"}, "invalid_number"),
        ({"price": "1.0000000"}, "invalid_number"),  # >6 places as written, even with trailing zeros
        ({"quantity": "1e3"}, "invalid_number"),
        ({"price": "1E-2"}, "invalid_number"),
        ({"quantity": "+1"}, "invalid_number"),
        ({"price": "-1"}, "invalid_number"),
        ({"quantity": "NaN"}, "invalid_number"),
        ({"price": "Infinity"}, "invalid_number"),
        ({"price": "-Infinity"}, "invalid_number"),
        # all timestamp and date failures are invalid_timestamp
        ({"order_execution_time": "2020-03-02T09:30:00Z"}, "invalid_timestamp"),  # shape
        ({"order_execution_time": "2020-02-30T09:30:00"}, "invalid_timestamp"),  # impossible datetime
        ({"order_execution_time": "0001-01-01T00:00:00", "trade_date": "0001-01-01"}, "invalid_timestamp"),  # UTC overflow
        ({"order_execution_time": "0001-01-02T00:00:00", "trade_date": "0001-01-02"}, "invalid_timestamp"),  # before window
        ({"order_execution_time": "9999-12-31T23:59:59", "trade_date": "9999-12-31"}, "invalid_timestamp"),  # after window
        ({"trade_date": "2020-3-2"}, "invalid_timestamp"),  # trade_date shape
        ({"trade_date": "2020-02-30"}, "invalid_timestamp"),  # trade_date not a real date
        ({"trade_date": "2020-03-03"}, "date_mismatch"),  # real date, not the IST execution date
        # unchanged mappings
        ({"quantity": "0"}, "invalid_trade"),
        ({"price": "0.000000"}, "invalid_trade"),
        ({"quantity": "123456789012345"}, "invalid_trade"),  # 15 integer digits
        ({"price": "123456789012345.5"}, "invalid_trade"),
        ({"quantity": "1000000000", "price": "1000000"}, "numeric_limit_exceeded"),  # exactly 10^15
    ],
)
def test_final_row_rejection_taxonomy(overrides, code):
    assert only_rejection(**overrides).code == code


def test_the_last_instant_inside_the_window_is_accepted_and_one_second_later_is_not():
    last = only_row(order_execution_time="9999-12-31T05:29:59", trade_date="9999-12-31")
    assert last.trade_timestamp == datetime(9999, 12, 30, 23, 59, 59, tzinfo=timezone.utc)
    assert only_rejection(order_execution_time="9999-12-31T05:30:00", trade_date="9999-12-31").code == "invalid_timestamp"
