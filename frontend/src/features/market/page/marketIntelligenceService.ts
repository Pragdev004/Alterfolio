import { getPortfolioAnalysis, getPortfolioSummary, getTrades } from "../../../shared/api/alterfolioApi";
import { apiClient } from "../../../services/apiClient";
import { parseDecimal } from "../../../shared/lib/format";
import {
  type PortfolioAnalysisResponse,
  type PortfolioSummary,
  type TradeResponse,
} from "../../../shared/api/types";
import {
  type EarningsEvent,
  type MarketIntelligenceData,
  type MarketMover,
  type MarketNewsItem,
  type PortfolioImpactItem,
} from "./marketTypes";

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
  const topSymbols = summary.holdings
    .map((holding) => ({
      symbol: holding.symbol,
      invested: parseDecimal(holding.invested_amount),
    }))
    .sort((left, right) => right.invested - left.invested)
    .slice(0, 4)
    .map((holding) => holding.symbol);

  const news = buildDerivedNews(topSymbols, analysis);
  const impact = buildPortfolioImpact(news, summary);
  const movers = buildMarketMovers(trades);
  const earnings = buildEarningsCalendar(summary);

  return {
    news,
    impact,
    aiSummary: buildAiSummary(analysis),
    movers,
    earnings,
    dataSource: "derived",
  };
}

function buildDerivedNews(
  topSymbols: string[],
  analysis: PortfolioAnalysisResponse
): MarketNewsItem[] {
  const now = Date.now();

  const derivedStories = [
    {
      headline: `Risk watch across ${topSymbols.slice(0, 2).join(" and ") || "your top holdings"}`,
      summary: firstSentence(analysis.analysis.risk_assessment),
      sentiment: inferSentiment(analysis.analysis.risk_assessment),
      relatedSymbols: topSymbols.slice(0, 3),
    },
    {
      headline: "Diversification update from today’s portfolio signals",
      summary: firstSentence(analysis.analysis.diversification_analysis),
      sentiment: inferSentiment(analysis.analysis.diversification_analysis),
      relatedSymbols: topSymbols.slice(1, 4),
    },
    {
      headline: "Actionable recommendation focus for this session",
      summary: analysis.analysis.recommendations[0] ?? "No recommendation available.",
      sentiment: "neutral" as const,
      relatedSymbols: topSymbols.slice(0, 2),
    },
  ];

  return derivedStories.map((story, index) => ({
    id: `derived-news-${index}`,
    headline: story.headline,
    summary: story.summary,
    source: "Derived intelligence (portfolio + AI analysis)",
    publishedAt: new Date(now - index * 60 * 60 * 1000).toISOString(),
    relatedSymbols: story.relatedSymbols,
    sentiment: story.sentiment,
  }));
}

function buildPortfolioImpact(
  news: MarketNewsItem[],
  summary: PortfolioSummary
): PortfolioImpactItem[] {
  const impactMap = new Map<string, PortfolioImpactItem>();

  for (const holding of summary.holdings) {
    impactMap.set(holding.symbol, {
      symbol: holding.symbol,
      mentionCount: 0,
      latestHeadline: "No direct mention in current feed.",
    });
  }

  for (const item of news) {
    for (const symbol of item.relatedSymbols) {
      const existing = impactMap.get(symbol);
      if (!existing) {
        continue;
      }

      impactMap.set(symbol, {
        symbol,
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
  const tradesBySymbol = new Map<string, TradeResponse[]>();

  for (const trade of trades) {
    const list = tradesBySymbol.get(trade.asset_symbol) ?? [];
    list.push(trade);
    tradesBySymbol.set(trade.asset_symbol, list);
  }

  const movers: MarketMover[] = [];

  for (const [symbol, symbolTrades] of tradesBySymbol.entries()) {
    const sortedTrades = [...symbolTrades].sort(
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

    movers.push({ symbol, changePercent, latestPrice });
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

  return summary.holdings.slice(0, 6).map((holding, index) => {
    const offsetDays = ((holding.symbol.charCodeAt(0) + index * 7) % 24) + 3;
    const earningsDate = new Date(baseDate);
    earningsDate.setDate(baseDate.getDate() + offsetDays);

    return {
      symbol: holding.symbol,
      earningsDate: earningsDate.toISOString(),
      confidenceNote: "Estimated placeholder date until live earnings feed is connected.",
    };
  });
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
