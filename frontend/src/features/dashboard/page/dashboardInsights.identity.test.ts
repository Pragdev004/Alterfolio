import { describe, expect, it } from "vitest";

import { buildAllocationSeries } from "./dashboardInsights";

describe("dashboardInsights instrument identity normalization", () => {
  it("uses stable composite identity for equivalent NSE symbols", () => {
    const series = buildAllocationSeries([
      {
        symbol: "TCS",
        exchange: "NSE",
        asset_type: "STOCK",
        currency: "INR",
        market_value: "100",
      },
      {
        symbol: "TCS.NS",
        exchange: "NSE",
        asset_type: "STOCK",
        currency: "INR",
        market_value: "120",
      },
    ]);

    expect(series).toHaveLength(2);
    expect(series[0].id).toBe("TCS|NSE|STOCK|INR");
    expect(series[1].id).toBe("TCS|NSE|STOCK|INR");
  });

  it("keeps NSE and BSE composite identities distinct", () => {
    const series = buildAllocationSeries([
      {
        symbol: "TCS.NS",
        exchange: "NSE",
        asset_type: "STOCK",
        currency: "INR",
        market_value: "100",
      },
      {
        symbol: "TCS.BO",
        exchange: "BSE",
        asset_type: "STOCK",
        currency: "INR",
        market_value: "120",
      },
    ]);

    expect(series).toHaveLength(2);
    expect(series.map((point) => point.id)).toEqual(
      expect.arrayContaining(["TCS|NSE|STOCK|INR", "TCS|BSE|STOCK|INR"])
    );
  });
});
