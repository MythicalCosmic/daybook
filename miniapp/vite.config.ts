import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:28000";

export default defineConfig({
  plugins: [react()],
  // Served by Django at /app/ in production; the dev server mirrors that.
  base: "/app/",
  server: {
    host: "127.0.0.1",
    port: 28173,
    proxy: { "/api": backend, "/media": backend },
  },
  test: {
    environment: "jsdom",
  },
});
