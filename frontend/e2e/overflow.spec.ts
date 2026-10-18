import { expect, test } from "@playwright/test";

import { fixture, mockApi } from "./mock";

// The page must never scroll sideways, and the left rail must stay in view, at any width.
const WIDTHS = [1920, 1366, 1000, 700, 390];
const tripId = fixture("full/trip.json").trip.trip_id as string;
const ROUTES = ["/trips", `/trips/${tripId}`, "/holdings", "/costs", "/ask", "/upload"];

for (const width of WIDTHS) {
  test(`no horizontal scroll at ${width}px on any screen`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockApi(page);
    for (const route of ROUTES) {
      await page.goto(route);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await page.waitForLoadState("networkidle");
      const { scroll, client } = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
      expect(scroll, `${route} at ${width}px`).toBeLessThanOrEqual(client);
      await expect(page.getByRole("navigation", { name: "Screens" })).toBeInViewport();
    }
    // the upload result summary and an ask answer are the widest states of their screens
    await page.goto("/upload");
    await page.getByLabel("Tradebook CSV").setInputFiles({ name: "t.csv", mimeType: "text/csv", buffer: Buffer.from("a\n") });
    await page.getByRole("button", { name: "Import tradebook" }).click();
    await expect(page.getByRole("heading", { name: /Import result/ })).toBeVisible();
    await page.goto("/ask");
    await page.getByLabel("Your question").fill("What did my behaviour cost me?");
    await page.getByRole("button", { name: "Ask" }).click();
    await expect(page.getByRole("heading", { name: "Answer" })).toBeVisible();
    const { scroll, client } = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
    expect(scroll, `ask answer at ${width}px`).toBeLessThanOrEqual(client);
  });
}

// Real data can carry long names and long sentences: they must wrap, never widen the page.
for (const width of [1890, 1366, 390]) {
  test(`long listing names and reasons do not widen the page at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockApi(page);
    const longer = (o: unknown) => JSON.parse(JSON.stringify(o), (k, v) => (typeof v === "string" && /symbol|label|reason_text|text|message/.test(k) && v.length > 2 ? v + "X".repeat(180) : v));
    await page.route("**/api/analysis/trips", (r) => r.fulfill({ json: longer(fixture("excluded/trips.json")) }));
    await page.route("**/api/analysis/trips/*", (r) => r.fulfill({ json: longer(fixture("full/trip.json")) }));
    for (const route of ["/trips", `/trips/${tripId}`]) {
      await page.goto(route);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await page.waitForLoadState("networkidle");
      const { scroll, client } = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
      expect(scroll, `${route} at ${width}px`).toBeLessThanOrEqual(client);
    }
  });
}
