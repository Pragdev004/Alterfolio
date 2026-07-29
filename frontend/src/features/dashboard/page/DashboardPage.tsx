import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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

const MAX_HOLDINGS_PREVIEW = 5;
const MAX_RECENT_TRADES = 5;
const STAT_CARD_SKELETONS = [0, 1, 2, 3] as const;
const TABLE_SKELETON_LINES = [0, 1, 2] as const;

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

  const recentTrades = useMemo(
    () => trades.slice(0, MAX_RECENT_TRADES),
    [trades]
  );

  const totalInvested = parseDecimal(summary?.total_invested);
  const currentPortfolioValue = totalInvested;
  const unrealizedGainLoss = currentPortfolioValue - totalInvested;
  const unrealizedTone: StatCardTone =
    unrealizedGainLoss > 0
      ? "positive"
      : unrealizedGainLoss < 0
        ? "negative"
        : "default";

  const topRecommendation =
    analysis?.analysis.recommendations[0] ?? "No recommendation available yet.";

  return (
    <PageContainer
      title="Dashboard"
      description="Track portfolio health, recent activity, and AI insights."
    >
      <div className="stats-grid" aria-busy={isSummaryLoading}>
        {isSummaryLoading ?
          STAT_CARD_SKELETONS.map((item) => (
            <article className="stat-card stat-card-skeleton" key={item}>
              <SkeletonBlock className="skeleton-line-short" />
              <SkeletonBlock className="skeleton-line-large" />
            </article>
          ))
        : summaryError ? (
          <section className="section-card section-card-span-all">
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
              label="Current Portfolio Value"
              value={formatCurrency(currentPortfolioValue)}
            />
            <StatCard
              label="Unrealized Gain / Loss"
              value={formatSignedCurrency(unrealizedGainLoss)}
              tone={unrealizedTone}
            />
            <StatCard label="Number of Holdings" value={String(holdings.length)} />
          </>
        )}
      </div>

      <div className="dashboard-grid">
        <section className="section-card" aria-busy={isSummaryLoading}>
          <header className="section-header">
            <h2 className="section-title">Holdings Preview</h2>
          </header>

          {isSummaryLoading ? (
            <TableSkeleton />
          ) : summaryError ? (
            <SectionErrorState
              message={summaryError}
              retryLabel="Retry"
              onRetry={handleSummaryRetry}
            />
          ) : largestHoldings.length === 0 ? (
            <p className="empty-state">No holdings found yet.</p>
          ) : (
            <div className="table-wrap">
              <table className="trades-table">
                <caption className="sr-only">Largest holdings preview</caption>
                <thead>
                  <tr>
                    <th scope="col">Symbol</th>
                    <th scope="col">Quantity</th>
                    <th scope="col">Average Buy Price</th>
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

        <section className="section-card" aria-busy={isTradesLoading}>
          <header className="section-header">
            <h2 className="section-title">Recent Trades</h2>
          </header>

          {isTradesLoading ? (
            <TableSkeleton />
          ) : tradesError ? (
            <SectionErrorState
              message={tradesError}
              retryLabel="Retry"
              onRetry={handleTradesRetry}
            />
          ) : recentTrades.length === 0 ? (
            <p className="empty-state">No recent trades yet.</p>
          ) : (
            <div className="table-wrap">
              <table className="trades-table">
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
                      <td>{trade.transaction_type}</td>
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
      </div>

      <section className="section-card insight-card" aria-busy={isAnalysisLoading}>
        <header className="section-header">
          <h2 className="section-title">AI Insights</h2>
          <button
            type="button"
            className="button-secondary"
            onClick={handleAnalysisRetry}
            disabled={isAnalysisLoading}
          >
            {isAnalysisLoading ? "Refreshing..." : "Refresh Analysis"}
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

            <div className="insight-grid">
              <article>
                <p className="insight-label">Overview</p>
                <p className="insight-text">{analysis.analysis.overview}</p>
              </article>
              <article>
                <p className="insight-label">Risk Summary</p>
                <p className="insight-text">{analysis.analysis.risk_assessment}</p>
              </article>
              <article>
                <p className="insight-label">Top Recommendation</p>
                <p className="insight-text">{topRecommendation}</p>
              </article>
            </div>
          </>
        ) : analysisError ? (
          <SectionErrorState
            message={analysisError}
            retryLabel="Retry AI Analysis"
            onRetry={handleAnalysisRetry}
          />
        ) : (
          <p className="empty-state">
            No analysis available yet. Refresh to generate portfolio insights.
          </p>
        )}
      </section>
    </PageContainer>
  );
}
