import type { TripRow, TripsOut } from "../../shared/api/types";

export type TripStatus = "EVALUATED" | "NOT EVALUATED" | "LISTING EXCLUDED";

/** Status code of a trip row. A trip on an excluded listing keeps its row and says why; gated trips stay in the list. */
export function tripStatus(trip: TripRow, excluded: TripsOut["excluded_listings"]): TripStatus {
  if (trip.evaluated) return "EVALUATED";
  const listed = excluded.some((e) => e.symbol === trip.symbol && e.exchange === trip.exchange);
  return listed ? "LISTING EXCLUDED" : "NOT EVALUATED";
}

/** The sentence hung in the note column, only for a trip that was not compared (per-baseline reasons live on the trip page). */
export function tripNote(trip: TripRow, excluded: TripsOut["excluded_listings"]): string | null {
  if (trip.evaluated) return null;
  if (trip.reason_text) return trip.reason_text;
  const listing = excluded.find((e) => e.symbol === trip.symbol && e.exchange === trip.exchange);
  return listing?.reason_text ?? trip.alt?.reason_text ?? null;
}
