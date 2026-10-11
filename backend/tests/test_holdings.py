import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from uuid import UUID

import pytest

from app.domain.enums import Exchange, TradeSide
from app.domain.instrument import Instrument
from app.services.errors import OversellError
from app.services.holdings import (
    LedgerEntry,
    canonical_order,
    find_oversell,
    fold_holdings,
    fold_ledger,
)

T0 = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
RELIANCE_NSE = Instrument("RELIANCE", Exchange.NSE)
RELIANCE_BSE = Instrument("RELIANCE", Exchange.BSE)
TCS = Instrument("TCS", Exchange.NSE)
_n = 0


def entry(side, qty, price, minutes=0, inst=RELIANCE_NSE, recorded=0, fee=0, tax=0):
    global _n
    _n += 1
    return LedgerEntry(
        id=UUID(int=_n),
        instrument=inst,
        side=TradeSide(side),
        quantity=D(qty),
        price_per_unit=D(price),
        brokerage_fee=D(fee),
        taxes=D(tax),
        trade_timestamp=T0 + timedelta(minutes=minutes),
        recorded_at=T0 + timedelta(days=1, seconds=recorded),
    )


def test_empty_portfolio_is_an_empty_list():
    assert fold_holdings([]) == []


def test_weighted_average_cost_of_two_buys():
    (h,) = fold_holdings([entry("BUY", 10, 100, 0), entry("BUY", 10, 120, 1)])
    assert h.instrument == RELIANCE_NSE
    assert h.quantity == D(20)
    assert h.invested_amount == D(2200)
    assert h.average_buy_price == D(110)


def test_partial_sell_keeps_average_and_reduces_invested():
    (h,) = fold_holdings(
        [entry("BUY", 10, 100, 0), entry("BUY", 10, 120, 1), entry("SELL", 5, 200, 2)]
    )
    assert h.quantity == D(15)
    assert h.invested_amount == D(1650)
    assert h.average_buy_price == D(110)


def test_full_exit_removes_instrument_and_reentry_starts_fresh():
    entries = [entry("BUY", 10, 100, 0), entry("SELL", 10, 150, 1)]
    assert fold_holdings(entries) == []
    (h,) = fold_holdings(entries + [entry("BUY", 4, 50, 2)])
    assert (h.quantity, h.invested_amount, h.average_buy_price) == (D(4), D(200), D(50))


def test_full_exit_after_inexact_average_leaves_no_dust():
    entries = [
        entry("BUY", 1, 100, 0),
        entry("BUY", 2, "100.5", 1),  # invested 301, quantity 3, average 100.333...
        entry("SELL", 1, 120, 2),
        entry("SELL", 2, 120, 3),
    ]
    assert fold_holdings(entries) == []
    (h,) = fold_holdings(entries[:2])
    assert h.average_buy_price == D(301) / D(3)


def test_fractional_quantities_and_prices_are_exact():
    (h,) = fold_holdings([entry("BUY", "0.5", "101.25", 0), entry("BUY", "1.5", "99.75", 1)])
    assert h.quantity == D("2.0")
    assert h.invested_amount == D("0.5") * D("101.25") + D("1.5") * D("99.75")
    assert isinstance(h.invested_amount, D)


def test_nse_and_bse_listings_are_separate_instruments():
    holdings = fold_holdings(
        [entry("BUY", 1, 10, 0, RELIANCE_NSE), entry("BUY", 2, 20, 1, RELIANCE_BSE)]
    )
    assert [(h.instrument, h.quantity) for h in holdings] == [
        (RELIANCE_BSE, D(2)),
        (RELIANCE_NSE, D(1)),
    ]


def test_holdings_sorted_by_symbol_then_exchange():
    holdings = fold_holdings([entry("BUY", 1, 1, 0, TCS), entry("BUY", 1, 1, 1, RELIANCE_NSE)])
    assert [h.instrument.symbol for h in holdings] == ["RELIANCE", "TCS"]


def test_sell_above_held_is_an_oversell():
    entries = [entry("BUY", 5, 100, 0), entry("SELL", 6, 100, 1)]
    over = find_oversell(entries)
    assert over is not None
    assert over.instrument == RELIANCE_NSE
    assert (over.held, over.requested) == (D(5), D(6))
    with pytest.raises(OversellError):
        fold_holdings(entries)


