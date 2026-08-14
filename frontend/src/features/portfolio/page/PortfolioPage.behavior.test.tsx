import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { LoadingProvider } from "../../../context/LoadingContext";
import { getPortfolioSummary } from "../../../shared/api/alterfolioApi";
import type { PortfolioSummary } from "../../../shared/api/types";
import { PortfolioPage } from "./PortfolioPage";

vi.mock("../../../shared/api/alterfolioApi", () => ({
  getPortfolioSummary: vi.fn(),
}));

vi.mock("recharts", () => {
  const Mock = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  return {
    ResponsiveContainer: Mock,
    PieChart: Mock,
    Pie: Mock,
    Cell: Mock,
    Tooltip: Mock,
    BarChart: Mock,
    Bar: Mock,
    CartesianGrid: Mock,
    XAxis: Mock,
    YAxis: Mock,
  };
});

const mockedGetPortfolioSummary = vi.mocked(getPortfolioSummary);

function renderPage(summary: PortfolioSummary) {
  mockedGetPortfolioSummary.mockResolvedValueOnce(summary);

  render(
    <LoadingProvider>
      <PortfolioPage />
    </LoadingProvider>
  );
}

function buildSummary(overrides: Partial<PortfolioSummary>): PortfolioSummary {
  return {
    total_trades: 2,
    total_invested: "2000",
    total_market_value: "2200",
    total_unrealized_profit_loss: "200",
    total_realized_profit_loss: "0",
    valuation_status: "COMPLETE",
    valued_at: new Date().toISOString(),
    holdings: [],
    ...overrides,
  };
}

describe("PortfolioPage valuation-state behavior", () => {
  it("shows allocation and winners/losers for COMPLETE valuation", async () => {
    renderPage(
      buildSummary({
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
            symbol: "INFY",
            quantity: "5",
            average_buy_price: "200",
            invested_amount: "1000",
            exchange: "NSE",
            asset_type: "STOCK",
            currency: "INR",
            current_price: "200",
            market_value: "1000",
            unrealized_profit_loss: "0",
            realized_profit_loss: "0",
            quote_status: "AVAILABLE",
          },
        ],
      })
    );

    expect(await screen.findByText(/Valuation status: COMPLETE/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Portfolio allocation by holding")).toBeInTheDocument();
    expect(screen.getAllByText("RELIANCE · NSE").length).toBeGreaterThan(0);
    expect(screen.getAllByText("INFY · NSE").length).toBeGreaterThan(0);
    expect(screen.queryByText(/Allocation is hidden because valuation is partial/i)).not.toBeInTheDocument();
  });

  it("suppresses complete-only analytics and shows coverage for PARTIAL valuation", async () => {
    renderPage(
      buildSummary({
        valuation_status: "PARTIAL",
        total_market_value: null,
        total_unrealized_profit_loss: null,
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
            symbol: "INFY",
            quantity: "5",
            average_buy_price: "200",
            invested_amount: "1000",
            exchange: "NSE",
            asset_type: "STOCK",
            currency: "INR",
            current_price: null,
            market_value: null,
            unrealized_profit_loss: null,
            realized_profit_loss: "0",
            quote_status: "UNAVAILABLE",
          },
        ],
      })
    );

    expect(await screen.findByText(/Valuation status: PARTIAL \(1\/2 holdings valued\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Allocation is hidden because valuation is partial/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Portfolio allocation by holding")).not.toBeInTheDocument();
    expect(screen.queryByText("100%", { exact: false })).not.toBeInTheDocument();
  });

  it("shows unavailable state and does not fabricate zero valuation", async () => {
    renderPage(
      buildSummary({
        valuation_status: "UNAVAILABLE",
        total_market_value: null,
        total_unrealized_profit_loss: null,
        holdings: [
          {
            symbol: "RELIANCE",
            quantity: "10",
            average_buy_price: "100",
            invested_amount: "1000",
            exchange: "NSE",
            asset_type: "STOCK",
            currency: "INR",
            current_price: null,
            market_value: null,
            unrealized_profit_loss: null,
            realized_profit_loss: "0",
            quote_status: "UNAVAILABLE",
          },
        ],
      })
    );

    expect(await screen.findByText(/Valuation status: UNAVAILABLE/i)).toBeInTheDocument();
    expect(screen.getByText("Current Value").closest("article")).toHaveTextContent("Unavailable");
    expect(screen.getByText(/Allocation is unavailable because live valuation data is unavailable/i)).toBeInTheDocument();
  });

  it("keeps NSE/BSE same-symbol holdings distinct", async () => {
    renderPage(
      buildSummary({
        holdings: [
          {
            symbol: "RELIANCE",
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
            symbol: "RELIANCE",
            quantity: "2",
            average_buy_price: "100",
            invested_amount: "200",
            exchange: "BSE",
            asset_type: "STOCK",
            currency: "INR",
            current_price: "121",
            market_value: "242",
            unrealized_profit_loss: "42",
            realized_profit_loss: "0",
            quote_status: "AVAILABLE",
          },
        ],
      })
    );

    await waitFor(() => {
      expect(screen.getAllByText("RELIANCE · NSE").length).toBeGreaterThan(0);
      expect(screen.getAllByText("RELIANCE · BSE").length).toBeGreaterThan(0);
    });
  });
});
