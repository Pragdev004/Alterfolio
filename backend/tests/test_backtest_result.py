"""Backtest result: JSON form, fingerprint, provenance and immutability (Feature 005 step 6)."""

import dataclasses
import json
import re
from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

from app.quant.backtest.engine import run_backtest
from tests.backtest_helpers import A, B, PRICES, WEEK, Scripted, config, make_series

D1, D2, D3, D4, D5 = WEEK


def run(plan=None, version="1", prices=PRICES, **params):
    return run_backtest([make_series(prices=prices)], config(), Scripted(plan or {D1: {A: D(10)}}, version, **params))


def test_json_form_has_the_contract_sections_and_canonical_decimal_text():
    d = run().to_dict()
    assert set(d) == {"schema_version", "as_of", "provenance", "inputs", "values"} and d["schema_version"] == 1
    values = d["values"]
    assert values["final_cash"] == "8960" and values["fills"][0]["notional"] == "1040"
    assert values["equity_curve"][1] == {"date": "2026-03-03", "cash": "8960", "positions_value": "1060", "equity": "10020"}
    assert d["inputs"]["config"]["initial_cash"] == "10000" and d["inputs"]["config"]["price_basis"] == "SPLIT_ADJUSTED_OPEN_CLOSE"
    assert values["calendar"] == {"first_date": "2026-03-02", "last_date": "2026-03-06", "session_count": 5, "dropped_dates": []}
    json.dumps(d)  # plain JSON types only
    assert not re.search(r"\d[eE][+-]?\d", json.dumps(d["values"]))  # never exponent notation


def test_assumptions_label_the_result_gross_price_only():
    assert run().to_dict()["provenance"]["assumptions"] == {
        "costs": "NONE", "dividends": "EXCLUDED", "fill": "NEXT_SESSION_OPEN", "mark": "CLOSE",
        "share_units": "SPLIT_ADJUSTED", "shares": "WHOLE", "slippage": "NONE", "taxes": "NONE"}


def test_provenance_copies_each_input_series_and_as_of_is_the_minimum_cutoff():
    late = datetime(2026, 3, 25, 10, 0, tzinfo=timezone.utc)
    early = datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc)
    result = run_backtest([make_series(A, retrieved_at=late), make_series(B, retrieved_at=early)], config(), Scripted({}))
    assert result.as_of == early and result.to_dict()["as_of"] == "2026-03-20T10:00:00Z"
    first = result.to_dict()["provenance"]["series"][0]
    assert first["fingerprint"] == make_series(A, retrieved_at=late).fingerprint
    assert first["knowledge_basis"] == "AS_FETCHED_AT_RETRIEVAL" and first["bar_count"] == 5


def test_same_inputs_give_the_same_fingerprint_and_to_dict_matches_it():
    one, two = run(), run()
    assert one.fingerprint == two.fingerprint and re.fullmatch(r"[0-9a-f]{64}", one.fingerprint)
    assert one.to_dict()["provenance"]["result_fingerprint"] == one.fingerprint


@pytest.mark.parametrize(
    "variant",
    [
        dict(version="2"),
        dict(lookback=D("20")),
        dict(prices={**PRICES, D5: ("109", "112")}),
        dict(plan={D1: {A: D(11)}}),
    ],
)
def test_any_changed_strategy_version_parameter_bar_or_decision_changes_the_fingerprint(variant):
    assert run(**variant).fingerprint != run().fingerprint


def test_a_changed_parameter_value_changes_the_fingerprint():
    assert run(lookback=D("20")).fingerprint != run(lookback=D("21")).fingerprint


def test_strategy_identity_is_recorded_verbatim():
    inputs = run(version="7", window=5).to_dict()["inputs"]["strategy"]
    assert inputs == {"strategy_id": "scripted", "version": "7", "parameters": [["window", "5"]]}


def test_mutating_to_dict_output_never_changes_the_result():
    result = run()
    before = result.fingerprint
    snapshot = result.to_dict()
    snapshot["values"]["fills"].clear()
    snapshot["values"]["final_cash"] = "0"
    snapshot["provenance"]["series"][0]["source"] = "evil"
    again = result.to_dict()
    assert again["values"]["final_cash"] == "8960" and len(again["values"]["fills"]) == 1
    assert again["provenance"]["series"][0]["source"] == "fake" and result.fingerprint == before


def test_result_is_frozen_and_holds_only_tuples():
    result = run()
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.final_cash = D(0)  # type: ignore[misc]
    for field in dataclasses.fields(result):
        value = getattr(result, field.name)
        assert not isinstance(value, (list, dict, set)), field.name
