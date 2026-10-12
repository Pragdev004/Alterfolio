"""The historical-bar port is provider-neutral (Feature 004, plan sections 2-3, decision R3)."""

import ast
import dataclasses
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import pytest

from app.domain.enums import Currency, Exchange
from app.domain.instrument import Instrument
from app.providers.market import history_port
from app.providers.market.history_port import (
    BarFailure,
    BarFailureKind,
    HistoricalBarProvider,
    RawBar,
    RawBarBatch,
)

PORT_FILE = Path(history_port.__file__)
NOW = datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc)
INST = Instrument("ZZTEST", Exchange.NSE)


def raw_bar(**kw):
    fields = dict(
        timestamp=datetime(2026, 3, 9, 3, 45, tzinfo=timezone.utc), session_date=date(2026, 3, 9),
        open=D("1"), high=D("2"), low=D("1"), close=D("2"), adjusted_close=D("2"), volume=0,
    )
    fields.update(kw)
    return RawBar(**fields)


def test_field_sets_are_exactly_the_neutral_contract():
    assert [f.name for f in dataclasses.fields(RawBar)] == [
        "timestamp", "session_date", "open", "high", "low", "close", "adjusted_close", "volume",
    ]
    assert [f.name for f in dataclasses.fields(RawBarBatch)] == [
        "instrument", "bars", "currency", "source", "retrieved_at", "exchange_utc_offset",
        "rows_returned", "empty_rows_excluded",
    ]
    assert [f.name for f in dataclasses.fields(BarFailure)] == ["kind", "detail"]
    assert {k.value for k in BarFailureKind} == {"NOT_FOUND", "PROVIDER_ERROR", "INVALID_RESPONSE"}


def test_value_types_are_frozen():
    bar = raw_bar()
    with pytest.raises(dataclasses.FrozenInstanceError):
        bar.volume = 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        BarFailure(BarFailureKind.NOT_FOUND, "x").detail = "y"


def test_port_source_names_no_provider_or_provider_field():
    text = PORT_FILE.read_text(encoding="utf-8").lower()
    for word in ("yahoo", "gmtoffset", "regularmarket", "adjclose", "pricehint", "exchangename", "httpx", "chart"):
        assert word not in text, word


def test_port_imports_only_stdlib_and_domain():
    tree = ast.parse(PORT_FILE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
            [node.module or ""] if isinstance(node, ast.ImportFrom) and not node.level else [])
        for name in names:
            assert name.split(".")[0] in sys.stdlib_module_names or name.startswith("app.domain"), name


def test_port_has_no_float_use():
    for node in ast.walk(ast.parse(PORT_FILE.read_text(encoding="utf-8"))):
        assert not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "float")
        assert not (isinstance(node, ast.Constant) and isinstance(node.value, float))


def test_a_non_vendor_fake_provider_satisfies_the_protocol_and_returns_neutral_values():
    class FakeProvider:
        def get_daily_bars(self, instrument, start, end, retrieved_at):
            if instrument.symbol == "MISSING":
                return BarFailure(BarFailureKind.NOT_FOUND, "no such listing")
            return RawBarBatch(
                instrument=instrument, bars=(raw_bar(),), currency=Currency.INR, source="fake-provider",
                retrieved_at=retrieved_at, exchange_utc_offset=timedelta(hours=5, minutes=30),
                rows_returned=1, empty_rows_excluded=0,
            )

    fake = FakeProvider()
    assert isinstance(fake, HistoricalBarProvider)
    ok = fake.get_daily_bars(INST, date(2026, 3, 1), date(2026, 3, 9), NOW)
    assert isinstance(ok, RawBarBatch) and ok.bars[0].adjusted_close == D("2")
    bad = fake.get_daily_bars(Instrument("MISSING", Exchange.NSE), date(2026, 3, 1), date(2026, 3, 9), NOW)
    assert isinstance(bad, BarFailure) and bad.kind is BarFailureKind.NOT_FOUND
