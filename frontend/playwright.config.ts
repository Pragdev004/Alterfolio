import { defineConfig } from "@playwright/test";

// One smoke path against the mocked API (fixtures recorded from the real 013a responses; see e2e/smoke.spec.ts).
export default defineConfig({
  testDir: "e2e",
  webServer: { command: "npx vite --host 127.0.0.1 --port 5199 --strictPort", url: "http://127.0.0.1:5199", reuseExistingServer: false },
  use: { baseURL: "http://127.0.0.1:5199", viewport: { width: 1280, height: 900 } },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
