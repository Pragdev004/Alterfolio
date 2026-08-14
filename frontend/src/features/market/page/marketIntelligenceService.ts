import { getPortfolioAnalysis, getPortfolioSummary, getTrades } from "../../../shared/api/alterfolioApi";
import { apiClient } from "../../../services/apiClient";
import { parseDecimal } from "../../../shared/lib/format";
import {
  type HoldingSummary,
  type PortfolioAnalysisResponse,
  type PortfolioSummary,
  type TradeResponse,
} from "../../../shared/api/types";
import {
  buildCompositeInstrumentId,
  buildDisplaySymbol,
  buildProviderTicker,
} from "../../../shared/lib/instrumentIdentity";
import {
  type EarningsEvent,
  type MarketIntelligenceData,
  type MarketMover,
  type MarketNewsItem,
  type PortfolioImpactItem,
} from "./marketTypes";

type InstrumentIdentity = {
  instrumentId: string;
  displaySymbol: string;
  providerTicker: string;
};


export async function getMarketIntelligence(): Promise<MarketIntelligenceData> {
  const backendPayload = await tryGetBackendPayload();

  if (backendPayload) {
    return backendPayload;
  }

  const [summary, analysis, trades] = await Promise.all([
    getPortfolioSummary(),
    getPortfolioAnalysis(),
    getTrades(),
  ]);

  return buildDerivedMarketIntelligence(summary, analysis, trades);
}

async function tryGetBackendPayload(): Promise<MarketIntelligenceData | null> {
  try {
    const response = await apiClient.get<MarketIntelligenceData>("/market/intelligence");
    return response.data;
  } catch {
    return null;
  }
}

function buildDerivedMarketIntelligence(
  summary: PortfolioSummary,
  analysis: PortfolioAnalysisResponse,
  trades: TradeResponse[]
): MarketIntelligenceData {
  const topHoldings = summary.holdings
    .map((holding) => ({
      identity: buildHoldingIdentity(holding),
      invested: parseDecimal(holding.invested_amount),
    }))
    .sort((left, right) => right.invested - left.invested)
    .slice(0, 4)
    .map((holding) => holding.identity);

  const newsWithIdentity = buildDerivedNews(topHoldings, analysis);
  const impact = buildPortfolioImpact(newsWithIdentity, summary);
  const movers = buildMarketMovers(trades);
  const earnings = buildEarningsCalendar(summary);

  return {
    news: newsWithIdentity,
    impact,
    aiSummary: buildAiSummary(analysis),
    movers,
    earnings,
    dataSource: "derived",
  };
}

function buildDerivedNews(
  topHoldings: InstrumentIdentity[],
  analysis: PortfolioAnalysisResponse
): MarketNewsItem[] {
  const now = Date.now();
  const topTickers = topHoldings.map((holding) => holding.providerTicker);

  const derivedStories = [
    {
      headline: `Risk watch across ${topTickers.slice(0, 2).join(" and ") || "your top holdings"}`,
      summary: firstSentence(analysis.analysis.risk_assessment),
      sentiment: inferSentiment(analysis.analysis.risk_assessment),
      related: topHoldings.slice(0, 3),
    },
    {
      headline: "Diversification update from today’s portfolio signals",
      summary: firstSentence(analysis.analysis.diversification_analysis),
      sentiment: inferSentiment(analysis.analysis.diversification_analysis),
      related: topHoldings.slice(1, 4),
    },
    {
      headline: "Actionable recommendation focus for this session",
      summary: analysis.analysis.recommendations[0] ?? "No recommendation available.",
      sentiment: "neutral" as const,
      related: topHoldings.slice(0, 2),
    },
  ];

  return derivedStories.map((story, index) => ({
    id: `derived-news-${index}`,
    headline: story.headline,
    summary: story.summary,
    source: "Derived intelligence (portfolio + AI analysis)",
    publishedAt: new Date(now - index * 60 * 60 * 1000).toISOString(),
    relatedSymbols: story.related.map((item) => item.providerTicker),
    relatedInstrumentIds: story.related.map((item) => item.instrumentId),
    sentiment: story.sentiment,
  }));
}

function buildPortfolioImpact(
  news: MarketNewsItem[],
  summary: PortfolioSummary
): PortfolioImpactItem[] {
  const impactMap = new Map<string, PortfolioImpactItem>();

  for (const holding of summary.holdings) {
    const identity = buildHoldingIdentity(holding);
    impactMap.set(identity.instrumentId, {
      instrumentId: identity.instrumentId,
      symbol: identity.displaySymbol,
      mentionCount: 0,
      latestHeadline: "No direct mention in current feed.",
    });
  }

  for (const item of news) {
    for (const instrumentId of item.relatedInstrumentIds) {
      const existing = impactMap.get(instrumentId);
      if (!existing) {
        continue;
      }

      impactMap.set(instrumentId, {
        instrumentId: existing.instrumentId,
        symbol: existing.symbol,
        mentionCount: existing.mentionCount + 1,
        latestHeadline: item.headline,
      });
    }
  }

  return Array.from(impactMap.values())
    .sort((left, right) => right.mentionCount - left.mentionCount)
    .slice(0, 8);
}

