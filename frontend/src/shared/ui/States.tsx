import type { ReactNode } from "react";

import { ApiError, errorCopy } from "../api/errors";

/** Loading is always labelled and keeps the real column grid: hatch rows at 40% alpha, never a bare spinner. */
export function Skeleton({ label = "Fetching market data and computing", rows = 6 }: { label?: string; rows?: number }) {
  return (
    <div className="skeleton" role="status" aria-live="polite">
      <p className="label">{label}…</p>
      {Array.from({ length: rows }, (_, i) => <div key={i} className="row" aria-hidden="true" />)}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state">
      <h2>{title}</h2>
      {children}
    </div>
  );
}

/** Offline, 4xx (server code and message in plain language) and 5xx are distinct; one failed section never blanks another. */
export function ErrorState({ error, onRetry, children }: { error: unknown; onRetry?: () => void; children?: ReactNode }) {
  const copy = errorCopy(error);
  const code = error instanceof ApiError && error.code ? error.code : null;
  return (
    <div className="state" role="alert">
      <h2>{copy.title}</h2>
      <p>{copy.body}</p>
      {error instanceof ApiError && error.kind === "client" && error.message && <p className="reason">Server said: {error.message}</p>}
      {code && <p className="reason">Server code: {code}</p>}
      {copy.retry && onRetry && <button type="button" className="btn" onClick={onRetry}>Try again</button>}
      {children}
    </div>
  );
}

/** 422 as_of_not_sealed. */
export function NotFinal({ onUseLatest, latestDisplay }: { onUseLatest: () => void; latestDisplay: string | null }) {
  return (
    <div className="state" role="alert">
      <h2>Data for that date isn&apos;t final yet.</h2>
      <p>Only days that have fully ended can be analysed.</p>
      <button type="button" className="btn" onClick={onUseLatest}>{latestDisplay ? `Use the latest final date, ${latestDisplay}` : "Use the latest final date"}</button>
    </div>
  );
}

/** The analyst is optional: when it fails, everything else stays interactive (spec 013 D4). */
export function AnalystOffline() {
  return <p className="offline" role="status">Analyst offline — your numbers are still here.</p>;
}
