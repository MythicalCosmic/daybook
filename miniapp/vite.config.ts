import { readFileSync } from "node:fs";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The release (package.json, kept equal to pyproject.toml by the backend's tests), shown on Me.
const { version } = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")) as { version: string };

// Each package runs its own backend and dev server (PLAN-OWNER §2.4): DEV_PORT and API_PORT pick
// them, BACKEND_URL overrides the whole backend address. The defaults are the lead's ports.
const port = Number(process.env.DEV_PORT ?? 28173);
const backend = process.env.BACKEND_URL ?? `http://127.0.0.1:${process.env.API_PORT ?? 28000}`;

export default defineConfig({
  plugins: [react()],
  define: { __APP_VERSION__: JSON.stringify(version) },
  // Served by Django at /app/ in production; the dev server mirrors that.
  base: "/app/",
  server: {
    host: "127.0.0.1",
    port,
    strictPort: true,
    proxy: { "/api": backend, "/media": backend },
  },
  test: {
    environment: "jsdom",
  },
});
