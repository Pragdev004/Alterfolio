import { Link } from "react-router-dom";

import { useImportStatus } from "../api/queries";

/** Rejected rows are never silent: while any import row was rejected, the figures on this screen may be wrong. */
export function RejectedRowsWarning() {
  const status = useImportStatus();
  const warning = status.data?.warning;
  if (!warning) return null;
  return (
    <p className="warn" role="alert">
      <strong>{warning}.</strong> <Link to={{ pathname: "/upload", hash: "previous" }}>See the upload results</Link>
    </p>
  );
}

const CLOCK = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" });

/** The last good fetch as HH:MM India time. A time of day, not a figure. */
export const clockTime = (at: number) => CLOCK.format(new Date(at));

/** A refresh failed but the last good figures are still on screen: say so instead of blanking or alarming. */
export function RefreshFailed({ at, onRetry }: { at: number; onRetry?: () => void }) {
  return (
    <p className="warn" role="status">
      Couldn&apos;t refresh. Showing figures from {clockTime(at)}.{" "}
      {onRetry && <button type="button" className="btn-link" onClick={onRetry}>Try again</button>}
    </p>
  );
}
