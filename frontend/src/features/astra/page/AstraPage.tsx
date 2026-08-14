import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getPortfolioSummary } from "../../../shared/api/alterfolioApi";
import { type PortfolioSummary, getApiErrorMessage } from "../../../shared/api/types";
import { useLoading } from "../../../shared/hooks/useLoading";
import { formatCurrency, formatDateTime, parseDecimal } from "../../../shared/lib/format";
import { SkeletonBlock } from "../../../shared/ui/feedback/SkeletonBlock";
import { PageContainer } from "../../../shared/ui/layout/PageContainer";
import { astraAdapter } from "./astraAdapter";
import { MarkdownContent } from "./MarkdownContent";
import { type CopilotMessage } from "./astraTypes";

import "./AstraPage.css";

const PROMPT_SUGGESTIONS = [
  "Review my portfolio",
  "Explain my portfolio risk",
  "How can I diversify?",
  "Summarise AI recommendations",
] as const;

function createMessage(role: CopilotMessage["role"], content: string): CopilotMessage {
  return {
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    role,
    content,
    timestamp: new Date().toISOString(),
  };
}

export function AstraPage() {
  const { startLoading, stopLoading } = useLoading();

  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [summaryError, setSummaryError] = useState("");
  const [isSummaryLoading, setSummaryLoading] = useState(false);

  const [inputValue, setInputValue] = useState("");
  const [messages, setMessages] = useState<CopilotMessage[]>([]);
  const [isSending, setSending] = useState(false);

  const conversationViewportRef = useRef<HTMLDivElement | null>(null);
  const isMountedRef = useRef(true);

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

  useEffect(() => {
    const viewport = conversationViewportRef.current;
    if (!viewport) {
      return;
    }

    viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const portfolioValue = useMemo(
    () =>
      summary?.total_market_value == null
        ? null
        : parseDecimal(summary.total_market_value),
    [summary?.total_market_value]
  );

  const largestPosition = useMemo(() => {
    if (summary?.valuation_status !== "COMPLETE") {
      return null;
    }

    const holdings = summary.holdings;

    if (holdings.length === 0) {
      return null;
    }

    return holdings
      .map((holding) => ({
        symbol: holding.symbol,
        exchange: holding.exchange,
        value:
          holding.market_value == null
            ? null
            : parseDecimal(holding.market_value),
      }))
      .filter(
        (holding): holding is { symbol: string; exchange: string | null; value: number } =>
          holding.value != null
      )
      .sort((left, right) => right.value - left.value)[0] ?? null;
  }, [summary]);

  const submitPrompt = useCallback(
    async (prompt: string) => {
      const trimmedPrompt = prompt.trim();

      if (!trimmedPrompt || isSending) {
        return;
      }

      const userMessage = createMessage("user", trimmedPrompt);
      setMessages((previous) => [...previous, userMessage]);
      setSending(true);
      startLoading();

      try {
        const response = await astraAdapter.respond({
          prompt: trimmedPrompt,
          summary,
        });

        if (isMountedRef.current) {
          setMessages((previous) => [
            ...previous,
            createMessage("assistant", response),
          ]);
        }
      } catch (error) {
        if (isMountedRef.current) {
          const fallback = getApiErrorMessage(error);
          setMessages((previous) => [
            ...previous,
            createMessage(
              "system",
              `Astra could not process this request right now.\n- Reason: ${fallback}`
            ),
          ]);
        }
      } finally {
        if (isMountedRef.current) {
          setSending(false);
          setInputValue("");
        }

        stopLoading();
      }
    },
    [isSending, startLoading, stopLoading, summary]
  );

  const hasMessages = messages.length > 0;

  return (
    <PageContainer
      title="Astra"
      description="AI Investment Assistant"
    >
      <div className="astra-layout">
        <section className="astra-conversation-card" aria-live="polite">
          <header className="astra-section-header">
            <h2 className="astra-section-title">Conversation</h2>
          </header>

          <div className="astra-conversation-viewport" ref={conversationViewportRef}>
            {!hasMessages ? (
              <div className="astra-empty-state">
                <div className="astra-empty-icon" aria-hidden="true" />
                <p className="astra-empty-title">Start a conversation with Astra</p>
                <p className="astra-empty-description">
                  Ask about risk, diversification, or recommendations using the quick prompts.
                </p>
              </div>
            ) : (
              <ul className="astra-message-list">
                {messages.map((message) => (
                  <li
                    key={message.id}
                    className={`astra-message astra-message--${message.role}`}
                  >
                    <div className="astra-message-bubble">
                      <MarkdownContent content={message.content} />
                    </div>
                    <p className="astra-message-time">{formatDateTime(message.timestamp)}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <form
            className="astra-input-row"
            onSubmit={(event) => {
              event.preventDefault();
              void submitPrompt(inputValue);
            }}
          >
            <label htmlFor="astra-prompt" className="sr-only">
              Ask Astra
            </label>
            <input
              id="astra-prompt"
              name="astra-prompt"
              value={inputValue}
              onChange={(event) => setInputValue(event.target.value)}
              className="astra-input"
              placeholder="Ask Astra about your portfolio..."
              autoComplete="off"
            />
            <button
              type="submit"
              className="button-primary astra-send-button"
              disabled={isSending || inputValue.trim().length === 0}
            >
              {isSending ? "Sending..." : "Send"}
            </button>
          </form>

          <div className="astra-suggestions" role="group" aria-label="Prompt suggestions">
            {PROMPT_SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                className="button-secondary astra-suggestion-button"
                onClick={() => {
                  void submitPrompt(suggestion);
                }}
                disabled={isSending}
              >
                {suggestion}
              </button>
            ))}
          </div>
        </section>

        <aside className="astra-context-card" aria-busy={isSummaryLoading}>
          <header className="astra-section-header">
            <h2 className="astra-section-title">Portfolio Context</h2>
            <button
              type="button"
              className="button-secondary"
              onClick={() => {
                void loadSummary();
              }}
              disabled={isSummaryLoading}
            >
              {isSummaryLoading ? "Refreshing..." : "Refresh"}
            </button>
          </header>

          {isSummaryLoading ? (
            <div className="astra-context-skeleton" aria-hidden="true">
              <SkeletonBlock className="skeleton-line-large" />
              <SkeletonBlock className="skeleton-line-large" />
              <SkeletonBlock className="skeleton-line-medium" />
            </div>
          ) : summaryError ? (
            <p className="feedback error" role="status">
              {summaryError}
            </p>
          ) : (
            <dl className="astra-context-list">
              <div className="astra-context-item">
                <dt>Portfolio Value</dt>
                <dd>{portfolioValue == null ? "Unavailable" : formatCurrency(portfolioValue)}</dd>
              </div>
              <div className="astra-context-item">
                <dt>Holdings Count</dt>
                <dd>{summary?.holdings.length ?? 0}</dd>
              </div>
              {summary?.valuation_status === "COMPLETE" ? (
                <div className="astra-context-item">
                  <dt>Largest Position</dt>
                  <dd>
                    {largestPosition ?
                      `${largestPosition.exchange ? `${largestPosition.symbol} · ${largestPosition.exchange}` : largestPosition.symbol} (${formatCurrency(largestPosition.value)})`
                    : "Unavailable"}
                  </dd>
                </div>
              ) : null}
            </dl>
          )}
        </aside>
      </div>
    </PageContainer>
  );
}
