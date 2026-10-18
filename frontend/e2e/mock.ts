import type { Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

// Recorded real responses (backend/scripts/record_fixtures.py) served in place of the API.
const read = (path: string) => JSON.parse(readFileSync(join(process.cwd(), "src/test/fixtures", path), "utf8"));

/** Mock the whole API. `imported` flips when a tradebook is uploaded: before it the ledger is empty, after it the trips exist. */
export async function mockApi(page: Page, opts: { imported?: boolean } = {}) {
  const state = { imported: opts.imported ?? true };
  const pick = (name: string) => read(`${state.imported ? "full" : "empty"}/${name}`);
  await page.route("**/api/analysis/meta", (r) => r.fulfill({ json: read("full/meta.json") }));
  await page.route("**/api/analysis/regimes**", (r) => r.fulfill({ json: pick("regimes.json") }));
  await page.route("**/api/analysis/biases**", (r) => r.fulfill({ json: pick("biases.json") }));
  await page.route("**/api/analysis/trips", (r) => r.fulfill({ json: pick("trips.json") }));
  await page.route("**/api/analysis/trips/*", (r) => r.fulfill({ json: read("full/trip.json") }));
  await page.route("**/trades", (r) => r.fulfill({ json: state.imported ? [{ id: "t" }] : [] }));
  await page.route("**/portfolio/summary", (r) => r.fulfill({ json: read("holdings/summary.json") }));
  await page.route("**/portfolio/holdings", (r) => r.fulfill({ json: read("holdings/holdings.json") }));
  await page.route("**/imports/status", (r) => r.fulfill({ json: { batches: [], rejected_rows_total: 0, warning: null } }));
  await page.route("**/imports/tradebook", (r) => {
    state.imported = true;
    return r.fulfill({ status: 201, json: read("imports.json").ok.body });
  });
  await page.route("**/api/analyst/ask", (r) => r.fulfill({ json: read("ask.json").template.body }));
  return state;
}

export const fixture = (path: string) => read(path);
