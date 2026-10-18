// Screenshots of the running app (trip list + trip detail, desktop + mobile).
// Usage: node scripts/screenshots.mjs [baseUrl] [outDir]   (start the backend and `npm run dev` first)
import { mkdirSync } from "node:fs";
import { chromium } from "@playwright/test";

const base = process.argv[2] ?? "http://127.0.0.1:5173";
const out = process.argv[3] ?? "../docs/reports/c1-screenshots";
mkdirSync(out, { recursive: true });

const browser = await chromium.launch();
for (const [name, viewport] of [["desktop", { width: 1280, height: 900 }], ["mobile", { width: 390, height: 844 }]]) {
  const page = await browser.newPage({ viewport });
  await page.goto(`${base}/trips`);
  await page.getByRole("table").waitFor();
  await page.screenshot({ path: `${out}/trip-list-${name}.png`, fullPage: true });
  await page.getByRole("link", { name: /· NSE/ }).first().click();
  await page.getByRole("img", { name: /Histogram/ }).waitFor();
  await page.screenshot({ path: `${out}/trip-detail-${name}.png`, fullPage: true });
  await page.close();
}
await browser.close();
console.log(`wrote screenshots to ${out}`);
