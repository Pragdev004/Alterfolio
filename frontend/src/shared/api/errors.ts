/** The three failure kinds the UI tells apart (spec 013 section 7), plus the server's own `code` and `message` when it sent them. */
export type ErrorKind = "network" | "client" | "server";

export class ApiError extends Error {
  constructor(
    readonly kind: ErrorKind,
    readonly status: number | null,
    readonly code: string | null,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface ErrorCopy {
  title: string;
  body: string;
  retry: boolean;
}

/** Known server codes in plain language. Unknown codes fall back to the server's message, shown with its code. */
const KNOWN: Record<string, ErrorCopy> = {
  as_of_not_sealed: { title: "Data for that date isn't final yet.", body: "Pick the latest final date instead.", retry: false },
  analysis_trip_not_found: { title: "That trip is not in your analysis.", body: "It may belong to a different date. Go back to the list.", retry: false },
  ledger_busy: { title: "Your ledger is busy.", body: "Another change is in progress. Try again in a moment.", retry: true },
  invalid_import_file: { title: "That file could not be read.", body: "Check that it is a Zerodha tradebook CSV.", retry: false },
  oversell: {
    title: "A sell has no earlier buy.",
    body: "Upload your oldest tradebook first, then the newer ones.",
    retry: false,
  },
};

export function errorCopy(error: unknown): ErrorCopy {
  if (!(error instanceof ApiError)) return { title: "Something went wrong.", body: "Try again. Your data is unchanged.", retry: true };
  if (error.kind === "network") {
    return { title: "Cannot reach the server.", body: "Check that the backend is running, then try again. Nothing was lost.", retry: true };
  }
  const known = error.code ? KNOWN[error.code] : undefined;
  if (known) return known;
  if (error.kind === "server") {
    return { title: "The server hit a problem.", body: `${error.message || "No details were sent."} Your data is unchanged.`, retry: true };
  }
  return { title: "The server could not do that.", body: error.message, retry: false };
}
