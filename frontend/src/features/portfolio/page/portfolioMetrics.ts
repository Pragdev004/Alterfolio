import { type HoldingSummary } from "../../../shared/api/types";
import { parseDecimal } from "../../../shared/lib/format";

export type HoldingMetric = {
  symbol: string;
  quantity: number;
  averageCost: number;
  currentPrice: number;
  investedAmount: number;
  marketValue: number;
  profitLoss: number;
  profitLossPercent: number;
};

export type AllocationDatum = {
  symbol: string;
  value: number;
  weightPercent: number;
};

export type GainLossDatum = {
  symbol: string;
  profitLoss: number;
};

export type PortfolioStatistics = {
  largestPosition: HoldingMetric | null;
  smallestPosition: HoldingMetric | null;
  diversificationScore: number;
  averagePositionSize: number;
};

export type TopPerformers = {
  winners: HoldingMetric[];
  losers: HoldingMetric[];
};

export function buildHoldingMetrics(holdings: HoldingSummary[]): HoldingMetric[] {
  return holdings.map((holding) => {
    const quantity = parseDecimal(holding.quantity);
    const averageCost = parseDecimal(holding.average_buy_price);
    const investedAmount = parseDecimal(holding.invested_amount);

    const currentPrice = quantity > 0 ? investedAmount / quantity : averageCost;
    const marketValue = currentPrice * quantity;
    const profitLoss = marketValue - investedAmount;
    const profitLossPercent =
      investedAmount > 0 ? (profitLoss / investedAmount) * 100 : 0;

    return {
      symbol: holding.symbol,
      quantity,
      averageCost,
      currentPrice,
      investedAmount,
      marketValue,
      profitLoss,
      profitLossPercent,
    };
  });
}

export function buildAllocationData(holdings: HoldingMetric[]): AllocationDatum[] {
  const totalMarketValue = holdings.reduce(
    (total, holding) => total + holding.marketValue,
    0
  );

  if (totalMarketValue <= 0) {
    return [];
  }

  return holdings
    .map((holding) => ({
      symbol: holding.symbol,
      value: holding.marketValue,
      weightPercent: (holding.marketValue / totalMarketValue) * 100,
    }))
    .sort((left, right) => right.value - left.value);
}

export function buildGainLossData(holdings: HoldingMetric[]): GainLossDatum[] {
  return holdings
    .map((holding) => ({
      symbol: holding.symbol,
      profitLoss: holding.profitLoss,
    }))
    .sort((left, right) => right.profitLoss - left.profitLoss);
}

export function buildPortfolioStatistics(
  holdings: HoldingMetric[]
): PortfolioStatistics {
  if (holdings.length === 0) {
    return {
      largestPosition: null,
      smallestPosition: null,
      diversificationScore: 0,
      averagePositionSize: 0,
    };
  }

  const sortedBySize = [...holdings].sort(
    (left, right) => right.marketValue - left.marketValue
  );

  const totalMarketValue = sortedBySize.reduce(
    (total, holding) => total + holding.marketValue,
    0
  );

  const averagePositionSize = totalMarketValue / holdings.length;

  return {
    largestPosition: sortedBySize[0],
    smallestPosition: sortedBySize[sortedBySize.length - 1],
    diversificationScore: calculateDiversificationScore(sortedBySize),
    averagePositionSize,
  };
}

export function buildTopPerformers(
  holdings: HoldingMetric[],
  count = 3
): TopPerformers {
  const sortedByGainLoss = [...holdings].sort((left, right) => {
    if (right.profitLoss === left.profitLoss) {
      return right.marketValue - left.marketValue;
    }

    return right.profitLoss - left.profitLoss;
  });

  const winners = sortedByGainLoss.slice(0, count);
  const losers = [...sortedByGainLoss].reverse().slice(0, count);

  return { winners, losers };
}

function calculateDiversificationScore(holdings: HoldingMetric[]): number {
  if (holdings.length <= 1) {
    return 0;
  }

  const totalMarketValue = holdings.reduce(
    (total, holding) => total + holding.marketValue,
    0
  );

  if (totalMarketValue <= 0) {
    return 0;
  }

  const concentration = holdings.reduce((total, holding) => {
    const weight = holding.marketValue / totalMarketValue;
    return total + weight * weight;
  }, 0);

  const holdingCount = holdings.length;
  const maxDiversifiedConcentration = 1 / holdingCount;

  const normalizedScore =
    (1 - concentration) / (1 - maxDiversifiedConcentration);

  return Math.max(0, Math.min(100, normalizedScore * 100));
}
