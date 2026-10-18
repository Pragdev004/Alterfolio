import { http, HttpResponse } from "msw";

import { recordedAsk, recordedErrors, recordedImports, scenarios, type ScenarioName } from "./fixtures";
import { noRejections, server } from "./server";

export interface Seen {
  asOf: (string | null)[];
}

/** Serve one recorded scenario. `as_of` values are captured so a test can see what the UI asked for. */
export function serve(name: ScenarioName, seen: Seen = { asOf: [] }): Seen {
  const s = scenarios[name];
  const capture = (request: Request) => {
    seen.asOf.push(new URL(request.url).searchParams.get("as_of"));
  };
  server.use(
    http.get("*/api/analysis/meta", () => HttpResponse.json(s.meta)),
    http.get("*/api/analysis/trips", ({ request }) => {
      capture(request);
      return HttpResponse.json(s.trips);
    }),
    http.get("*/api/analysis/trips/:id", ({ request, params }) => {
      capture(request);
      if (s.trip && params.id === s.trip.trip.trip_id) return HttpResponse.json(s.trip);
      return HttpResponse.json(recordedErrors.trip_not_found.body, { status: recordedErrors.trip_not_found.status });
    }),
    http.get("*/api/analysis/regimes", () => HttpResponse.json(s.regimes)),
    http.get("*/trades", () => HttpResponse.json(s.trades)),
    http.get("*/api/analysis/biases", ({ request }) => {
      capture(request);
      return HttpResponse.json(s.biases);
    }),
    http.get("*/portfolio/summary", () => HttpResponse.json(s.summary ?? scenarios.empty.summary!)),
    http.get("*/portfolio/holdings", () => HttpResponse.json(s.holdings ?? [])),
    http.get("*/imports/status", () => HttpResponse.json(s.status ?? noRejections)),
  );
  return seen;
}

export const failWith = {
  network: () => HttpResponse.error(),
  server: () => HttpResponse.json({ detail: "boom" }, { status: 500 }),
  notSealed: () => HttpResponse.json(recordedErrors.not_sealed.body, { status: recordedErrors.not_sealed.status }),
};

type Recorded = { status: number; body: Record<string, unknown> };
const reply = (r: Recorded) => HttpResponse.json(r.body, { status: r.status });

/** Answer the next POSTs with a recorded response. */
export const serveImport = (key: keyof typeof recordedImports) => server.use(http.post("*/imports/tradebook", () => reply(recordedImports[key]!)));
export const serveAsk = (key: keyof typeof recordedAsk) => server.use(http.post("*/api/analyst/ask", () => reply(recordedAsk[key]!)));
