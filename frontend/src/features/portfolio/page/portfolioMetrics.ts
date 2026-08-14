import { type HoldingSummary } from "../../../shared/api/types";
import { parseDecimal } from "../../../shared/lib/format";
import {
  buildCompositeInstrumentId,
  buildDisplaySymbol,
} from "../../../shared/lib/instrumentIdentity";

export type HoldingMetric = {
  instrumentId: string;
  displayLabel: string;
  symbol: string;
  exchange: string | null;
  assetType: string | null;
  currency: string | null;
  quantity: number;
  averageCost: number;
  currentPrice: number | null;
  investedAmount: number;
  marketValue: number | null;
  profitLoss: number | null;
  profitLossPercent: number | null;
  quoteStatus: "AVAILABLE" | "UNAVAILABLE";
};

export type AllocationDatum = {
  id: string;
  label: string;
  value: number;
  weightPercent: number;
};

export type GainLossDatum = {
  id: string;
  label: string;
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

    const currentPrice =
      holding.current_price == null ? null : parseDecimal(holding.current_price);
    const marketValue =
      holding.market_value == null ? null : parseDecimal(holding.market_value);
    const profitLoss =
      holding.unrealized_profit_loss == null
        ? null
        : parseDecimal(holding.unrealized_profit_loss);
    const profitLossPercent =
      profitLoss == null || investedAmount <= 0
        ? null
        : (profitLoss / investedAmount) * 100;

    return {
      instrumentId: buildInstrumentId(holding),
      displayLabel: buildHoldingLabel(holding.symbol, holding.exchange),
      symbol: holding.symbol,
      exchange: holding.exchange,
      assetType: holding.asset_type,
      currency: holding.currency,
      quantity,
      averageCost,
      currentPrice,
      investedAmount,
      marketValue,
      profitLoss,
      profitLossPercent,
      quoteStatus: holding.quote_status,
    };
  });
}

export function buildAllocationData(holdings: HoldingMetric[]): AllocationDatum[] {
  const valuedHoldings = holdings.filter((holding) => holding.marketValue != null);
  const totalMarketValue = valuedHoldings.reduce(
    (total, holding) => total + (holding.marketValue ?? 0),
    0
  );

  if (totalMarketValue <= 0) {
    return [];
  }

  return valuedHoldings
    .map((holding) => ({
      id: holding.instrumentId,
      label: holding.displayLabel,
      value: holding.marketValue ?? 0,
      weightPercent: ((holding.marketValue ?? 0) / totalMarketValue) * 100,
    }))
    .sort((left, right) => right.value - left.value);
}

export function buildGainLossData(holdings: HoldingMetric[]): GainLossDatum[] {
  return holdings
    .filter((holding) => holding.profitLoss != null)
    .map((holding) => ({
      id: holding.instrumentId,
      label: holding.displayLabel,
      profitLoss: holding.profitLoss ?? 0,
    }))
    .sort((left, right) => right.profitLoss - left.profitLoss);
}

export function buildPortfolioStatistics(
  holdings: HoldingMetric[]
): PortfolioStatistics {
  const valuedHoldings = holdings.filter((holding) => holding.marketValue != null);

  if (valuedHoldings.length === 0) {
    return {
      largestPosition: null,
      smallestPosition: null,
      diversificationScore: 0,
      averagePositionSize: 0,
    };
  }

  const sortedBySize = [...valuedHoldings].sort(
    (left, right) => (right.marketValue ?? 0) - (left.marketValue ?? 0)
  );

  const totalMarketValue = sortedBySize.reduce(
    (total, holding) => total + (holding.marketValue ?? 0),
    0
  );

  const averagePositionSize = totalMarketValue / valuedHoldings.length;

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
  const valuedByGainLoss = holdings.filter((holding) => holding.profitLoss != null);

  const sortedByGainLoss = [...valuedByGainLoss].sort((left, right) => {
    if ((right.profitLoss ?? 0) === (left.profitLoss ?? 0)) {
      return (right.marketValue ?? 0) - (left.marketValue ?? 0);
    }

    return (right.profitLoss ?? 0) - (left.profitLoss ?? 0);
  });

  const winners = sortedByGainLoss.slice(0, count);
  const losers = [...sortedByGainLoss].reverse().slice(0, count);

  return { winners, losers };
}

function buildInstrumentId(holding: HoldingSummary): string {
  return buildCompositeInstrumentId({
    symbol: holding.symbol,
    exchange: holding.exchange,
    assetType: holding.asset_type,
    currency: holding.currency,
  });
}

function buildHoldingLabel(symbol: string, exchange: string | null): string {
  return buildDisplaySymbol(symbol, exchange);
}

function calculateDiversificationScore(holdings: HoldingMetric[]): number {
  if (holdings.length <= 1) {
    return 0;
  }

  const totalMarketValue = holdings.reduce(
    (total, holding) => total + (holding.marketValue ?? 0),
    0
  );

  if (totalMarketValue <= 0) {
    return 0;
  }

  const concentration = holdings.reduce((total, holding) => {
    const weight = (holding.marketValue ?? 0) / totalMarketValue;
    return total + weight * weight;
  }, 0);

  const holdingCount = holdings.length;
  const maxDiversifiedConcentration = 1 / holdingCount;

  const normalizedScore =
    (1 - concentration) / (1 - maxDiversifiedConcentration);

  return Math.max(0, Math.min(100, normalizedScore * 100));
}
