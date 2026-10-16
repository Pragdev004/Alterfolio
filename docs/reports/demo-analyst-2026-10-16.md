# Demo: analyst on real facts (2026-10-16)

Offline run. As-of D = 2026-09-30; injected clock 2026-12-01 10:00Z; provider none (TemplateLLM); fixtures: tradebook built in memory by `build_demo_fixture.py` in the `tradebook_synthetic.csv` format (30 rows imported, 2 of them after D and must be ignored) and recorded `analyst_demo_bars.json` (bars run to 2026-11-30; none after D may be used). All data is synthetic.

Seeds: {'luck_test': 5685454388150673179, 'regime_split': 17828822023823354133}. Luck universe: 12 synthetic NSE listings; corporate-action coverage declared for the fixture only.
Trades used: 28. Late-recorded rows: 28 (imported after D by nature; disclosed, not filtered).

## Q1. Was my last buy skill or luck?

verified: **True** (attempts 1)

Answer:
```
luck.trip_count: 14
luck.ALT.trips_used: 14
luck.ALT.trips_evaluated: 14
luck.ALT.mean_excess: -0.0037071855776146514
luck.ALT.mean_percentile: 0.145
luck.ALT.ci_lower: -0.013849513662801785
luck.ALT.ci_upper: 0.010175544110721609
luck.NIFTY.trips_used: 14
luck.NIFTY.trips_evaluated: 14
luck.NIFTY.mean_excess: -0.002422540453021594
luck.NIFTY.mean_percentile: 0.1942857142857143
luck.NIFTY.ci_lower: -0.012272394055297965
luck.NIFTY.ci_upper: 0.012207351122736174
luck.last_trip.actual_return: -0.012678288431061806656101426307448494453248811410459587955626 RATIO_FEES_EXCLUDED
luck.last_trip.ALT.percentile: 0.01
luck.last_trip.ALT.excess: -0.016840864224027214
luck.last_trip.NIFTY.percentile: 0.13
luck.last_trip.NIFTY.excess: -0.011968144879768166
See document 11111111-1111-1111-1111-111111111111.
```

Citations: tool:007:trip_count, tool:007:ALT.trips_used, tool:007:ALT.trips_evaluated, tool:007:ALT.mean_excess, tool:007:ALT.mean_percentile, tool:007:ALT.ci_lower, tool:007:ALT.ci_upper, tool:007:NIFTY.trips_used, tool:007:NIFTY.trips_evaluated, tool:007:NIFTY.mean_excess, tool:007:NIFTY.mean_percentile, tool:007:NIFTY.ci_lower, tool:007:NIFTY.ci_upper, tool:007:last_trip.actual_return, tool:007:last_trip.ALT.percentile, tool:007:last_trip.ALT.excess, tool:007:last_trip.NIFTY.percentile, tool:007:last_trip.NIFTY.excess, chunk:11111111-1111-1111-1111-111111111111

Retriever returned: h1-outlook-note (2026-08-14), nov-results-announcement (2026-11-12). Dated after D and dropped by the analyst: 1; cited: 1.

Facts used (18): luck.trip_count=14, luck.ALT.trips_used=14, luck.ALT.trips_evaluated=14, luck.ALT.mean_excess=-0.0037071855776146514, luck.ALT.mean_percentile=0.145, luck.ALT.ci_lower=-0.013849513662801785, luck.ALT.ci_upper=0.010175544110721609, luck.NIFTY.trips_used=14, luck.NIFTY.trips_evaluated=14, luck.NIFTY.mean_excess=-0.002422540453021594, luck.NIFTY.mean_percentile=0.1942857142857143, luck.NIFTY.ci_lower=-0.012272394055297965, luck.NIFTY.ci_upper=0.012207351122736174, luck.last_trip.actual_return=-0.012678288431061806656101426307448494453248811410459587955626, luck.last_trip.ALT.percentile=0.01, luck.last_trip.ALT.excess=-0.016840864224027214, luck.last_trip.NIFTY.percentile=0.13, luck.last_trip.NIFTY.excess=-0.011968144879768166

## Q2. What did my behaviour cost me?

verified: **True** (attempts 1)

Answer:
```
bias.DISPOSITION.cost_inr: 0 INR
bias.CHASING.cost_inr: 19.5947877483809985170819996720413198062922265276828123242572 INR
bias.OVERTRADING.cost_inr: 105.8 INR_LOWER_BOUND
bias.OVERTRADING.unknown_fee_trade_count: 28
See document 11111111-1111-1111-1111-111111111111.
```

