// Responses recorded from the real 013a API (backend/scripts/record_fixtures.py), typed by the generated OpenAPI schema.
import type { MetaOut, RegimesOut, TripDetailOut, TripsOut } from "../shared/api/types";
import errors from "./fixtures/errors.json";
import emptyMeta from "./fixtures/empty/meta.json";
import emptyRegimes from "./fixtures/empty/regimes.json";
import emptyTrades from "./fixtures/empty/trades.json";
import emptyTrips from "./fixtures/empty/trips.json";
import excludedMeta from "./fixtures/excluded/meta.json";
import excludedRegimes from "./fixtures/excluded/regimes.json";
import excludedTrip from "./fixtures/excluded/trip.json";
import excludedTrips from "./fixtures/excluded/trips.json";
import fewMeta from "./fixtures/few/meta.json";
import fewRegimes from "./fixtures/few/regimes.json";
import fewTrip from "./fixtures/few/trip.json";
import fewTrips from "./fixtures/few/trips.json";
import fullMeta from "./fixtures/full/meta.json";
import fullRegimes from "./fixtures/full/regimes.json";
import fullTrip from "./fixtures/full/trip.json";
import fullTrips from "./fixtures/full/trips.json";
import openMeta from "./fixtures/open/meta.json";
import openRegimes from "./fixtures/open/regimes.json";
import openTrades from "./fixtures/open/trades.json";
import openTrips from "./fixtures/open/trips.json";

export type ScenarioName = "full" | "few" | "excluded" | "open" | "empty";

export interface Scenario {
  meta: MetaOut;
  trips: TripsOut;
  regimes: RegimesOut;
  trip?: TripDetailOut;
  trades: Record<string, unknown>[];
}

export const scenarios: Record<ScenarioName, Scenario> = {
  full: { meta: fullMeta as MetaOut, trips: fullTrips as TripsOut, regimes: fullRegimes as RegimesOut, trip: fullTrip as TripDetailOut, trades: [{}] },
  few: { meta: fewMeta as MetaOut, trips: fewTrips as TripsOut, regimes: fewRegimes as RegimesOut, trip: fewTrip as TripDetailOut, trades: [{}] },
  excluded: { meta: excludedMeta as MetaOut, trips: excludedTrips as TripsOut, regimes: excludedRegimes as RegimesOut, trip: excludedTrip as TripDetailOut, trades: [{}] },
  open: { meta: openMeta as MetaOut, trips: openTrips as TripsOut, regimes: openRegimes as RegimesOut, trades: openTrades },
  empty: { meta: emptyMeta as MetaOut, trips: emptyTrips as TripsOut, regimes: emptyRegimes as RegimesOut, trades: emptyTrades },
};

export const recordedErrors = errors as { not_sealed: { status: number; body: Record<string, unknown> }; trip_not_found: { status: number; body: Record<string, unknown> } };
