import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LoadingProvider } from "../../../context/LoadingContext";
import { getPortfolioSummary } from "../../../shared/api/alterfolioApi";
import type { PortfolioSummary } from "../../../shared/api/types";
import { AstraPage } from "./AstraPage";

vi.mock("../../../shared/api/alterfolioApi", () => ({
  getPortfolioSummary: vi.fn(),
}));

const mockedGetPortfolioSummary = vi.mocked(getPortfolioSummary);

function renderPage(summary: PortfolioSummary) {
  mockedGetPortfolioSummary.mockResolvedValueOnce(summary);

  render(
    <LoadingProvider>
      <AstraPage />
    </LoadingProvider>
  );
}

function buildSummary(
  status: PortfolioSummary["valuation_status"],
  overrides: Partial<PortfolioSummary> = {}
): PortfolioSummary {
  return {
    total_trades: 1,
    total_invested: "1000",
    total_market_value: status === "COMPLETE" ? "1200" : null,
    total_unrealized_profit_loss: status === "COMPLETE" ? "200" : null,
    total_realized_profit_loss: "0",
    valuation_status: status,
    valued_at: status === "COMPLETE" ? new Date().toISOString() : null,
    holdings: [
      {
        symbol: "RELIANCE",
        quantity: "10",
        average_buy_price: "100",
        invested_amount: "1000",
        exchange: "NSE",
        asset_type: "STOCK",
        currency: "INR",
        current_price: status === "COMPLETE" ? "120" : null,
        market_value: status === "COMPLETE" ? "1200" : null,
        unrealized_profit_loss: status === "COMPLETE" ? "200" : null,
        realized_profit_loss: "0",
        quote_status: status === "COMPLETE" ? "AVAILABLE" : "UNAVAILABLE",
      },
    ],
    ...overrides,
  };
}

describe("AstraPage largest position visibility", () => {
  it("shows the actual largest position for COMPLETE valuation", async () => {
    renderPage(
      buildSummary("COMPLETE", {
        holdings: [
          {
            symbol: "RELIANCE",
            quantity: "10",
            average_buy_price: "100",
            invested_amount: "1000",
            exchange: "NSE",
            asset_type: "STOCK",
            currency: "INR",
            current_price: "120",
            market_value: "1200",
            unrealized_profit_loss: "200",
            realized_profit_loss: "0",
            quote_status: "AVAILABLE",
          },
          {
            symbol: "TCS",
            quantity: "10",
            average_buy_price: "100",
            invested_amount: "1000",
            exchange: "BSE",
            asset_type: "STOCK",
            currency: "INR",
            current_price: "180",
            market_value: "1800",
            unrealized_profit_loss: "800",
            realized_profit_loss: "0",
            quote_status: "AVAILABLE",
          },
        ],
      })
    );

    expect(await screen.findByText("Largest Position")).toBeInTheDocument();
    expect(screen.getByText(/TCS · BSE/i)).toBeInTheDocument();
  });

  it("hides Largest Position for PARTIAL valuation", async () => {
    renderPage(buildSummary("PARTIAL"));

    expect(await screen.findByText("Holdings Count")).toBeInTheDocument();
    expect(screen.queryByText("Largest Position")).not.toBeInTheDocument();
  });

  it("hides Largest Position for UNAVAILABLE valuation", async () => {
    renderPage(buildSummary("UNAVAILABLE"));

    expect(await screen.findByText("Holdings Count")).toBeInTheDocument();
    expect(screen.queryByText("Largest Position")).not.toBeInTheDocument();
  });
});
