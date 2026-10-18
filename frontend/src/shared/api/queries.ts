import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getJson, postFile, postJson } from "./client";
import { ApiError } from "./errors";
import type { AskOut, BiasesOut, HoldingOut, ImportResult, ImportStatus, MetaOut, RegimesOut, SummaryOut, TradeOut, TripDetailOut, TripsOut } from "./types";

// The backend caches per ledger version and a sealed day never changes, so results stay fresh for a long time.
const STALE = 30 * 60 * 1000;

/** Default for the QueryClient: a 4xx is final, anything else gets one more try. */
export const retryOnce = (count: number, error: unknown) => !(error instanceof ApiError && error.kind === "client") && count < 1;

export const useMeta = () =>
  useQuery({ queryKey: ["analysis", "meta"], queryFn: ({ signal }) => getJson<MetaOut>("/api/analysis/meta", {}, signal), staleTime: STALE });

/** `asOf` null = the server's latest sealed day. One query key per (endpoint, as_of). */
export const useTrips = (asOf: string | null) =>
  useQuery({
    queryKey: ["analysis", "trips", asOf],
    queryFn: ({ signal }) => getJson<TripsOut>("/api/analysis/trips", { as_of: asOf }, signal),
    staleTime: STALE,
  });

export const useTripDetail = (tripId: string, asOf: string | null) =>
  useQuery({
    queryKey: ["analysis", "trip", tripId, asOf],
    queryFn: ({ signal }) => getJson<TripDetailOut>(`/api/analysis/trips/${encodeURIComponent(tripId)}`, { as_of: asOf }, signal),
    staleTime: STALE,
  });

/** Used only to tell "no trades yet" from "no closed trips yet" on an empty trip list. */
export const useTrades = (enabled: boolean) =>
  useQuery({ queryKey: ["trades"], queryFn: ({ signal }) => getJson<TradeOut[]>("/trades", {}, signal), enabled, staleTime: STALE });

export const useRegimes = (asOf: string | null) =>
  useQuery({
    queryKey: ["analysis", "regimes", asOf],
    queryFn: ({ signal }) => getJson<RegimesOut>("/api/analysis/regimes", { as_of: asOf }, signal),
    staleTime: STALE,
  });

export const useBiases = (asOf: string | null) =>
  useQuery({
    queryKey: ["analysis", "biases", asOf],
    queryFn: ({ signal }) => getJson<BiasesOut>("/api/analysis/biases", { as_of: asOf }, signal),
    staleTime: STALE,
  });

// Holdings are current, not as-of, and prices move: keep them fresh for a minute only.
export const useSummary = () =>
  useQuery({ queryKey: ["portfolio", "summary"], queryFn: ({ signal }) => getJson<SummaryOut>("/portfolio/summary", {}, signal), staleTime: 60_000 });

export const useHoldings = () =>
  useQuery({ queryKey: ["portfolio", "holdings"], queryFn: ({ signal }) => getJson<HoldingOut[]>("/portfolio/holdings", {}, signal), staleTime: 60_000 });

/** Past uploads and how many rows were rejected: Holdings and Trips warn from this. */
export const useImportStatus = () =>
  useQuery({ queryKey: ["imports", "status"], queryFn: ({ signal }) => getJson<ImportStatus>("/imports/status", {}, signal), staleTime: 60_000 });

/** An import changes the ledger, so everything derived from it is refetched. */
export function useImportTradebook() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => postFile<ImportResult>("/imports/tradebook", file),
    onSuccess: () => Promise.all([client.invalidateQueries({ queryKey: ["analysis"] }), client.invalidateQueries({ queryKey: ["portfolio"] }), client.invalidateQueries({ queryKey: ["trades"] }), client.invalidateQueries({ queryKey: ["imports"] })]),
  });
}

export const ASK_TIMEOUT_MS = 60_000;

export const useAsk = () =>
  useMutation({ mutationFn: (body: { question: string; as_of: string }) => postJson<AskOut>("/api/analyst/ask", body, AbortSignal.timeout(ASK_TIMEOUT_MS)) });
