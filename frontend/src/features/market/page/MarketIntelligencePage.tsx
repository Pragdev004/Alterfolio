import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getApiErrorMessage } from "../../../shared/api/types";
import { useLoading } from "../../../shared/hooks/useLoading";
import { formatDateTime, formatNumber } from "../../../shared/lib/format";
import { SkeletonBlock } from "../../../shared/ui/feedback/SkeletonBlock";
import { PageContainer } from "../../../shared/ui/layout/PageContainer";
import { getMarketIntelligence } from "./marketIntelligenceService";
import { type MarketIntelligenceData, type MarketMover } from "./marketTypes";

import "./MarketIntelligencePage.css";

const SKELETON_LINES = [0, 1, 2] as const;

function getSentimentClass(sentiment: string): string {
  if (sentiment === "positive") {
    return "market-chip market-chip--positive";
  }

  if (sentiment === "negative") {
    return "market-chip market-chip--negative";
  }

  return "market-chip market-chip--neutral";
}

function formatSignedPercent(value: number): string {
  const absolute = `${formatNumber(Math.abs(value))}%`;

  if (value > 0) {
    return `+${absolute}`;
  }

  if (value < 0) {
    return `-${absolute}`;
  }

  return absolute;
}

function MoverList({
  title,
  items,
  tone,
}: {
  title: string;
  items: MarketMover[];
  tone: "up" | "down";
}) {
  return (
    <article>
      <h3 className="market-section-title">{title}</h3>
      {items.length === 0 ? (
        <p className="market-empty">No movers detected from available trade activity.</p>
      ) : (
        <ul className="market-mover-list">
          {items.map((item) => (
            <li key={`${title}-${item.instrumentId}`} className="market-mover-item">
              <p className="market-mover-symbol">{item.symbol}</p>
              <p className={`market-mover-change market-mover-change--${tone}`}>
                {formatSignedPercent(item.changePercent)}
              </p>
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

export function MarketIntelligencePage() {
  const { startLoading, stopLoading } = useLoading();
  const isMountedRef = useRef(true);

  const [data, setData] = useState<MarketIntelligenceData | null>(null);
  const [isLoading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const loadMarketIntelligence = useCallback(async (): Promise<void> => {
    if (!isMountedRef.current) {
      return;
    }

    setLoading(true);
    setErrorMessage("");
    startLoading();

    try {
      const response = await getMarketIntelligence();

      if (isMountedRef.current) {
        setData(response);
      }
    } catch (error) {
      if (isMountedRef.current) {
        setErrorMessage(getApiErrorMessage(error));
      }
    } finally {
      if (isMountedRef.current) {
        setLoading(false);
      }

      stopLoading();
    }
  }, [startLoading, stopLoading]);

  useEffect(() => {
    isMountedRef.current = true;
    void loadMarketIntelligence();

    return () => {
      isMountedRef.current = false;
    };
  }, [loadMarketIntelligence]);

  const sourceNote = useMemo(() => {
    if (!data) {
      return "";
    }

    return data.dataSource === "backend"
      ? "Live market feed connected"
      : "Derived from current portfolio + trade + analysis data";
  }, [data]);

  return (
    <PageContainer
      title="Market Intelligence"
      description="Track market signals, portfolio impact, and today’s key catalysts."
    >
      <div className="market-layout">
        <div className="market-section-header">
          <p className="market-source-note">{sourceNote}</p>
          <button
            type="button"
            className="button-secondary"
            onClick={() => {
              void loadMarketIntelligence();
            }}
            disabled={isLoading}
          >
            {isLoading ? "Refreshing..." : "Refresh"}
          </button>
        </div>

        {errorMessage ? (
          <section className="market-section" role="alert">
            <p className="feedback error">{errorMessage}</p>
          </section>
        ) : null}

        {isLoading && !data ? (
          <section className="market-section" aria-hidden="true">
            <div className="market-skeleton">
              {SKELETON_LINES.map((line) => (
                <SkeletonBlock key={`market-skeleton-${line}`} className="skeleton-line-large" />
              ))}
            </div>
          </section>
        ) : null}

        {!isLoading && data ? (
          <>
            <div className="market-grid">
              <section className="market-section">
                <header className="market-section-header">
                  <h2 className="market-section-title">Market News</h2>
                </header>

                {data.news.length === 0 ? (
                  <p className="market-empty">No market stories available for current holdings.</p>
                ) : (
                  <ul className="market-news-list">
                    {data.news.map((item) => (
                      <li key={item.id} className="market-news-item">
                        <h3 className="market-news-headline">{item.headline}</h3>
                        <p className="market-news-summary">{item.summary}</p>
                        <div className="market-news-meta">
                          <span>{item.source}</span>
                          <span>{formatDateTime(item.publishedAt)}</span>
                          <span className={getSentimentClass(item.sentiment)}>
                            {item.sentiment}
                          </span>
                          {item.relatedSymbols.length > 0 ? (
                            <span className="market-chip">
                              {item.relatedSymbols.join(", ")}
                            </span>
                          ) : null}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section className="market-section">
                <header className="market-section-header">
                  <h2 className="market-section-title">AI Summary</h2>
                </header>
                <p className="market-ai-summary">{data.aiSummary}</p>
              </section>
            </div>

            <div className="market-grid">
              <section className="market-section">
                <header className="market-section-header">
                  <h2 className="market-section-title">Portfolio Impact</h2>
                </header>

                {data.impact.length === 0 ? (
                  <p className="market-empty">No symbols were mentioned by today’s stories.</p>
                ) : (
                  <div className="table-wrap">
                    <table className="market-impact-table">
                      <caption className="sr-only">Holdings impacted by current market stories</caption>
                      <thead>
                        <tr>
                          <th scope="col">Symbol</th>
                          <th scope="col">Mentions</th>
                          <th scope="col">Latest Mention</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.impact.map((item) => (
                          <tr key={item.instrumentId}>
                            <td data-label="Symbol">{item.symbol}</td>
                            <td data-label="Mentions">{item.mentionCount}</td>
                            <td data-label="Latest Mention">{item.latestHeadline}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>

              <section className="market-section">
                <header className="market-section-header">
                  <h2 className="market-section-title">Earnings Calendar</h2>
                </header>

                {data.earnings.length === 0 ? (
                  <p className="market-empty">No upcoming earnings dates available.</p>
                ) : (
                  <ul className="market-earnings-list">
                    {data.earnings.map((event) => (
                      <li key={`earning-${event.instrumentId}`} className="market-earnings-item">
                        <p className="market-earnings-symbol">{event.symbol}</p>
                        <p className="market-earnings-date">{formatDateTime(event.earningsDate)}</p>
                        <p className="market-earnings-note">{event.confidenceNote}</p>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>

            <section className="market-section">
              <header className="market-section-header">
                <h2 className="market-section-title">Market Movers</h2>
              </header>

              <div className="market-movers-grid">
                <MoverList title="Biggest Gainers" items={data.movers.gainers} tone="up" />
                <MoverList title="Biggest Losers" items={data.movers.losers} tone="down" />
              </div>
            </section>
          </>
        ) : null}
      </div>
    </PageContainer>
  );
}
