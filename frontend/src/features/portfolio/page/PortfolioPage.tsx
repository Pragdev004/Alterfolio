import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { getPortfolioSummary } from "../../../shared/api/alterfolioApi";
import { PortfolioSummary, getApiErrorMessage } from "../../../shared/api/types";
import { useLoading } from "../../../shared/hooks/useLoading";
import {
  formatCurrency,
  formatNumber,
  formatSignedCurrency,
  parseDecimal,
} from "../../../shared/lib/format";

import {
  StatCard,
  type StatCardTone,
} from "../../../shared/ui/data-display/StatCard";
import { SkeletonBlock } from "../../../shared/ui/feedback/SkeletonBlock";
import { PageContainer } from "../../../shared/ui/layout/PageContainer";
import {
  type HoldingMetric,
  buildAllocationData,
  buildGainLossData,
  buildHoldingMetrics,
  buildPortfolioStatistics,
  buildTopPerformers,
} from "./portfolioMetrics";

import "./PortfolioPage.css";

const STAT_CARD_SKELETONS = [0, 1, 2, 3] as const;
const TABLE_SKELETON_LINES = [0, 1, 2, 3] as const;
const CHART_COLORS = [
  "var(--color-primary)",
  "var(--color-primary-strong)",
  "var(--color-text-secondary)",
  "var(--color-text-muted)",
  "var(--color-border-muted)",
] as const;

type SortKey =
  | "symbol"
  | "quantity"
  | "averageCost"
  | "currentPrice"
  | "marketValue"
  | "profitLoss"
  | "profitLossPercent";

type SortDirection = "asc" | "desc";

type SortConfig = {
  key: SortKey;
  direction: SortDirection;
};

type SectionErrorStateProps = {
  message: string;
  retryLabel: string;
  onRetry: () => void;
};

function SectionErrorState({
  message,
  retryLabel,
  onRetry,
}: SectionErrorStateProps) {
  return (
    <div className="section-error" role="alert">
      <p className="feedback error">{message}</p>
      <button type="button" className="button-secondary" onClick={onRetry}>
        {retryLabel}
      </button>
    </div>
  );
}

function TableSkeleton() {
  return (
    <div className="table-skeleton" aria-hidden="true">
      {TABLE_SKELETON_LINES.map((line) => (
        <SkeletonBlock
          key={`portfolio-table-skeleton-${line}`}
          className="skeleton-line-large"
        />
      ))}
    </div>
  );
}

function formatTooltipCurrency(value: unknown): string {
  if (typeof value === "number") {
    return formatCurrency(value);
  }

  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? formatCurrency(parsed) : formatCurrency(0);
  }

  if (Array.isArray(value) && typeof value[0] === "number") {
    return formatCurrency(value[0]);
  }

  return formatCurrency(0);
}

function formatSignedPercentage(value: number | null): string {
  if (value == null) {
    return "Unavailable";
  }

  const absolute = `${formatNumber(Math.abs(value))}%`;

  if (value > 0) {
    return `+${absolute}`;
  }

  if (value < 0) {
    return `-${absolute}`;
  }

  return absolute;
}

function formatMaybeCurrency(value: number | null): string {
  if (value == null) {
    return "Unavailable";
  }

  return formatCurrency(value);
}

function formatMaybeSignedCurrency(value: number | null): string {
  if (value == null) {
    return "Unavailable";
  }

  return formatSignedCurrency(value);
}

function getProfitLossTone(value: number | null): string {
  if (value == null) {
    return "";
  }

  if (value > 0) {
    return "portfolio-cell-positive";
  }

  if (value < 0) {
    return "portfolio-cell-negative";
  }

  return "";
}


function sortHoldings(
  holdings: HoldingMetric[],
  sortConfig: SortConfig
): HoldingMetric[] {
  const sorted = [...holdings].sort((left, right) => {
    if (sortConfig.key === "symbol") {
      return left.displayLabel.localeCompare(right.displayLabel);
    }


    const leftValue = left[sortConfig.key] ?? Number.NEGATIVE_INFINITY;
    const rightValue = right[sortConfig.key] ?? Number.NEGATIVE_INFINITY;

    return leftValue - rightValue;
  });

  return sortConfig.direction === "asc" ? sorted : sorted.reverse();
}


