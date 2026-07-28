# Alterfolio API Contract

_Last updated: 2026-07-27_

This document is the human-readable API contract for currently implemented endpoints.

## Base assumptions

- API framework: FastAPI
- Content type: `application/json`
- Base URL (local): `http://localhost:8000`
- Current routers:
  - Health: `/health`
  - Trades: `/trades`
  - Portfolio: `/portfolio`

## Endpoints

### 1) Health check

- **Method**: `GET`
- **Path**: `/health`
- **Purpose**: Basic liveness check.

**200 OK response**

```json
{
  "status": "ok"
}
```

---

### 2) Create trade

- **Method**: `POST`
- **Path**: `/trades/`
- **Response model**: `TradeResponse`
- **Success status**: `201 Created`

**Request body (`TradeCreate`)**

| Field | Type | Required | Notes |
|---|---|---|---|
| `user_id` | UUID | Yes | Trade owner ID |
| `asset_symbol` | string | Yes | e.g. `TCS` |
| `asset_name` | string | Yes | e.g. `Tata Consultancy Services` |
| `asset_type` | enum | Yes | `STOCK`, `ETF`, `MUTUAL_FUND`, `BOND`, `GOLD`, `REIT`, `INVIT`, `INDEX`, `FUTURES`, `OPTIONS`, `CASH` |
| `exchange` | enum | Yes | `NSE`, `BSE`, `NFO`, `MCX` |
| `currency` | enum | Yes (default) | currently `INR` |
| `transaction_type` | enum | Yes | `BUY`, `SELL` |
| `quantity` | decimal | Yes | |
| `price_per_unit` | decimal | Yes | |
| `trade_timestamp` | datetime | Yes | ISO-8601 |
| `brokerage_fee` | decimal | No | default `0` |
| `taxes` | decimal | No | default `0` |
| `broker` | string/null | No | |
| `order_id` | string/null | No | |
| `trade_source` | enum | Yes | `MANUAL`, `IMPORT`, `BROKER_SYNC`, `AI` |
| `market_session` | enum | Yes | `PRE_MARKET`, `REGULAR`, `POST_MARKET` |
| `status` | enum | No | default `EXECUTED`; also `PENDING`, `CANCELLED`, `REJECTED` |
| `investment_horizon` | enum/null | No | `INTRADAY`, `SWING`, `SHORT_TERM`, `LONG_TERM` |
| `notes` | string/null | No | |

**201 Created response (`TradeResponse`)**

- Includes all `TradeCreate` fields plus:
  - `id` (UUID)
  - `created_at` (datetime)
  - `updated_at` (datetime)

**Errors**
- `422 Unprocessable Entity` for schema validation failures.

---

### 3) List trades

- **Method**: `GET`
- **Path**: `/trades/`
- **Response model**: `list[TradeResponse]`
- **Success status**: `200 OK`

**200 OK response**
- JSON array of `TradeResponse` objects.

---

### 4) Get trade by ID

- **Method**: `GET`
- **Path**: `/trades/{trade_id}`
- **Path params**:
  - `trade_id` (UUID)
- **Response model**: `TradeResponse`
- **Success status**: `200 OK`

**Errors**
- `404 Not Found` with:

```json
{
  "detail": "Trade not found"
}
```

- `422 Unprocessable Entity` if `trade_id` is not a valid UUID.

---

### 5) Portfolio summary

- **Method**: `GET`
- **Path**: `/portfolio/summary`
- **Response model**: `PortfolioSummary`
- **Success status**: `200 OK`

**Response model (`PortfolioSummary`)**

| Field | Type | Notes |
|---|---|---|
| `total_trades` | integer | Total trades in portfolio |
| `total_invested` | decimal | Sum invested |
| `holdings` | list[`HoldingSummary`] | Per-symbol rolled-up view |

`HoldingSummary` fields:
- `symbol` (string)
- `quantity` (decimal)
- `average_buy_price` (decimal)
- `invested_amount` (decimal)

---

### 6) Portfolio AI analysis

- **Method**: `GET`
- **Path**: `/portfolio/analysis`
- **Current return shape**: `PortfolioAnalysisResponse`
- **Success status**: `200 OK`

**Response model (`PortfolioAnalysisResponse`)**

| Field | Type | Notes |
|---|---|---|
| `analysis` | `PortfolioAnalysis` | Main generated analysis object |
| `model` | string | AI deployment/model identifier |
| `generated_at` | datetime | UTC timestamp |

`PortfolioAnalysis` fields:
- `overview` (string)
- `diversification_analysis` (string)
- `risk_assessment` (string)
- `strengths` (list[string])
- `weaknesses` (list[string])
- `recommendations` (list[string])

## Notes for clients

- UUID fields must be valid UUID strings.
- Datetime values should be sent/parsed as ISO-8601.
- Enum values are case-sensitive and must match documented values exactly.
