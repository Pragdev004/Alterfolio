/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dev server forwards API paths to the backend, so the browser sees one origin and no CORS configuration is needed.
const backend = process.env.ALTERFOLIO_BACKEND ?? "http://127.0.0.1:8000";
const proxied = ["/api", "/portfolio", "/trades", "/imports", "/health"];

export default defineConfig({
  plugins: [react()],
  server: { proxy: Object.fromEntries(proxied.map((path) => [path, { target: backend, changeOrigin: false }])) },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