def test_sell_before_any_buy_is_an_oversell():
    assert find_oversell([entry("SELL", 1, 100, 0)]) is not None


def test_valid_history_has_no_oversell():
    assert find_oversell([entry("BUY", 5, 100, 0), entry("SELL", 5, 100, 1)]) is None


def test_equal_timestamp_buy_sorts_before_sell():
    sell = entry("SELL", 5, 100, 0, recorded=0)
    buy = entry("BUY", 5, 100, 0, recorded=10)
    assert [e.side for e in canonical_order([sell, buy])] == [TradeSide.BUY, TradeSide.SELL]
    assert find_oversell([sell, buy]) is None


def test_canonical_order_ties_break_on_recorded_at_then_id():
    a = entry("BUY", 1, 1, 0, recorded=5)
    b = entry("BUY", 1, 1, 0, recorded=1)
    assert canonical_order([a, b]) == [b, a]
    c = entry("BUY", 1, 1, 0, recorded=1)
    assert canonical_order([c, b]) == sorted([c, b], key=lambda e: e.id)


def test_insertion_order_does_not_change_the_result():
    entries = [
        entry("BUY", 10, 100, 0),
        entry("BUY", 5, 110, 1),
        entry("SELL", 7, 130, 2),
        entry("BUY", 3, 90, 3, TCS),
    ]
    expected = fold_holdings(entries)
    rng = random.Random(7)
    for _ in range(10):
        shuffled = entries[:]
        rng.shuffle(shuffled)
        assert fold_holdings(shuffled) == expected


def test_as_of_is_inclusive_and_ignores_later_trades():
    first = entry("BUY", 10, 100, 0)
    second = entry("BUY", 10, 200, 60)
    at_first = fold_holdings([first, second], as_of=first.trade_timestamp)
    assert at_first[0].quantity == D(10)
    assert at_first[0].average_buy_price == D(100)
    later = entry("SELL", 4, 300, 120)
    assert fold_holdings([first, second, later], as_of=second.trade_timestamp)[0].quantity == D(20)
    assert fold_holdings([first], as_of=T0 - timedelta(seconds=1)) == []


def test_as_of_must_be_timezone_aware():
    with pytest.raises(ValueError):
        fold_holdings([entry("BUY", 1, 1)], as_of=datetime(2026, 1, 1))


# ---- fees and taxes (buy-side raise cost; sell-side reduce net proceeds / realized P&L) ----


def test_buy_fee_and_tax_are_part_of_acquisition_cost():
    (h,) = fold_holdings([entry("BUY", 10, 100, 0, fee=10, tax=5)])
    assert h.invested_amount == D(1015)
    assert h.average_buy_price == D("101.5")


def test_average_cost_across_buys_includes_each_buys_fees():
    (h,) = fold_holdings([entry("BUY", 10, 100, 0, fee=10, tax=5), entry("BUY", 10, 120, 1)])
    assert (h.quantity, h.invested_amount, h.average_buy_price) == (D(20), D(2215), D("110.75"))


def test_sell_fees_reduce_net_proceeds_and_realized_pnl_not_average_cost():
    entries = [
        entry("BUY", 10, 100, 0, fee=10, tax=5),
        entry("BUY", 10, 120, 1),
        entry("SELL", 5, 200, 2, fee=20, tax=10),
    ]
    summary = fold_ledger(entries)
    (h,) = summary.holdings
    assert (h.quantity, h.invested_amount, h.average_buy_price) == (D(15), D("1661.25"), D("110.75"))
    (r,) = summary.realized
    assert r.instrument == RELIANCE_NSE
    assert r.net_sale_proceeds == D(970)
    assert r.cost_of_sold == D("553.75")
    assert r.realized_pnl == D("416.25")


def test_larger_sell_fees_never_move_the_remaining_average():
    base = [entry("BUY", 10, 100, 0, fee=10), entry("SELL", 4, 150, 1)]
    heavy = [entry("BUY", 10, 100, 0, fee=10), entry("SELL", 4, 150, 1, fee=500, tax=300)]
    (a,) = fold_holdings(base)
    (b,) = fold_holdings(heavy)
    assert a.average_buy_price == b.average_buy_price == D(101)
    assert a.invested_amount == b.invested_amount
    assert fold_ledger(heavy).realized[0].realized_pnl == fold_ledger(base).realized[0].realized_pnl - D(800)


