import { describe, expect, it } from "vitest";

import { buildHoldingMetrics } from "./portfolioMetrics";

describe("portfolioMetrics instrument identity normalization", () => {
  it("builds the same instrumentId for equivalent NSE symbol representations", () => {
    const metrics = buildHoldingMetrics([
      {
        symbol: "TCS",
        quantity: "1",
        average_buy_price: "100",
        invested_amount: "100",
        exchange: "NSE",
        asset_type: "STOCK",
        currency: "INR",
        current_price: "120",
        market_value: "120",
        unrealized_profit_loss: "20",
        realized_profit_loss: "0",
        quote_status: "AVAILABLE",
      },
      {
        symbol: "TCS.NS",
        quantity: "1",
        average_buy_price: "100",
        invested_amount: "100",
        exchange: "NSE",
        asset_type: "STOCK",
        currency: "INR",
        current_price: "120",
        market_value: "120",
        unrealized_profit_loss: "20",
        realized_profit_loss: "0",
        quote_status: "AVAILABLE",
      },
    ]);

    expect(metrics[0].instrumentId).toBe("TCS|NSE|STOCK|INR");
    expect(metrics[1].instrumentId).toBe("TCS|NSE|STOCK|INR");
  });

  it("keeps NSE and BSE identities distinct", () => {
    const metrics = buildHoldingMetrics([
      {
        symbol: "TCS.NS",
        quantity: "1",
        average_buy_price: "100",
        invested_amount: "100",
        exchange: "NSE",
        asset_type: "STOCK",
        currency: "INR",
        current_price: "120",
        market_value: "120",
        unrealized_profit_loss: "20",
        realized_profit_loss: "0",
        quote_status: "AVAILABLE",
      },
      {
        symbol: "TCS.BO",
        quantity: "1",
        average_buy_price: "100",
        invested_amount: "100",
        exchange: "BSE",
        asset_type: "STOCK",
        currency: "INR",
        current_price: "120",
        market_value: "120",
        unrealized_profit_loss: "20",
        realized_profit_loss: "0",
        quote_status: "AVAILABLE",
      },
    ]);

    expect(metrics[0].instrumentId).toBe("TCS|NSE|STOCK|INR");
    expect(metrics[1].instrumentId).toBe("TCS|BSE|STOCK|INR");
    expect(metrics[0].instrumentId).not.toBe(metrics[1].instrumentId);
  });
});
