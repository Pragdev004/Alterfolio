# Corporate actions review (2026-10-16)

Source: the owner-reviewed list supplied on 2026-10-16. Transcribed into `backend/config/corporate_actions_reviewed.toml`.
Reviewed window for every instrument: 2023-10-01 to 2026-10-15 (NSE listings).

**Caveat: July to mid-September 2026 was not fully verified against NSE.** Actions in that stretch may be missing.

## Declared actions (listing excluded as a known action inside the window)
| Instrument | Action | Record date |
|---|---|---|
| RELIANCE | bonus 1:1 | 2024-10-28 |
| WIPRO | bonus 1:1 | 2024-12-03 |
| ITC | demerger (ITC Hotels) | 2025-01-06 |
| HDFCBANK | bonus 1:1 | 2025-08-27 |
| HINDUNILVR | demerger (Kwality Wall's) 1:1 | 2025-12-05 |
| CANBK | stock split 1:5 | 2024-05-15 |

## Reviewed, no actions
ONGC, INFY, IDEA, TRIDENT, CENTRALBK, IOB, ZOMATO, TCS, ICICIBANK, SBIN, BHARTIARTL, LT, AXISBANK, ASIANPAINT,
MARUTI, SUNPHARMA, TITAN, ULTRACEMCO.

2023-10-01..2024-07-28 reviewed from owner knowledge; CANBK split verified by owner; others: no split/bonus/demerger in that window.

## Not reviewed (stay Unavailable until checked)
PNB, BANKBARODA, UNIONBANK, BANKINDIA, MAHABANK: added to `analysis_universe.toml` with UNVERIFIED ISINs, deliberately
absent from the register. Any other listing not named above is also unreviewed.

## Effect
A window counts only if it covers the whole analysis range (first trade minus 300 days .. as-of day). An as-of day after
2026-10-15, or a first trade earlier than 2024-07-29, leaves that instrument unreviewed.
A listing with a declared action inside the range is excluded from 006 disposition and from 007/008 as `CORPORATE_ACTION`.
