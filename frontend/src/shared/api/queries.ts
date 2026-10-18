import { useQuery } from "@tanstack/react-query";

import { getJson } from "./client";
import { ApiError } from "./errors";
import type { MetaOut, RegimesOut, TradeOut, TripDetailOut, TripsOut } from "./types";

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
