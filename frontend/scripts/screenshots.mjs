// Screenshots of every screen, desktop + mobile, from the running app.
// Usage: node scripts/screenshots.mjs [outDir]
// Needs three dev worlds (backend/scripts/dev_server.py) each behind its own Vite proxy:
//   FULL (full, :5180)  HOLDINGS (holdings, :5181)  EMPTY (empty ledger, :5182)  -- override with env FULL / HOLDINGS / EMPTY.
import { mkdirSync, readFileSync } from "node:fs";
import { chromium } from "@playwright/test";

const FULL = process.env.FULL ?? "http://127.0.0.1:5180";
const HOLDINGS = process.env.HOLDINGS ?? "http://127.0.0.1:5181";
const EMPTY = process.env.EMPTY ?? "http://127.0.0.1:5182";
const SYNTHETIC_CSV = new URL("../../backend/tests/fixtures/tradebook_synthetic.csv", import.meta.url).pathname; // invented data, never a real tradebook
const out = process.argv[2] ?? "../docs/reports/c2-screens";
mkdirSync(out, { recursive: true });

const browser = await chromium.launch();
for (const [size, viewport] of [["desktop", { width: 1440, height: 900 }], ["mobile", { width: 390, height: 844 }]]) {
  const shoot = async (page, name) => page.screenshot({ path: `${out}/${name}-${size}.png`, fullPage: true });
  const open = async (base, path, ready) => {
    const page = await browser.newPage({ viewport });
    await page.goto(base + path);
    await ready(page);
    return page;
  };

  let page = await open(FULL, "/trips", (p) => p.getByRole("table").waitFor());
  await shoot(page, "trips");
  await page.getByRole("link", { name: /·\s+NSE/ }).first().click();
  await page.getByRole("img", { name: /Histogram/ }).waitFor();
  await shoot(page, "trip-detail");
  await page.close();

  page = await open(FULL, "/costs", (p) => p.getByRole("table").waitFor());
  await shoot(page, "costs");
  await page.close();

  page = await open(FULL, "/ask", (p) => p.getByLabel("Your question").waitFor());
  await page.getByLabel("Your question").fill("What did my behaviour cost me?");
  await page.getByRole("button", { name: "Ask" }).click();
  await page.getByRole("heading", { name: "Answer" }).waitFor();
  await shoot(page, "ask");
  await page.close();

  page = await open(HOLDINGS, "/holdings", (p) => p.getByRole("table").waitFor());
  await shoot(page, "holdings");
  await page.close();

  // the second viewport uploads the same invented file with new trade ids, so it is not a duplicate of the first
  const csv = readFileSync(SYNTHETIC_CSV, "utf8").replace(/,9000(\d\d),/g, size === "desktop" ? ",9000$1," : ",9100$1,");
  page = await open(EMPTY, "/upload", (p) => p.getByLabel("Tradebook CSV").waitFor());
  await shoot(page, "upload");
  await page.getByLabel("Tradebook CSV").setInputFiles({ name: "tradebook_synthetic.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await page.getByRole("button", { name: "Import tradebook" }).click();
  await page.getByRole("heading", { name: /Import result/ }).waitFor();
  await shoot(page, "upload-result");
  await page.close();
}
await browser.close();
console.log(`wrote screenshots to ${out}`);
