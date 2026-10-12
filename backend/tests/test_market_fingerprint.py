"""Exact canonical Decimal text and the series fingerprint (plan section 8, F1)."""

import hashlib
import re
from datetime import date, datetime, timezone
from decimal import Decimal as D

import pytest

from app.domain.enums import Currency, Exchange
from app.domain.instrument import Instrument
from app.quant.market_data.fingerprint import FINGERPRINT_VERSION, canonical_decimal, compute_fingerprint
from tests.market_helpers import INSTRUMENT, mk_bar

D1, D2, D3 = date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1186.4", "1186.4"), ("1186.400", "1186.4"), ("100", "100"), ("100.00", "100"), ("1E+3", "1000"),
        ("1.5E-7", "0.00000015"), ("0.0", "0"), ("0", "0"), ("-0", "0"), ("-1.50", "-1.5"),
        ("0.5", "0.5"), ("920.7383422851562", "920.7383422851562"), ("1477.4749755859375", "1477.4749755859375"),
        ("1E-20", "0.00000000000000000001"), ("1E+13", "10000000000000"),
    ],
)
def test_canonical_decimal_is_plain_fixed_point_without_trailing_zeros(value, expected):
    assert canonical_decimal(D(value)) == expected


def test_canonical_decimal_is_exact_beyond_the_default_context_precision():
    text = "12345678901234567890123456789012345.123456789012345678901"  # 56 digits, well past prec=28
    assert canonical_decimal(D(text)) == text


def test_canonical_decimal_rejects_non_decimals_and_non_finite():
    for bad in (D("NaN"), D("Infinity")):
        with pytest.raises(ValueError):
            canonical_decimal(bad)
    for bad in (1.5, 3, "1"):
        with pytest.raises(TypeError):
            canonical_decimal(bad)


def bars(**overrides):
    return (mk_bar(D1, **overrides), mk_bar(D2), mk_bar(D3))


def fp(bar_tuple=None, source="fake", instrument=INSTRUMENT, currency=Currency.INR):
    chosen = bars() if bar_tuple is None else bar_tuple
    return compute_fingerprint(source=source, instrument=instrument, currency=currency, bars=chosen)


def test_fingerprint_is_a_stable_sha256_hex():
    value = fp()
    assert re.fullmatch(r"[0-9a-f]{64}", value) and value == fp()
    assert FINGERPRINT_VERSION == 1


def test_fingerprint_equals_sha256_of_the_documented_canonical_json():
    b = (mk_bar(D1, open=D("100.50"), high=D("110"), low=D("90"), close=D("105"), adjusted_close=D("104.5"), volume=7),)
    expected = (
        '{"bars":[["2026-03-02T03:45:00Z","2026-03-02","100.5","110","90","105","104.5",7]],'
        '"currency":"INR","fingerprint_version":1,"frequency":"1d",'
        '"instrument":{"exchange":"NSE","symbol":"ZZTEST"},"source":"fake"}'
    )
    assert fp(b) == hashlib.sha256(expected.encode("utf-8")).hexdigest()


def test_numerically_equal_decimals_with_different_trailing_zeros_hash_equal():
    assert fp(bars(close=D("105.0"), adjusted_close=D("104.50"))) == fp(bars(close=D("105"), adjusted_close=D("104.5")))


def test_last_digit_of_a_thirteen_dp_value_changes_the_hash():
    a = bars(open=D("100.0000000000001"), high=D("110"), low=D("90"), close=D("105"))
    b = bars(open=D("100.0000000000002"), high=D("110"), low=D("90"), close=D("105"))
    assert fp(a) != fp(b)


@pytest.mark.parametrize(
    "overrides",
    [
        dict(open=D("100.5")), dict(high=D("111")), dict(low=D("89")), dict(close=D("106")),
        dict(adjusted_close=D("104.6")), dict(volume=1001), dict(volume=0),
        dict(timestamp=datetime(2026, 3, 2, 3, 45, 1, tzinfo=timezone.utc)),
        dict(timestamp=datetime(2026, 3, 2, 12, 45, tzinfo=timezone.utc)),
    ],
)
def test_every_bar_field_is_part_of_the_fingerprint(overrides):
    assert fp(bars(**overrides)) != fp()


def test_identity_source_and_bar_set_are_part_of_the_fingerprint():
    base = fp()
    assert fp(instrument=Instrument("ZZOTHER", Exchange.NSE)) != base
    assert fp(instrument=Instrument("ZZTEST", Exchange.BSE)) != base
    assert fp(source="other") != base
    assert fp(bars()[:2]) != base                  # a bar removed
    assert fp((mk_bar(D1), mk_bar(D3))) != base    # a bar replaced by a gap
    assert fp(()) != base and re.fullmatch(r"[0-9a-f]{64}", fp(()))  # empty series still fingerprints


def test_bar_order_is_significant():
    assert fp(tuple(reversed(bars()))) != fp()
