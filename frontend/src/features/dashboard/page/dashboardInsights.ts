import { type PortfolioAnalysisResponse, type TradeResponse } from "../../../shared/api/types";
import { formatDateTime, parseDecimal } from "../../../shared/lib/format";
import {
  buildCompositeInstrumentId,
  buildDisplaySymbol,
} from "../../../shared/lib/instrumentIdentity";

export type PortfolioValuePoint = {
  label: string;
  investedValue: number;
};

export type AllocationPoint = {
  id: string;
  label: string;
  value: number;
  percentage: number;
};

export type RiskLevel = "Low" | "Moderate" | "High" | "Unavailable";
export type DiversificationLevel =
  | "Strong"
  | "Moderate"
  | "Needs Improvement"
  | "Unavailable";

export type PortfolioHealth = {
  score: number | null;
  riskLevel: RiskLevel;
  diversificationLevel: DiversificationLevel;
};

export function buildPortfolioValueSeries(trades: TradeResponse[]): PortfolioValuePoint[] {
  if (trades.length === 0) {
    return [];
  }

  const sortedTrades = [...trades].sort(
    (left, right) =>
      new Date(left.trade_timestamp).getTime() -
      new Date(right.trade_timestamp).getTime()
  );

  let runningInvestedValue = 0;

  return sortedTrades.map((trade) => {
    const quantity = parseDecimal(trade.quantity);
    const pricePerUnit = parseDecimal(trade.price_per_unit);
    const tradeValue = quantity * pricePerUnit;

    runningInvestedValue += trade.transaction_type === "SELL" ? -tradeValue : tradeValue;

    return {
      label: formatDateTime(trade.trade_timestamp),
      investedValue: runningInvestedValue,
    };
  });
}

export function buildAllocationSeries(
  holdings: Array<{
    symbol: string;
    exchange: string | null;
    asset_type: string | null;
    currency: string | null;
    market_value: string | null;
  }>
): AllocationPoint[] {
  const valuedHoldings = holdings
    .map((holding) => {
      return {
        id: buildCompositeInstrumentId({
          symbol: holding.symbol,
          exchange: holding.exchange,
          assetType: holding.asset_type,
          currency: holding.currency,
        }),
        label: buildDisplaySymbol(holding.symbol, holding.exchange),
        value: holding.market_value == null ? null : parseDecimal(holding.market_value),
      };
    })
    .filter(
      (holding): holding is { id: string; label: string; value: number } =>
        holding.value != null
    );

  const totalMarketValue = valuedHoldings.reduce(
    (total, holding) => total + holding.value,
    0
  );

  if (totalMarketValue <= 0) {
    return [];
  }

  return valuedHoldings
    .map((holding) => ({
      id: holding.id,
      label: holding.label,
      value: holding.value,
      percentage: (holding.value / totalMarketValue) * 100,
    }))
    .sort((left, right) => right.value - left.value);
}

export function buildPortfolioHealth(
  analysis: PortfolioAnalysisResponse | null
): PortfolioHealth {
  if (!analysis) {
    return {
      score: null,
      riskLevel: "Unavailable",
      diversificationLevel: "Unavailable",
    };
  }

  const riskLevel = inferRiskLevel(analysis.analysis.risk_assessment);
  const diversificationLevel = inferDiversificationLevel(
    analysis.analysis.diversification_analysis
  );

  let score = 65;

  if (riskLevel === "Low") {
    score += 10;
  } else if (riskLevel === "High") {
    score -= 15;
  }

  if (diversificationLevel === "Strong") {
    score += 12;
  } else if (diversificationLevel === "Needs Improvement") {
    score -= 12;
  }

  score += Math.min(analysis.analysis.strengths.length * 2, 8);
  score -= Math.min(analysis.analysis.weaknesses.length * 2, 8);

  return {
    score: Math.max(0, Math.min(100, score)),
    riskLevel,
    diversificationLevel,
  };
}

export function buildDailyBrief(analysis: PortfolioAnalysisResponse | null): string[] {
  if (!analysis) {
    return [];
  }

  const points = [
    analysis.analysis.recommendations[0],
    firstSentence(analysis.analysis.diversification_analysis),
    firstSentence(analysis.analysis.risk_assessment),
  ].filter((item): item is string => Boolean(item && item.trim().length > 0));

  return Array.from(new Set(points)).slice(0, 3);
}

function inferRiskLevel(value: string): RiskLevel {
  const normalized = value.toLowerCase();

  if (normalized.includes("high")) {
    return "High";
  }

  if (normalized.includes("low")) {
    return "Low";
  }

  if (normalized.includes("moderate") || normalized.includes("medium")) {
    return "Moderate";
  }

  return "Unavailable";
}

function inferDiversificationLevel(value: string): DiversificationLevel {
  const normalized = value.toLowerCase();

  if (
    normalized.includes("well-diversified") ||
    normalized.includes("well diversified") ||
    normalized.includes("strong")
  ) {
    return "Strong";
  }

  if (
    normalized.includes("concentrat") ||
    normalized.includes("limited") ||
    normalized.includes("below")
  ) {
    return "Needs Improvement";
  }

  if (normalized.includes("moderate") || normalized.includes("balanced")) {
    return "Moderate";
  }

  return "Unavailable";
}

function firstSentence(value: string): string {
  const sentence = value.split(".")[0]?.trim();
  return sentence ? `${sentence}.` : value;
}