Citations: tool:006:DISPOSITION.cost_inr, tool:006:CHASING.cost_inr, tool:006:OVERTRADING.cost_inr, tool:006:OVERTRADING.unknown_fee_trade_count, chunk:11111111-1111-1111-1111-111111111111

Retriever returned: h1-outlook-note (2026-08-14), nov-results-announcement (2026-11-12). Dated after D and dropped by the analyst: 1; cited: 1.

Facts used (4): bias.DISPOSITION.cost_inr=0, bias.CHASING.cost_inr=19.5947877483809985170819996720413198062922265276828123242572, bias.OVERTRADING.cost_inr=105.8, bias.OVERTRADING.unknown_fee_trade_count=28

## Q3. How did I do in each regime?

verified: **True** (attempts 1)

Answer:
```
regime.round_trip_count: 14
regime.unclassified_count: 0
regime.LOW.trip_count: 5
regime.LOW.luck.ALT.mean_excess: 0.008129731758308214
regime.LOW.bias.DISPOSITION.cost_inr: 0 INR
regime.LOW.bias.CHASING.cost_inr: 0 INR
regime.LOW.bias.OVERTRADING.cost_inr: 29.6 INR_LOWER_BOUND
regime.NORMAL.trip_count: 6
regime.NORMAL.luck.ALT.mean_excess: -0.006910176938286443
regime.NORMAL.bias.DISPOSITION.cost_inr: 0 INR
regime.NORMAL.bias.CHASING.cost_inr: 0 INR
regime.NORMAL.bias.OVERTRADING.cost_inr: 46 INR_LOWER_BOUND
regime.HIGH.trip_count: 3
regime.HIGH.luck.ALT.mean_excess: -0.016329223406398707
regime.HIGH.bias.DISPOSITION.cost_inr: Unavailable
regime.HIGH.bias.CHASING.cost_inr: 0.173092750963002995107693231511032236966493906323158406385299 INR
regime.HIGH.bias.OVERTRADING.cost_inr: 30.2 INR_LOWER_BOUND
See document 11111111-1111-1111-1111-111111111111.
```

Citations: tool:008:round_trip_count, tool:008:unclassified_count, tool:008:LOW.trip_count, tool:008:LOW.luck.ALT.mean_excess, tool:008:LOW.bias.DISPOSITION.cost_inr, tool:008:LOW.bias.CHASING.cost_inr, tool:008:LOW.bias.OVERTRADING.cost_inr, tool:008:NORMAL.trip_count, tool:008:NORMAL.luck.ALT.mean_excess, tool:008:NORMAL.bias.DISPOSITION.cost_inr, tool:008:NORMAL.bias.CHASING.cost_inr, tool:008:NORMAL.bias.OVERTRADING.cost_inr, tool:008:HIGH.trip_count, tool:008:HIGH.luck.ALT.mean_excess, tool:008:HIGH.bias.DISPOSITION.cost_inr, tool:008:HIGH.bias.CHASING.cost_inr, tool:008:HIGH.bias.OVERTRADING.cost_inr, chunk:11111111-1111-1111-1111-111111111111

Retriever returned: h1-outlook-note (2026-08-14), nov-results-announcement (2026-11-12). Dated after D and dropped by the analyst: 1; cited: 1.

Facts used (17): regime.round_trip_count=14, regime.unclassified_count=0, regime.LOW.trip_count=5, regime.LOW.luck.ALT.mean_excess=0.008129731758308214, regime.LOW.bias.DISPOSITION.cost_inr=0, regime.LOW.bias.CHASING.cost_inr=0, regime.LOW.bias.OVERTRADING.cost_inr=29.6, regime.NORMAL.trip_count=6, regime.NORMAL.luck.ALT.mean_excess=-0.006910176938286443, regime.NORMAL.bias.DISPOSITION.cost_inr=0, regime.NORMAL.bias.CHASING.cost_inr=0, regime.NORMAL.bias.OVERTRADING.cost_inr=46, regime.HIGH.trip_count=3, regime.HIGH.luck.ALT.mean_excess=-0.016329223406398707, regime.HIGH.bias.DISPOSITION.cost_inr=Unavailable, regime.HIGH.bias.CHASING.cost_inr=0.173092750963002995107693231511032236966493906323158406385299, regime.HIGH.bias.OVERTRADING.cost_inr=30.2

## Q4. What did the November 2026 results announcement say?

verified: **True** (attempts 1)

Answer:
```
See document 11111111-1111-1111-1111-111111111111.
```

Citations: chunk:11111111-1111-1111-1111-111111111111

Retriever returned: h1-outlook-note (2026-08-14), nov-results-announcement (2026-11-12). Dated after D and dropped by the analyst: 1; cited: 1.

Facts used (0): none (documents only)

