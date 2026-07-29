import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { PageContainer } from "../../../shared/ui/layout/PageContainer";
import { SkeletonBlock } from "../../../shared/ui/feedback/SkeletonBlock";
import {
  StatCard,
  type StatCardTone,
} from "../../../shared/ui/data-display/StatCard";
import { useLoading } from "../../../shared/hooks/useLoading";
import {
  getPortfolioAnalysis,
  getPortfolioSummary,
  getTrades,
} from "../../../shared/api/alterfolioApi";
import {
  PortfolioAnalysisResponse,
  PortfolioSummary,
  TradeResponse,
  getApiErrorMessage,
} from "../../../shared/api/types";
import {
  formatCurrency,
  formatDateTime,
  formatNumber,
  formatSignedCurrency,
  parseDecimal,
} from "../../../shared/lib/format";
import {
  buildAllocationSeries,
  buildDailyBrief,
  buildPortfolioHealth,
  buildPortfolioValueSeries,
} from "./dashboardInsights";

import "./DashboardPage.css";

const MAX_HOLDINGS_PREVIEW = 5;
const MAX_RECENT_TRADES = 5;
const STAT_CARD_SKELETONS = [0, 1, 2, 3] as const;
const TABLE_SKELETON_LINES = [0, 1, 2] as const;
const CHART_COLORS = [
  "var(--color-primary)",
  "var(--color-primary-strong)",
  "var(--color-text-secondary)",
  "var(--color-text-muted)",
  "var(--color-border-muted)",
] as const;

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
          key={`table-skeleton-${line}`}
          className="skeleton-line-large"
        />
      ))}
    </div>
  );
}

function getHealthTone(value: string | number | null): string {
  if (typeof value === "number") {
    if (value >= 75) {
      return "dashboard-health-tone-positive";
    }

    if (value < 50) {
      return "dashboard-health-tone-negative";
    }

    return "";
  }

  if (value === "High" || value === "Needs Improvement") {
    return "dashboard-health-tone-negative";
  }

  if (value === "Low" || value === "Strong") {
    return "dashboard-health-tone-positive";
  }

  return "";
}

function formatTooltipCurrency(value: unknown): string {
  if (Array.isArray(value)) {
    return formatCurrency(parseDecimal(value[0]));
  }

  if (typeof value === "string" || typeof value === "number" || value == null) {
    return formatCurrency(parseDecimal(value));
  }

  return formatCurrency(0);
}