function buildMarketMovers(trades: TradeResponse[]): {
  gainers: MarketMover[];
  losers: MarketMover[];
} {
  const tradesByInstrument = new Map<
    string,
    { instrumentId: string; displaySymbol: string; trades: TradeResponse[] }
  >();

  for (const trade of trades) {
    const identity = buildTradeIdentity(trade);
    const existing = tradesByInstrument.get(identity.instrumentId);

    if (existing) {
      existing.trades.push(trade);
      continue;
    }

    tradesByInstrument.set(identity.instrumentId, {
      instrumentId: identity.instrumentId,
      displaySymbol: identity.displaySymbol,
      trades: [trade],
    });
  }

  const movers: MarketMover[] = [];

  for (const { instrumentId, displaySymbol, trades: instrumentTrades } of tradesByInstrument.values()) {
    const sortedTrades = [...instrumentTrades].sort(
      (left, right) =>
        new Date(left.trade_timestamp).getTime() -
        new Date(right.trade_timestamp).getTime()
    );

    const latestTrade = sortedTrades[sortedTrades.length - 1];
    const previousTrade = sortedTrades[sortedTrades.length - 2] ?? latestTrade;

    const latestPrice = parseDecimal(latestTrade?.price_per_unit);
    const previousPrice = parseDecimal(previousTrade?.price_per_unit);

    const changePercent =
      previousPrice > 0 ? ((latestPrice - previousPrice) / previousPrice) * 100 : 0;

    movers.push({ instrumentId, symbol: displaySymbol, changePercent, latestPrice });
  }

  const gainers = [...movers]
    .filter((item) => item.changePercent >= 0)
    .sort((left, right) => right.changePercent - left.changePercent)
    .slice(0, 5);

  const losers = [...movers]
    .filter((item) => item.changePercent < 0)
    .sort((left, right) => left.changePercent - right.changePercent)
    .slice(0, 5);

  return { gainers, losers };
}

function buildEarningsCalendar(summary: PortfolioSummary): EarningsEvent[] {
  const baseDate = new Date();

  return summary.holdings
    .map((holding) => ({ holding, identity: buildHoldingIdentity(holding) }))
    .slice(0, 6)
    .map(({ holding, identity }, index) => {
      const offsetDays = ((holding.symbol.charCodeAt(0) + index * 7) % 24) + 3;
      const earningsDate = new Date(baseDate);
      earningsDate.setDate(baseDate.getDate() + offsetDays);

      return {
        instrumentId: identity.instrumentId,
        symbol: identity.displaySymbol,
        earningsDate: earningsDate.toISOString(),
        confidenceNote: "Estimated placeholder date until live earnings feed is connected.",
      };
    });
}

function buildHoldingIdentity(holding: HoldingSummary): InstrumentIdentity {
  return {
    instrumentId: buildCompositeInstrumentId({
      symbol: holding.symbol,
      exchange: holding.exchange,
      assetType: holding.asset_type,
      currency: holding.currency,
    }),
    displaySymbol: buildDisplaySymbol(holding.symbol, holding.exchange),
    providerTicker: buildProviderTicker({
      symbol: holding.symbol,
      exchange: holding.exchange,
      assetType: holding.asset_type,
      currency: holding.currency,
    }),
  };
}

function buildTradeIdentity(trade: TradeResponse): InstrumentIdentity {
  return {
    instrumentId: buildCompositeInstrumentId({
      symbol: trade.asset_symbol,
      exchange: trade.exchange,
      assetType: trade.asset_type,
      currency: trade.currency,
    }),
    displaySymbol: buildDisplaySymbol(trade.asset_symbol, trade.exchange),
    providerTicker: buildProviderTicker({
      symbol: trade.asset_symbol,
      exchange: trade.exchange,
      assetType: trade.asset_type,
      currency: trade.currency,
    }),
  };
}

function buildAiSummary(analysis: PortfolioAnalysisResponse): string {
  const overview = firstSentence(analysis.analysis.overview);
  const risk = firstSentence(analysis.analysis.risk_assessment);
  const recommendation = analysis.analysis.recommendations[0] ?? "No recommendation available.";

  return `${overview} ${risk} Priority for today: ${recommendation}`.trim();
}

function firstSentence(text: string): string {
  const sentence = text.split(".")[0]?.trim();
  return sentence ? `${sentence}.` : text;
}

function inferSentiment(text: string): "positive" | "negative" | "neutral" {
  const normalized = text.toLowerCase();

  if (normalized.includes("strong") || normalized.includes("well-diversified")) {
    return "positive";
  }

  if (normalized.includes("risk") || normalized.includes("concentrat")) {
    return "negative";
  }

  return "neutral";
}
