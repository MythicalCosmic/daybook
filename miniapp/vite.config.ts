import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Ports come from the environment so each work package runs its own copy (`make app PKG=e`,
// deploy/dev-packages.mk); the defaults are the lead's.
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