export function DashboardPage() {
  const { startLoading, stopLoading } = useLoading();
  const isMountedRef = useRef(true);

  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [isSummaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState("");

  const [trades, setTrades] = useState<TradeResponse[]>([]);
  const [isTradesLoading, setTradesLoading] = useState(false);
  const [tradesError, setTradesError] = useState("");

  const [analysis, setAnalysis] =
    useState<PortfolioAnalysisResponse | null>(null);
  const [isAnalysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState("");

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

  const loadTrades = useCallback(async (): Promise<void> => {
    if (!isMountedRef.current) {
      return;
    }

    setTradesLoading(true);
    setTradesError("");
    startLoading();

    try {
      const response = await getTrades();

      if (isMountedRef.current) {
        setTrades(response);
      }
    } catch (error) {
      if (isMountedRef.current) {
        setTradesError(getApiErrorMessage(error));
      }
    } finally {
      if (isMountedRef.current) {
        setTradesLoading(false);
      }

      stopLoading();
    }
  }, [startLoading, stopLoading]);

  const loadAnalysis = useCallback(async (): Promise<void> => {
    if (!isMountedRef.current) {
      return;
    }

    setAnalysisLoading(true);
    setAnalysisError("");
    startLoading();

    try {
      const response = await getPortfolioAnalysis();

      if (isMountedRef.current) {
        setAnalysis(response);
      }
    } catch (error) {
      if (isMountedRef.current) {
        setAnalysisError(getApiErrorMessage(error));
      }
    } finally {
      if (isMountedRef.current) {
        setAnalysisLoading(false);
      }

      stopLoading();
    }
  }, [startLoading, stopLoading]);

  const handleSummaryRetry = useCallback(() => {
    void loadSummary();
  }, [loadSummary]);

  const handleTradesRetry = useCallback(() => {
    void loadTrades();
  }, [loadTrades]);

  const handleAnalysisRetry = useCallback(() => {
    void loadAnalysis();
  }, [loadAnalysis]);

  useEffect(() => {
    isMountedRef.current = true;

    void loadSummary();
    void loadTrades();
    void loadAnalysis();

    return () => {
      isMountedRef.current = false;
    };
  }, [loadSummary, loadTrades, loadAnalysis]);

  const holdings = summary?.holdings ?? [];

  const largestHoldings = useMemo(
    () =>
      holdings
        .map((holding) => ({
          holding,
          investedAmount: parseDecimal(holding.invested_amount),
        }))
        .sort((left, right) => right.investedAmount - left.investedAmount)
        .slice(0, MAX_HOLDINGS_PREVIEW)
        .map((item) => item.holding),
    [holdings]
  );

  const recentTrades = useMemo(() => trades.slice(0, MAX_RECENT_TRADES), [trades]);

  const valueSeries = useMemo(() => buildPortfolioValueSeries(trades), [trades]);
  const allocationSeries = useMemo(() => buildAllocationSeries(holdings), [holdings]);
  const portfolioHealth = useMemo(() => buildPortfolioHealth(analysis), [analysis]);
  const dailyBrief = useMemo(() => buildDailyBrief(analysis), [analysis]);

  const totalInvested = parseDecimal(summary?.total_invested);
  const currentPortfolioValue = totalInvested;
  const unrealizedGainLoss = currentPortfolioValue - totalInvested;
  const unrealizedTone: StatCardTone =
    unrealizedGainLoss > 0
      ? "positive"
      : unrealizedGainLoss < 0
        ? "negative"
        : "default";

  return (
    <PageContainer
      title="Dashboard"
      description="Track portfolio health, allocation, and AI-guided decisions."
    >
      <div className="dashboard-premium">
        <div className="stats-grid" aria-busy={isSummaryLoading}>
          {isSummaryLoading ?
            STAT_CARD_SKELETONS.map((item) => (
              <article className="stat-card stat-card-skeleton" key={item}>
                <SkeletonBlock className="skeleton-line-short" />
                <SkeletonBlock className="skeleton-line-large" />
              </article>
            ))
          : summaryError ? (
            <section className="dashboard-section section-card-span-all">
              <SectionErrorState
                message={summaryError}
                retryLabel="Retry Portfolio Summary"
                onRetry={handleSummaryRetry}
              />
            </section>
          ) : (
            <>
              <StatCard label="Total Invested" value={formatCurrency(totalInvested)} />
              <StatCard
                label="Current Value"
                value={formatCurrency(currentPortfolioValue)}
              />
              <StatCard
                label="Unrealized Gain / Loss"
                value={formatSignedCurrency(unrealizedGainLoss)}
                tone={unrealizedTone}
              />
              <StatCard label="Holdings Count" value={String(holdings.length)} />
            </>
          )}
        </div>

        <div className="dashboard-premium-grid dashboard-premium-grid--equal">
          <section className="dashboard-section" aria-busy={isAnalysisLoading}>
            <header className="dashboard-section-header">
              <h2 className="dashboard-section-title">Portfolio Health</h2>
            </header>

            {isAnalysisLoading && !analysis ? (
              <TableSkeleton />
            ) : analysisError && !analysis ? (
              <SectionErrorState
                message={analysisError}
                retryLabel="Retry Health Analysis"
                onRetry={handleAnalysisRetry}
              />
            ) : (
              <div className="dashboard-health-grid">
                <article className="dashboard-health-stat">
                  <p className="dashboard-health-label">Health Score</p>
                  <p
                    className={`dashboard-health-value ${getHealthTone(portfolioHealth.score)}`.trim()}
                  >
                    {portfolioHealth.score === null ? "Unavailable" : `${portfolioHealth.score}/100`}
                  </p>
                </article>
                <article className="dashboard-health-stat">
                  <p className="dashboard-health-label">Risk Level</p>
                  <p
                    className={`dashboard-health-value ${getHealthTone(portfolioHealth.riskLevel)}`.trim()}
                  >
                    {portfolioHealth.riskLevel}
                  </p>
                </article>
                <article className="dashboard-health-stat">
                  <p className="dashboard-health-label">Diversification Level</p>
                  <p
                    className={`dashboard-health-value ${getHealthTone(portfolioHealth.diversificationLevel)}`.trim()}
                  >
                    {portfolioHealth.diversificationLevel}
                  </p>
                </article>
              </div>
            )}
          </section>

          <section className="dashboard-section dashboard-section--highlight" aria-busy={isAnalysisLoading}>
            <header className="dashboard-section-header">
              <h2 className="dashboard-section-title">AI Daily Brief</h2>
              <button
                type="button"
                className="button-secondary"
                onClick={handleAnalysisRetry}
                disabled={isAnalysisLoading}
              >
                {isAnalysisLoading ? "Refreshing..." : "Refresh"}
              </button>
            </header>

            {isAnalysisLoading && !analysis ? (
              <div className="insight-skeleton" aria-hidden="true">
                <SkeletonBlock className="skeleton-line-large" />
                <SkeletonBlock className="skeleton-line-large" />
                <SkeletonBlock className="skeleton-line-medium" />
              </div>
            ) : analysis ? (
              <>
                {analysisError ? (
                  <p className="feedback error" role="status">
                    {analysisError}
                  </p>
                ) : null}
                {dailyBrief.length > 0 ? (
                  <ul className="dashboard-brief-list">
                    {dailyBrief.map((point) => (
                      <li key={point}>{point}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="dashboard-empty">Analysis is available, but no concise highlights were returned.</p>
                )}
              </>
            ) : analysisError ? (
              <SectionErrorState
                message={analysisError}
                retryLabel="Retry AI Analysis"
                onRetry={handleAnalysisRetry}
              />
            ) : (
              <p className="dashboard-empty">
                No analysis available yet. Refresh to generate portfolio insights.
              </p>
            )}
          </section>
        </div>

        <div className="dashboard-premium-grid">
          <section className="dashboard-section" aria-busy={isTradesLoading}>
            <header className="dashboard-section-header">
              <div>
                <h2 className="dashboard-section-title">Portfolio Value Over Time</h2>
                <p className="dashboard-section-description">
                  Based on cumulative trade values. Ready to switch to historical endpoints.
                </p>
              </div>
            </header>

            {isTradesLoading && valueSeries.length === 0 ? (
              <TableSkeleton />
            ) : tradesError && valueSeries.length === 0 ? (
              <SectionErrorState
                message={tradesError}
                retryLabel="Retry Value Timeline"
                onRetry={handleTradesRetry}
              />
            ) : valueSeries.length === 0 ? (
              <p className="dashboard-empty">Not enough trade data to render a timeline.</p>
            ) : (
              <div className="dashboard-chart-wrap" role="img" aria-label="Portfolio value over time line chart">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={valueSeries} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
                    <XAxis dataKey="label" tick={{ fill: "var(--color-text-muted)", fontSize: 12 }} interval="preserveStartEnd" />
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
                    <Line
                      type="monotone"
                      dataKey="investedValue"
                      stroke="var(--color-primary)"
                      strokeWidth={2.5}
                      dot={false}
                      activeDot={{ r: 4 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </section>

          <section className="dashboard-section" aria-busy={isSummaryLoading}>
            <header className="dashboard-section-header">
              <h2 className="dashboard-section-title">Asset Allocation</h2>
            </header>

            {isSummaryLoading && allocationSeries.length === 0 ? (
              <TableSkeleton />
            ) : summaryError && allocationSeries.length === 0 ? (
              <SectionErrorState
                message={summaryError}
                retryLabel="Retry Allocation"
                onRetry={handleSummaryRetry}
              />
            ) : allocationSeries.length === 0 ? (
              <p className="dashboard-empty">No holdings available for allocation breakdown.</p>
            ) : (
              <>
                <div className="dashboard-donut-wrap" role="img" aria-label="Asset allocation donut chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={allocationSeries}
                        dataKey="value"
                        nameKey="name"
                        innerRadius="60%"
                        outerRadius="82%"
                        paddingAngle={2}
                      >
                        {allocationSeries.map((_, index) => (
                          <Cell key={`allocation-cell-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />
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

                <ul className="dashboard-legend">
                  {allocationSeries.slice(0, 5).map((item, index) => (
                    <li key={item.name} className="dashboard-legend-item">
                      <span className="dashboard-legend-name">
                        <span
                          className="dashboard-legend-dot"
                          style={{ background: CHART_COLORS[index % CHART_COLORS.length] }}
                          aria-hidden="true"
                        />
                        {item.name}
                      </span>
                      <span>{formatNumber(item.percentage)}%</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
        </div>

        <div className="dashboard-premium-grid dashboard-premium-grid--equal">
          <section className="dashboard-section" aria-busy={isTradesLoading}>
            <header className="dashboard-section-header">
              <h2 className="dashboard-section-title">Recent Trades</h2>
            </header>

            {isTradesLoading ? (
              <TableSkeleton />
            ) : tradesError ? (
              <SectionErrorState
                message={tradesError}
                retryLabel="Retry Recent Trades"
                onRetry={handleTradesRetry}
              />
            ) : recentTrades.length === 0 ? (
              <p className="dashboard-empty">No recent trades yet.</p>
            ) : (
              <div className="table-wrap">
                <table className="trades-table dashboard-table">
                  <caption className="sr-only">Most recent portfolio trades</caption>
                  <thead>
                    <tr>
                      <th scope="col">Symbol</th>
                      <th scope="col">Type</th>
                      <th scope="col">Quantity</th>
                      <th scope="col">Price</th>
                      <th scope="col">Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentTrades.map((trade) => (
                      <tr key={trade.id}>
                        <td>{trade.asset_symbol}</td>
                        <td>
                          <span
                            className={`dashboard-trade-type ${trade.transaction_type === "BUY" ? "dashboard-trade-type--buy" : "dashboard-trade-type--sell"}`}
                          >
                            {trade.transaction_type}
                          </span>
                        </td>
                        <td>{formatNumber(trade.quantity)}</td>
                        <td>{formatCurrency(parseDecimal(trade.price_per_unit))}</td>
                        <td>{formatDateTime(trade.trade_timestamp)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="dashboard-section" aria-busy={isSummaryLoading}>
            <header className="dashboard-section-header">
              <h2 className="dashboard-section-title">Holdings Preview</h2>
            </header>

            {isSummaryLoading ? (
              <TableSkeleton />
            ) : summaryError ? (
              <SectionErrorState
                message={summaryError}
                retryLabel="Retry Holdings"
                onRetry={handleSummaryRetry}
              />
            ) : largestHoldings.length === 0 ? (
              <p className="dashboard-empty">No holdings found yet.</p>
            ) : (
              <div className="table-wrap">
                <table className="trades-table dashboard-table">
                  <caption className="sr-only">Largest holdings preview</caption>
                  <thead>
                    <tr>
                      <th scope="col">Symbol</th>
                      <th scope="col">Quantity</th>
                      <th scope="col">Avg Buy Price</th>
                      <th scope="col">Invested Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {largestHoldings.map((holding) => (
                      <tr key={holding.symbol}>
                        <td>{holding.symbol}</td>
                        <td>{formatNumber(holding.quantity)}</td>
                        <td>{formatCurrency(parseDecimal(holding.average_buy_price))}</td>
                        <td>{formatCurrency(parseDecimal(holding.invested_amount))}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      </div>
    </PageContainer>
  );
}

