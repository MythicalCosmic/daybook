import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Each package runs its own backend and dev server (PLAN-OWNER §2.4): DEV_PORT and API_PORT pick
// them, BACKEND_URL overrides the whole backend address. The defaults are the lead's ports.
const port = Number(process.env.DEV_PORT ?? 28173);
const backend = process.env.BACKEND_URL ?? `http://127.0.0.1:${process.env.API_PORT ?? 28000}`;

export default defineConfig({
  plugins: [react()],
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