export function PortfolioPage() {
  const { startLoading, stopLoading } = useLoading();
  const isMountedRef = useRef(true);

  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [isSummaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState("");
  const [sortConfig, setSortConfig] = useState<SortConfig>({
    key: "marketValue",
    direction: "desc",
  });

  const loadSummary = useCallback(async (): Promise<void> => {
    if (!isMountedRef.current) {
      return;
    }

    setSummaryLoading(true);
    setSummaryError("");
    startLoading();

    try {
      const response = await getPortfolioSummary();

      if (isMountedRef.current) {
        setSummary(response);
      }
    } catch (error) {
      if (isMountedRef.current) {
        setSummaryError(getApiErrorMessage(error));
      }
    } finally {
      if (isMountedRef.current) {
        setSummaryLoading(false);
      }

      stopLoading();
    }
  }, [startLoading, stopLoading]);

  useEffect(() => {
    isMountedRef.current = true;

    void loadSummary();

    return () => {
      isMountedRef.current = false;
    };
  }, [loadSummary]);

  const holdingMetrics = useMemo(
    () => buildHoldingMetrics(summary?.holdings ?? []),
    [summary?.holdings]
  );

  const sortedHoldings = useMemo(
    () => sortHoldings(holdingMetrics, sortConfig),
    [holdingMetrics, sortConfig]
  );

  const allocationData = useMemo(
    () => buildAllocationData(holdingMetrics),
    [holdingMetrics]
  );

  const gainLossData = useMemo(
    () => buildGainLossData(holdingMetrics),
    [holdingMetrics]
  );

  const topPerformers = useMemo(
    () => buildTopPerformers(holdingMetrics),
    [holdingMetrics]
  );

  const statistics = useMemo(
    () => buildPortfolioStatistics(holdingMetrics),
    [holdingMetrics]
  );

    const totalInvested = useMemo(
    () => parseDecimal(summary?.total_invested),
    [summary?.total_invested]
  );

  const currentValue = useMemo(
    () =>
      summary?.total_market_value == null
        ? null
        : parseDecimal(summary.total_market_value),
    [summary?.total_market_value]
  );

  const unrealizedGainLoss = useMemo(
    () =>
      summary?.total_unrealized_profit_loss == null
        ? null
        : parseDecimal(summary.total_unrealized_profit_loss),
    [summary?.total_unrealized_profit_loss]
  );

    const unrealizedTone: StatCardTone =
    unrealizedGainLoss == null
      ? "default"
      : unrealizedGainLoss > 0
        ? "positive"
        : unrealizedGainLoss < 0
          ? "negative"
          : "default";

  const valuationStatus = summary?.valuation_status ?? "UNAVAILABLE";
  const isCompleteValuation = valuationStatus === "COMPLETE";
  const isPartialValuation = valuationStatus === "PARTIAL";
  const valuedHoldingsCount = holdingMetrics.filter(
    (holding) => holding.quoteStatus === "AVAILABLE"
  ).length;


  const handleSort = useCallback((key: SortKey) => {

    setSortConfig((previous) => {
      if (previous.key === key) {
        return {
          key,
          direction: previous.direction === "asc" ? "desc" : "asc",
        };
      }

      return {
        key,
        direction: key === "symbol" ? "asc" : "desc",
      };
    });
  }, []);

  const getSortIndicator = useCallback(
    (key: SortKey): string => {
      if (sortConfig.key !== key) {
        return "";
      }

      return sortConfig.direction === "asc" ? " ↑" : " ↓";
    },
    [sortConfig]
  );

  const getAriaSort = useCallback(
    (key: SortKey): "ascending" | "descending" | "none" => {
      if (sortConfig.key !== key) {
        return "none";
      }

      return sortConfig.direction === "asc" ? "ascending" : "descending";
    },
    [sortConfig]
  );

  const handleSummaryRetry = useCallback(() => {
    void loadSummary();
  }, [loadSummary]);

  return (
    <PageContainer
      title="Portfolio"
      description="Professional portfolio analytics using your current holdings data."
    >
      <div className="portfolio-layout">
        <div className="stats-grid" aria-busy={isSummaryLoading}>
          {isSummaryLoading ?
            STAT_CARD_SKELETONS.map((item) => (
              <article className="stat-card stat-card-skeleton" key={item}>
                <SkeletonBlock className="skeleton-line-short" />
                <SkeletonBlock className="skeleton-line-large" />
              </article>
            ))
          : summaryError ? (
            <section className="portfolio-section section-card-span-all">
              <SectionErrorState
                message={summaryError}
                retryLabel="Retry Portfolio Summary"
                onRetry={handleSummaryRetry}
              />
            </section>
          ) : (
            <>
                            <StatCard label="Total Invested" value={formatCurrency(totalInvested)} />
              <StatCard label="Current Value" value={formatMaybeCurrency(currentValue)} />
              <StatCard
                label="Unrealized Gain / Loss"
                value={formatMaybeSignedCurrency(unrealizedGainLoss)}
                tone={unrealizedTone}
              />

              <StatCard label="Number of Holdings" value={String(holdingMetrics.length)} />
            </>
          )}
        </div>

        <section className="portfolio-section" aria-busy={isSummaryLoading}>
          <header className="portfolio-section-header">
            <h2 className="portfolio-section-title">Holdings Table</h2>
                                    <p className="portfolio-section-note">
              Valuation status: {valuationStatus}
              {holdingMetrics.length > 0
                ? ` (${valuedHoldingsCount}/${holdingMetrics.length} holdings valued)`
                : ""}
            </p>


          </header>

          {isSummaryLoading ? (
            <TableSkeleton />
          ) : summaryError ? (
            <SectionErrorState
              message={summaryError}
              retryLabel="Retry Holdings"
              onRetry={handleSummaryRetry}
            />
          ) : sortedHoldings.length === 0 ? (
            <p className="portfolio-empty">No holdings found in your portfolio yet.</p>
          ) : (
            <div className="table-wrap">
              <table className="portfolio-table">
                <caption className="sr-only">Portfolio holdings with computed analytics</caption>
                <thead>
                  <tr>
                    <th scope="col" aria-sort={getAriaSort("symbol")}>
                      <button
                        type="button"
                        className="portfolio-sort-button"
                        onClick={() => handleSort("symbol")}
                      >
                        Symbol{getSortIndicator("symbol")}
                      </button>
                    </th>
                    <th scope="col" aria-sort={getAriaSort("quantity")}>
                      <button
                        type="button"
                        className="portfolio-sort-button"
                        onClick={() => handleSort("quantity")}
                      >
                        Quantity{getSortIndicator("quantity")}
                      </button>
                    </th>
                    <th scope="col" aria-sort={getAriaSort("averageCost")}>
                      <button
                        type="button"
                        className="portfolio-sort-button"
                        onClick={() => handleSort("averageCost")}
                      >
                        Average Cost{getSortIndicator("averageCost")}
                      </button>
                    </th>
                    <th scope="col" aria-sort={getAriaSort("currentPrice")}>
                      <button
                        type="button"
                        className="portfolio-sort-button"
                        onClick={() => handleSort("currentPrice")}
                      >
                        Current Price{getSortIndicator("currentPrice")}
                      </button>
                    </th>
                    <th scope="col" aria-sort={getAriaSort("marketValue")}>
                      <button
                        type="button"
                        className="portfolio-sort-button"
                        onClick={() => handleSort("marketValue")}
                      >
                        Market Value{getSortIndicator("marketValue")}
                      </button>
                    </th>
                    <th scope="col" aria-sort={getAriaSort("profitLoss")}>
                      <button
                        type="button"
                        className="portfolio-sort-button"
                        onClick={() => handleSort("profitLoss")}
                      >
                        Profit / Loss{getSortIndicator("profitLoss")}
                      </button>
                    </th>
                    <th scope="col" aria-sort={getAriaSort("profitLossPercent")}>
                      <button
                        type="button"
                        className="portfolio-sort-button"
                        onClick={() => handleSort("profitLossPercent")}
                      >
                        Profit %{getSortIndicator("profitLossPercent")}
                      </button>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {sortedHoldings.map((holding) => {
                    const toneClass = getProfitLossTone(holding.profitLoss);

                    return (
                                            <tr key={holding.instrumentId}>
                        <td data-label="Symbol">{holding.displayLabel}</td>

                        <td data-label="Quantity">{formatNumber(holding.quantity)}</td>
                        <td data-label="Average Cost">
                          {formatCurrency(holding.averageCost)}
                        </td>
                                                <td data-label="Current Price">
                          {formatMaybeCurrency(holding.currentPrice)}
                        </td>
                        <td data-label="Market Value">
                          {formatMaybeCurrency(holding.marketValue)}
                        </td>
                        <td data-label="Profit / Loss" className={toneClass}>
                          {formatMaybeSignedCurrency(holding.profitLoss)}
                        </td>
                        <td data-label="Profit %" className={toneClass}>
                          {formatSignedPercentage(holding.profitLossPercent)}
                        </td>

                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <div className="portfolio-grid-2">
          <section className="portfolio-section" aria-busy={isSummaryLoading}>
            <header className="portfolio-section-header">
              <h2 className="portfolio-section-title">Portfolio Allocation</h2>
            </header>

                        {isSummaryLoading ? (
              <TableSkeleton />
            ) : !isCompleteValuation ? (
              <p className="portfolio-empty">
                {isPartialValuation
                  ? `Allocation is hidden because valuation is partial (${valuedHoldingsCount}/${holdingMetrics.length} holdings valued).`
                  : "Allocation is unavailable because live valuation data is unavailable."}
              </p>
            ) : allocationData.length === 0 ? (
              <p className="portfolio-empty">
                Allocation data appears when holdings are available.
              </p>
            ) : (

              <div
                className="portfolio-chart"
                role="img"
                aria-label="Portfolio allocation by holding"
              >
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={allocationData}
                      dataKey="value"
                                            nameKey="label"

                      innerRadius="55%"
                      outerRadius="82%"
                      paddingAngle={2}
                    >
                                            {allocationData.map((item, index) => (
                        <Cell
                          key={item.id}
                          fill={CHART_COLORS[index % CHART_COLORS.length]}
                        />
                      ))}

                    </Pie>
                    <Tooltip
                      formatter={(value) => formatTooltipCurrency(value)}
                      contentStyle={{
                        borderRadius: "10px",
                        border: "1px solid var(--color-border-default)",
                        background: "var(--color-surface-overlay)",
                      }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            )}
          </section>

          <section className="portfolio-section" aria-busy={isSummaryLoading}>
            <header className="portfolio-section-header">
              <h2 className="portfolio-section-title">Gain / Loss Chart</h2>
            </header>

                        {isSummaryLoading ? (
              <TableSkeleton />
            ) : !isCompleteValuation ? (
              <p className="portfolio-empty">
                {isPartialValuation
                  ? `Gain/loss distribution is hidden because valuation is partial (${valuedHoldingsCount}/${holdingMetrics.length} holdings valued).`
                  : "Gain/loss distribution is unavailable because live valuation data is unavailable."}
              </p>
            ) : gainLossData.length === 0 ? (
              <p className="portfolio-empty">No gain/loss distribution available yet.</p>
            ) : (

              <div
                className="portfolio-chart"
                role="img"
                aria-label="Gain and loss across portfolio holdings"
              >
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={gainLossData}
                    margin={{ top: 8, right: 8, left: 8, bottom: 8 }}
                  >
                    <CartesianGrid
                      stroke="var(--color-border-default)"
                      strokeDasharray="3 3"
                    />
                    <XAxis
                                            dataKey="label"

                      tick={{ fill: "var(--color-text-muted)", fontSize: 12 }}
                    />
                    <YAxis
                      tick={{ fill: "var(--color-text-muted)", fontSize: 12 }}
                      tickFormatter={(value) => formatCurrency(Number(value))}
                    />
                    <Tooltip
                      formatter={(value) => formatTooltipCurrency(value)}
                      contentStyle={{
                        borderRadius: "10px",
                        border: "1px solid var(--color-border-default)",
                        background: "var(--color-surface-overlay)",
                      }}
                    />
                    <Bar dataKey="profitLoss" radius={[6, 6, 0, 0]}>
                      {gainLossData.map((item) => (
                        <Cell
                                                    key={`gain-loss-${item.id}`}

                          fill={
                            item.profitLoss >= 0
                              ? "var(--color-positive)"
                              : "var(--color-negative)"
                          }
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </section>
        </div>

        <div className="portfolio-grid-2">
          <section className="portfolio-section" aria-busy={isSummaryLoading}>
            <header className="portfolio-section-header">
              <h2 className="portfolio-section-title">Top Winners</h2>
            </header>

                        {!isCompleteValuation ? (
              <p className="portfolio-empty">
                {isPartialValuation
                  ? `Top winners are hidden because valuation is partial (${valuedHoldingsCount}/${holdingMetrics.length} holdings valued).`
                  : "Top winners are unavailable because live valuation data is unavailable."}
              </p>
            ) : topPerformers.winners.length === 0 ? (
              <p className="portfolio-empty">No holdings available.</p>
            ) : (

              <ul className="portfolio-list">
                {topPerformers.winners.map((holding) => (
                                    <li key={`winner-${holding.instrumentId}`} className="portfolio-list-item">
                    <div>
                      <p className="portfolio-list-label">{holding.displayLabel}</p>

                                            <p className="portfolio-list-value">
                        Market Value: {formatMaybeCurrency(holding.marketValue)}
                      </p>
                    </div>
                    <p className={`portfolio-list-label ${getProfitLossTone(holding.profitLoss)}`}>
                      {formatMaybeSignedCurrency(holding.profitLoss)}
                    </p>

                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="portfolio-section" aria-busy={isSummaryLoading}>
            <header className="portfolio-section-header">
              <h2 className="portfolio-section-title">Top Losers</h2>
            </header>

                        {!isCompleteValuation ? (
              <p className="portfolio-empty">
                {isPartialValuation
                  ? `Top losers are hidden because valuation is partial (${valuedHoldingsCount}/${holdingMetrics.length} holdings valued).`
                  : "Top losers are unavailable because live valuation data is unavailable."}
              </p>
            ) : topPerformers.losers.length === 0 ? (
              <p className="portfolio-empty">No holdings available.</p>
            ) : (

              <ul className="portfolio-list">
                {topPerformers.losers.map((holding) => (
                                    <li key={`loser-${holding.instrumentId}`} className="portfolio-list-item">
                    <div>
                      <p className="portfolio-list-label">{holding.displayLabel}</p>

                                            <p className="portfolio-list-value">
                        Market Value: {formatMaybeCurrency(holding.marketValue)}
                      </p>
                    </div>
                    <p className={`portfolio-list-label ${getProfitLossTone(holding.profitLoss)}`}>
                      {formatMaybeSignedCurrency(holding.profitLoss)}
                    </p>

                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <section className="portfolio-section" aria-busy={isSummaryLoading}>
          <header className="portfolio-section-header">
            <h2 className="portfolio-section-title">Portfolio Statistics</h2>
          </header>

                              {!isCompleteValuation ? (
            <p className="portfolio-empty">
              {isPartialValuation
                ? `Portfolio statistics are hidden because valuation is partial (${valuedHoldingsCount}/${holdingMetrics.length} holdings valued).`
                : "Valuation data is unavailable for statistics."}
            </p>
          ) : statistics.largestPosition == null ? (
            <p className="portfolio-empty">Valuation data is unavailable for statistics.</p>
          ) : (


            <div className="portfolio-stats-grid">
              <article className="portfolio-stat">
                <p className="portfolio-stat-label">Largest Position</p>
                <p className="portfolio-stat-value">
                                                      {statistics.largestPosition?.displayLabel ?? "-"} ({formatMaybeCurrency(

                    statistics.largestPosition?.marketValue ?? null
                  )})

                </p>
              </article>
              <article className="portfolio-stat">
                <p className="portfolio-stat-label">Smallest Position</p>
                <p className="portfolio-stat-value">
                                                      {statistics.smallestPosition?.displayLabel ?? "-"} ({formatMaybeCurrency(

                    statistics.smallestPosition?.marketValue ?? null
                  )})

                </p>
              </article>
              <article className="portfolio-stat">
                <p className="portfolio-stat-label">Diversification Score</p>
                <p className="portfolio-stat-value">
                  {formatNumber(statistics.diversificationScore)} / 100
                </p>
              </article>
              <article className="portfolio-stat">
                <p className="portfolio-stat-label">Average Position Size</p>
                <p className="portfolio-stat-value">
                  {formatCurrency(statistics.averagePositionSize)}
                </p>
              </article>
            </div>
          )}
        </section>
      </div>
    </PageContainer>
  );
}