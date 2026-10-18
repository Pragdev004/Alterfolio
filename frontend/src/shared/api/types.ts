import type { components } from "./schema";

type S = components["schemas"];

export type NumberOut = S["NumberOut"];
export type DateOut = S["DateOut"];
export type MetaOut = S["MetaOut"];
export type TripsOut = S["TripsOut"];
export type TripRow = S["TripRowOut"];
export type TripDetailOut = S["TripDetailOut"];
export type TripDetailRow = S["TripDetailRowOut"];
export type Outcome = S["OutcomeOut"];
export type Histogram = S["HistogramOut"];
export type RegimeTag = S["RegimeTagOut"];
export type BaselineSummary = S["BaselineSummaryOut"];
export type RegimesOut = S["RegimesOut"];
export type TradeOut = S["TradeOut"];
export type SummaryOut = S["SummaryOut"];
export type SummaryHolding = S["SummaryHoldingOut"];
export type HoldingOut = S["HoldingOut"];
export type ImportResult = S["ImportResultOut"];
export type ImportStatus = S["ImportStatusOut"];
export type ImportBatch = S["ImportBatchOut"];
export type BiasesOut = S["BiasesOut"];
export type BiasOut = S["BiasOut"];

/** `POST /api/analyst/ask` has no response model in OpenAPI; this is its documented body (spec 013 section 3). */
export interface AskOut {
  text: string;
  citations: { kind: string; ref: string }[];
  verified: boolean;
  as_of: string;
  attempts: number;
  answer_source: "template" | "llm";
}
