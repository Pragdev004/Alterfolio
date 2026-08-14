import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { LoadingProvider } from "../../../context/LoadingContext";
import {
  getPortfolioAnalysis,
  getPortfolioSummary,
  getTrades,
} from "../../../shared/api/alterfolioApi";
import type {
  PortfolioAnalysisResponse,
  PortfolioSummary,
  TradeResponse,
} from "../../../shared/api/types";
import { DashboardPage } from "./DashboardPage";

vi.mock("../../../shared/api/alterfolioApi", () => ({
  getPortfolioSummary: vi.fn(),
  getTrades: vi.fn(),
  getPortfolioAnalysis: vi.fn(),
}));

vi.mock("recharts", () => {
  const Mock = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  return {
    ResponsiveContainer: Mock,
    PieChart: Mock,
    Pie: Mock,
    Cell: Mock,
    Tooltip: Mock,
    LineChart: Mock,
    Line: Mock,
    XAxis: Mock,
    YAxis: Mock,
  };
});

const mockedGetPortfolioSummary = vi.mocked(getPortfolioSummary);
const mockedGetTrades = vi.mocked(getTrades);
const mockedGetPortfolioAnalysis = vi.mocked(getPortfolioAnalysis);

function buildSummary(overrides: Partial<PortfolioSummary>): PortfolioSummary {
  return {
    total_trades: 2,
    total_invested: "2000",
    total_market_value: "2200",
    total_unrealized_profit_loss: "200",
    total_realized_profit_loss: "0",
    valuation_status: "COMPLETE",
    valued_at: new Date().toISOString(),
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
    ],
    ...overrides,
  };
}

function buildAnalysis(): PortfolioAnalysisResponse {
  return {
    analysis: {
      overview: "Portfolio steady.",
      diversification_analysis: "Moderate diversification.",
      risk_assessment: "Moderate risk.",
      strengths: [],
      weaknesses: [],
      recommendations: ["Review allocations."],
    },
    model: "test",
    generated_at: new Date().toISOString(),
  };
}

function buildTrades(): TradeResponse[] {
  return [
    {
      id: "1",
      user_id: "u1",
      asset_symbol: "RELIANCE",
      asset_name: "Reliance",
      asset_type: "STOCK",
      exchange: "NSE",
      currency: "INR",
      transaction_type: "BUY",
      quantity: "1",
      price_per_unit: "100",
      trade_timestamp: new Date().toISOString(),
      trade_source: "MANUAL",
      market_session: "REGULAR",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
  ];
}

function renderPage(summary: PortfolioSummary) {
  mockedGetPortfolioSummary.mockResolvedValueOnce(summary);
  mockedGetPortfolioAnalysis.mockResolvedValueOnce(buildAnalysis());
  mockedGetTrades.mockResolvedValueOnce(buildTrades());

  render(
    <LoadingProvider>
      <DashboardPage />
    </LoadingProvider>
  );
}

describe("DashboardPage valuation-state behavior", () => {
  it("shows complete analytics for COMPLETE valuation", async () => {
    renderPage(buildSummary({ valuation_status: "COMPLETE" }));

    expect(await screen.findByLabelText("Asset allocation donut chart")).toBeInTheDocument();
    expect(screen.queryByText(/Allocation is hidden because valuation is partial/i)).not.toBeInTheDocument();
  });

  it("suppresses complete-only allocation analytics for PARTIAL valuation", async () => {
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

    expect(await screen.findByText(/Allocation is hidden because valuation is partial/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Asset allocation donut chart")).not.toBeInTheDocument();
    expect(screen.getByText("Current Value").closest("article")).toHaveTextContent("Unavailable");
  });

  it("shows unavailable state for UNAVAILABLE valuation without fabricated totals", async () => {
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

    expect(await screen.findByText(/Allocation unavailable because live valuation data is unavailable/i)).toBeInTheDocument();
    expect(screen.getByText("Current Value").closest("article")).toHaveTextContent("Unavailable");
    expect(screen.queryByLabelText("Asset allocation donut chart")).not.toBeInTheDocument();
  });
});
