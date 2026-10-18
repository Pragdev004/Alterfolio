// Responses recorded from the real 013a API (backend/scripts/record_fixtures.py), typed by the generated OpenAPI schema.
import type { BiasesOut, HoldingOut, ImportStatus, MetaOut, RegimesOut, SummaryOut, TripDetailOut, TripsOut } from "../shared/api/types";
import ask from "./fixtures/ask.json";
import imports from "./fixtures/imports.json";
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

import holdingsMeta from "./fixtures/holdings/meta.json";
import holdingsRegimes from "./fixtures/holdings/regimes.json";
import holdingsSummary from "./fixtures/holdings/summary.json";
import holdingsHoldings from "./fixtures/holdings/holdings.json";
import holdingsTrips from "./fixtures/holdings/trips.json";
import holdingsBiases from "./fixtures/holdings/biases.json";
import valuedMeta from "./fixtures/valued/meta.json";
import valuedRegimes from "./fixtures/valued/regimes.json";
import valuedSummary from "./fixtures/valued/summary.json";
import valuedHoldings from "./fixtures/valued/holdings.json";
import valuedTrips from "./fixtures/valued/trips.json";
import valuedBiases from "./fixtures/valued/biases.json";
import emptyBiases from "./fixtures/empty/biases.json";
import fullBiases from "./fixtures/full/biases.json";
import fewBiases from "./fixtures/few/biases.json";
import excludedBiases from "./fixtures/excluded/biases.json";
import emptySummary from "./fixtures/empty/summary.json";
import emptyHoldings from "./fixtures/empty/holdings.json";
import openBiases from "./fixtures/open/biases.json";
import importedMeta from "./fixtures/imported/meta.json";
import importedRegimes from "./fixtures/imported/regimes.json";
import importedSummary from "./fixtures/imported/summary.json";
import importedHoldings from "./fixtures/imported/holdings.json";
import importedTrips from "./fixtures/imported/trips.json";
import importedBiases from "./fixtures/imported/biases.json";
import importedStatus from "./fixtures/imported/status.json";
export type ScenarioName = "full" | "few" | "excluded" | "open" | "empty" | "holdings" | "valued" | "imported";

export interface Scenario {
  meta: MetaOut;
  trips: TripsOut;
  regimes: RegimesOut;
  trip?: TripDetailOut;
  trades: Record<string, unknown>[];
  biases: BiasesOut;
  summary?: SummaryOut;
  holdings?: HoldingOut[];
  status?: ImportStatus;
}

export const scenarios = {
  full: { biases: fullBiases as BiasesOut, meta: fullMeta as MetaOut, trips: fullTrips as TripsOut, regimes: fullRegimes as RegimesOut, trip: fullTrip as TripDetailOut, trades: [{}] },
  few: { biases: fewBiases as BiasesOut, meta: fewMeta as MetaOut, trips: fewTrips as TripsOut, regimes: fewRegimes as RegimesOut, trip: fewTrip as TripDetailOut, trades: [{}] },
  excluded: { biases: excludedBiases as BiasesOut, meta: excludedMeta as MetaOut, trips: excludedTrips as TripsOut, regimes: excludedRegimes as RegimesOut, trip: excludedTrip as TripDetailOut, trades: [{}] },
  open: { biases: openBiases as BiasesOut, meta: openMeta as MetaOut, trips: openTrips as TripsOut, regimes: openRegimes as RegimesOut, trades: openTrades },
  empty: { summary: emptySummary as SummaryOut, holdings: emptyHoldings as HoldingOut[], biases: emptyBiases as BiasesOut, meta: emptyMeta as MetaOut, trips: emptyTrips as TripsOut, regimes: emptyRegimes as RegimesOut, trades: emptyTrades },
} as unknown as Record<ScenarioName, Scenario>;

const owned = (n: "holdings" | "valued" | "imported", meta: unknown, regimes: unknown, trips: unknown, biases: unknown, summary: unknown, holdings: unknown): Scenario => ({
  meta: meta as MetaOut, regimes: regimes as RegimesOut, trips: trips as TripsOut, biases: biases as BiasesOut, summary: summary as SummaryOut,
  holdings: holdings as HoldingOut[], trades: [{ n }],
});
scenarios.holdings = owned("holdings", holdingsMeta, holdingsRegimes, holdingsTrips, holdingsBiases, holdingsSummary, holdingsHoldings);
scenarios.imported = { ...owned("imported", importedMeta, importedRegimes, importedTrips, importedBiases, importedSummary, importedHoldings), status: importedStatus as ImportStatus };
scenarios.valued = owned("valued", valuedMeta, valuedRegimes, valuedTrips, valuedBiases, valuedSummary, valuedHoldings);

type Recorded = Record<string, { status: number; body: Record<string, unknown> }>;
export const recordedAsk = ask as unknown as Recorded;
export const recordedImports = imports as unknown as Recorded;

export const recordedErrors = errors as { not_sealed: { status: number; body: Record<string, unknown> }; trip_not_found: { status: number; body: Record<string, unknown> } };
