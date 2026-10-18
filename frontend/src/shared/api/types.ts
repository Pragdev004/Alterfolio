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
