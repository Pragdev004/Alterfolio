import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

// Smoke path against the mocked API: trip list -> trip detail -> an Unavailable value renders the word and its reason.
// The bodies are the recorded real 013a responses (backend/scripts/record_fixtures.py).
const fixture = (name: string) => JSON.parse(readFileSync(join(process.cwd(), "src/test/fixtures/full", name), "utf8"));

test("trip list to trip detail, and an Unavailable value shows the word and its reason", async ({ page }) => {
  const trip = fixture("trip.json");
  await page.route("**/api/analysis/meta", (r) => r.fulfill({ json: fixture("meta.json") }));
  await page.route("**/api/analysis/regimes**", (r) => r.fulfill({ json: fixture("regimes.json") }));
  await page.route("**/api/analysis/trips", (r) => r.fulfill({ json: fixture("trips.json") }));
  await page.route("**/api/analysis/trips/*", (r) => r.fulfill({ json: trip }));

  await page.goto("/trips");
  await expect(page.getByRole("heading", { level: 1, name: "Trips" })).toBeVisible();
  await expect(page.getByRole("group", { name: "Data as of" })).toContainText("Chart prepared");
  await page.getByRole("link", { name: /· NSE/ }).first().click();

  await expect(page.getByRole("heading", { level: 1, name: trip.trip.symbol })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/trips/${trip.trip.trip_id}`));
  const nifty = page.getByRole("row", { name: /Nifty 50 random portfolios/ });
  await expect(nifty.getByText("Unavailable").first()).toBeVisible();
  await expect(nifty).toContainText(trip.trip.nifty.reason_text);
  await expect(page.getByRole("img", { name: /Histogram/ })).toBeVisible();
});
