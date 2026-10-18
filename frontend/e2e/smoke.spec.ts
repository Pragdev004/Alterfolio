import { expect, test } from "@playwright/test";

import { fixture, mockApi } from "./mock";

// Smoke path against the mocked API: upload -> trips -> trip detail -> an Unavailable value renders the word and its reason.
test("upload, then trips, then a trip, and an Unavailable value shows the word and its reason", async ({ page }) => {
  const trip = fixture("full/trip.json");
  await mockApi(page, { imported: false });

  await page.goto("/upload");
  await expect(page.getByText("Upload your oldest tradebook first.")).toBeVisible();
  await page.getByLabel("Tradebook CSV").setInputFiles({ name: "tradebook.csv", mimeType: "text/csv", buffer: Buffer.from("a,b\n1,2\n") });
  await page.getByRole("button", { name: "Import tradebook" }).click();
  await expect(page.getByRole("heading", { name: /Import result/ })).toBeVisible();
  await expect(page.getByText("Charges are unknown, not zero")).toBeVisible();

  await page.getByRole("link", { name: "See your trips" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Trips" })).toBeVisible();
  await expect(page.getByRole("group", { name: "Data as of" })).toContainText("Chart prepared");
  await page.getByRole("link", { name: /·\s+NSE/ }).first().click();

  await expect(page.getByRole("heading", { level: 1, name: trip.trip.symbol })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/trips/${trip.trip.trip_id}`));
  const nifty = page.getByRole("row", { name: /Nifty 50 random portfolios/ });
  await expect(nifty.getByText("Unavailable").first()).toBeVisible();
  await expect(nifty).toContainText(trip.trip.nifty.reason_text);
  await expect(page.getByRole("img", { name: /Histogram/ })).toBeVisible();
});

test("the page is English (India)", async ({ page }) => {
  await mockApi(page);
  await page.goto("/trips");
  await expect(page.locator("html")).toHaveAttribute("lang", "en-IN");
});