def test_full_exit_realizes_exactly_and_is_still_reported():
    entries = [entry("BUY", 10, 100, 0, fee=10), entry("SELL", 10, 150, 1, fee=15, tax=5)]
    summary = fold_ledger(entries)
    assert summary.holdings == []
    (r,) = summary.realized
    assert (r.net_sale_proceeds, r.cost_of_sold, r.realized_pnl) == (D(1480), D(1010), D(470))


def test_a_loss_is_a_negative_realized_pnl():
    (r,) = fold_ledger([entry("BUY", 10, 100, 0), entry("SELL", 10, 90, 1, fee=5)]).realized
    assert r.realized_pnl == D(-105)


def test_buy_only_history_has_no_realized_entries():
    assert fold_ledger([entry("BUY", 10, 100, 0, fee=3)]).realized == []
    assert fold_ledger([]).realized == []


def test_realized_is_per_instrument_and_sorted():
    summary = fold_ledger(
        [
            entry("BUY", 1, 10, 0, TCS), entry("SELL", 1, 12, 1, TCS),
            entry("BUY", 1, 10, 2, RELIANCE_NSE), entry("SELL", 1, 11, 3, RELIANCE_NSE),
        ]
    )
    assert [(r.instrument.symbol, r.realized_pnl) for r in summary.realized] == [
        ("RELIANCE", D(1)),
        ("TCS", D(2)),
    ]


def test_realized_respects_as_of():
    buy = entry("BUY", 10, 100, 0)
    early = entry("SELL", 2, 110, 60, fee=1)
    late = entry("SELL", 3, 120, 120)
    before_late = fold_ledger([buy, early, late], as_of=early.trade_timestamp)
    assert before_late.realized[0].realized_pnl == D(19)
    assert fold_ledger([buy, early, late]).realized[0].realized_pnl == D(19) + D(60)
    assert fold_ledger([buy, early, late], as_of=buy.trade_timestamp).realized == []


def test_inexact_averages_leave_no_dust_across_partial_and_full_exits():
    entries = [
        entry("BUY", 3, 100, 0, fee=1),  # cost 301, average 301/3
        entry("SELL", 1, 110, 1),
        entry("SELL", 2, 110, 2),
    ]
    (r,) = fold_ledger(entries).realized
    assert r.cost_of_sold == D(301)
    assert r.realized_pnl == D(330) - D(301)
    assert all(isinstance(v, D) for v in (r.net_sale_proceeds, r.cost_of_sold, r.realized_pnl))


def test_zero_fees_match_the_price_only_math():
    (h,) = fold_holdings([entry("BUY", 10, 100, 0), entry("BUY", 10, 120, 1)])
    assert (h.invested_amount, h.average_buy_price) == (D(2200), D(110))


# ---- defect 3: running totals can never leave the exact-calculation range ----

from app.domain.numeric import MAX_AMOUNT  # noqa: E402
from app.services.errors import NumericLimitError  # noqa: E402

JUST_UNDER = MAX_AMOUNT - D("0.000001")


def test_cost_just_under_the_ceiling_is_exact():
    (h,) = fold_holdings([entry("BUY", 1, JUST_UNDER, 0)])
    assert h.invested_amount == JUST_UNDER and h.average_buy_price == JUST_UNDER


def test_cost_reaching_the_ceiling_is_refused_not_rounded():
    entries = [entry("BUY", 1, JUST_UNDER, 0), entry("BUY", 1, "0.000001", 1)]
    with pytest.raises(NumericLimitError):
        fold_ledger(entries)
    with pytest.raises(NumericLimitError):
        find_oversell(entries)


def test_cumulative_net_proceeds_are_bounded():
    entries = [entry("BUY", 12, 1, 0), entry("SELL", 6, "99999999999999", 1), entry("SELL", 6, "99999999999999", 2)]
    with pytest.raises(NumericLimitError):
        fold_ledger(entries)


def test_held_quantity_is_bounded():
    with pytest.raises(NumericLimitError):
        fold_ledger([entry("BUY", MAX_AMOUNT, "0.000001", 0)])
