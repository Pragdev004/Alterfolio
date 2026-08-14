import { describe, expect, it, vi } from "vitest";

import { getPortfolioAnalysis, getPortfolioSummary, getTrades } from "../../../shared/api/alterfolioApi";
import { apiClient } from "../../../services/apiClient";
import { getMarketIntelligence } from "./marketIntelligenceService";

vi.mock("../../../shared/api/alterfolioApi", () => ({
  getPortfolioSummary: vi.fn(),
  getPortfolioAnalysis: vi.fn(),
  getTrades: vi.fn(),
}));

vi.mock("../../../services/apiClient", () => ({
  apiClient: {
    get: vi.fn(),
  },
}));

const mockedGetPortfolioSummary = vi.mocked(getPortfolioSummary);
const mockedGetPortfolioAnalysis = vi.mocked(getPortfolioAnalysis);
const mockedGetTrades = vi.mocked(getTrades);
const mockedApiClientGet = vi.mocked(apiClient.get);

describe("marketIntelligenceService identity behavior", () => {
  it("keeps same symbol across exchanges as distinct instruments", async () => {
    mockedApiClientGet.mockRejectedValueOnce(new Error("no backend endpoint"));

    mockedGetPortfolioSummary.mockResolvedValueOnce({
      total_trades: 2,
      total_invested: "300",
      total_market_value: "362",
      total_unrealized_profit_loss: "62",
      total_realized_profit_loss: "0",
      valuation_status: "COMPLETE",
      valued_at: new Date().toISOString(),
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
    });

    mockedGetPortfolioAnalysis.mockResolvedValueOnce({
      analysis: {
        overview: "Portfolio is stable.",
        diversification_analysis: "Concentration exists.",
        risk_assessment: "Risk is moderate.",
        strengths: [],
        weaknesses: [],
        recommendations: ["Review sector concentration."],
      },
      model: "test",
      generated_at: new Date().toISOString(),
    });

    mockedGetTrades.mockResolvedValueOnce([
      {
        id: "1",
        user_id: "u1",
        asset_symbol: "RELIANCE",
        asset_name: "Reliance NSE",
        asset_type: "STOCK",
        exchange: "NSE",
        currency: "INR",
        transaction_type: "BUY",
        quantity: "1",
        price_per_unit: "100",
        trade_timestamp: new Date(Date.now() - 3600_000).toISOString(),
        trade_source: "MANUAL",
        market_session: "REGULAR",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      {
        id: "2",
        user_id: "u1",
        asset_symbol: "RELIANCE",
        asset_name: "Reliance NSE",
        asset_type: "STOCK",
        exchange: "NSE",
        currency: "INR",
        transaction_type: "BUY",
        quantity: "1",
        price_per_unit: "120",
        trade_timestamp: new Date().toISOString(),
        trade_source: "MANUAL",
        market_session: "REGULAR",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      {
        id: "3",
        user_id: "u1",
        asset_symbol: "RELIANCE",
        asset_name: "Reliance BSE",
        asset_type: "STOCK",
        exchange: "BSE",
        currency: "INR",
        transaction_type: "BUY",
        quantity: "1",
        price_per_unit: "100",
        trade_timestamp: new Date(Date.now() - 3600_000).toISOString(),
        trade_source: "MANUAL",
        market_session: "REGULAR",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      {
        id: "4",
        user_id: "u1",
        asset_symbol: "RELIANCE",
        asset_name: "Reliance BSE",
        asset_type: "STOCK",
        exchange: "BSE",
        currency: "INR",
        transaction_type: "BUY",
        quantity: "1",
        price_per_unit: "110",
        trade_timestamp: new Date().toISOString(),
        trade_source: "MANUAL",
        market_session: "REGULAR",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ]);

    const data = await getMarketIntelligence();

    expect(data.movers.gainers).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ instrumentId: "RELIANCE|NSE|STOCK|INR", symbol: "RELIANCE · NSE" }),
        expect.objectContaining({ instrumentId: "RELIANCE|BSE|STOCK|INR", symbol: "RELIANCE · BSE" }),
      ])
    );

    expect(data.impact).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ instrumentId: "RELIANCE|NSE|STOCK|INR", symbol: "RELIANCE · NSE" }),
        expect.objectContaining({ instrumentId: "RELIANCE|BSE|STOCK|INR", symbol: "RELIANCE · BSE" }),
      ])
    );

    expect(data.earnings).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ instrumentId: "RELIANCE|NSE|STOCK|INR", symbol: "RELIANCE · NSE" }),
        expect.objectContaining({ instrumentId: "RELIANCE|BSE|STOCK|INR", symbol: "RELIANCE · BSE" }),
      ])
    );

    expect(data.news).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          relatedInstrumentIds: expect.arrayContaining([
            "RELIANCE|NSE|STOCK|INR",
            "RELIANCE|BSE|STOCK|INR",
          ]),
        }),
      ])
    );
  });

  it("normalizes known provider suffixes when constructing composite identity", async () => {
    mockedApiClientGet.mockRejectedValueOnce(new Error("no backend endpoint"));

    mockedGetPortfolioSummary.mockResolvedValueOnce({
      total_trades: 3,
      total_invested: "300",
      total_market_value: "360",
      total_unrealized_profit_loss: "60",
      total_realized_profit_loss: "0",
      valuation_status: "COMPLETE",
      valued_at: new Date().toISOString(),
      holdings: [
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
          symbol: "TCS.BO",
          quantity: "2",
          average_buy_price: "100",
          invested_amount: "200",
          exchange: "BSE",
          asset_type: "STOCK",
          currency: "INR",
          current_price: "120",
          market_value: "240",
          unrealized_profit_loss: "40",
          realized_profit_loss: "0",
          quote_status: "AVAILABLE",
        },
      ],
    });

    mockedGetPortfolioAnalysis.mockResolvedValueOnce({
      analysis: {
        overview: "Portfolio is stable.",
        diversification_analysis: "Concentration exists.",
        risk_assessment: "Risk is moderate.",
        strengths: [],
        weaknesses: [],
        recommendations: ["Review sector concentration."],
      },
      model: "test",
      generated_at: new Date().toISOString(),
    });

    mockedGetTrades.mockResolvedValueOnce([
      {
        id: "1",
        user_id: "u1",
        asset_symbol: "tcs.ns",
        asset_name: "TCS NSE",
        asset_type: "STOCK",
        exchange: "NSE",
        currency: "INR",
        transaction_type: "BUY",
        quantity: "1",
        price_per_unit: "100",
        trade_timestamp: new Date(Date.now() - 3600_000).toISOString(),
        trade_source: "MANUAL",
        market_session: "REGULAR",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      {
        id: "2",
        user_id: "u1",
        asset_symbol: "TCS",
        asset_name: "TCS NSE",
        asset_type: "STOCK",
        exchange: "NSE",
        currency: "INR",
        transaction_type: "BUY",
        quantity: "1",
        price_per_unit: "110",
        trade_timestamp: new Date().toISOString(),
        trade_source: "MANUAL",
        market_session: "REGULAR",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      {
        id: "3",
        user_id: "u1",
        asset_symbol: "tcs.bo",
        asset_name: "TCS BSE",
        asset_type: "STOCK",
        exchange: "BSE",
        currency: "INR",
        transaction_type: "BUY",
        quantity: "1",
        price_per_unit: "90",
        trade_timestamp: new Date(Date.now() - 3600_000).toISOString(),
        trade_source: "MANUAL",
        market_session: "REGULAR",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      {
        id: "4",
        user_id: "u1",
        asset_symbol: "TCS.BO",
        asset_name: "TCS BSE",
        asset_type: "STOCK",
        exchange: "BSE",
        currency: "INR",
        transaction_type: "BUY",
        quantity: "1",
        price_per_unit: "95",
        trade_timestamp: new Date().toISOString(),
        trade_source: "MANUAL",
        market_session: "REGULAR",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ]);

    const data = await getMarketIntelligence();

    expect(data.movers.gainers).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ instrumentId: "TCS|NSE|STOCK|INR", symbol: "tcs.ns · NSE" }),
        expect.objectContaining({ instrumentId: "TCS|BSE|STOCK|INR", symbol: "tcs.bo · BSE" }),
      ])
    );

    expect(data.movers.gainers).not.toEqual(
      expect.arrayContaining([
        expect.objectContaining({ instrumentId: "TCS.NS|NSE|STOCK|INR" }),
        expect.objectContaining({ instrumentId: "TCS.BO|BSE|STOCK|INR" }),
      ])
    );
  });
});
