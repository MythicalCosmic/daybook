import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:28000";
const port = Number(process.env.DASHBOARD_PORT ?? process.env.PORT ?? 28174);

/** Libraries that only a few pages need get their own chunks, so the shell never pays for them. */
const isolated: Array<[name: string, test: RegExp]> = [
  ["echarts", /node_modules[\\/](echarts|zrender|vue-echarts)[\\/]/],
  ["tiptap", /node_modules[\\/](@tiptap|prosemirror-[a-z-]+|orderedmap|rope-sequence|w3c-keyname|linkifyjs)[\\/]/],
  ["leaflet", /node_modules[\\/]leaflet[\\/]/],
];

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  // Served by Django at /dashboard/ in production; the dev server mirrors that.
  base: "/dashboard/",
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  define: {
    __VUE_OPTIONS_API__: "true",
    __VUE_PROD_DEVTOOLS__: "false",
    __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: "false",
    __VUE_I18N_FULL_INSTALL__: "true",
    __VUE_I18N_LEGACY_API__: "false",
    __INTLIFY_PROD_DEVTOOLS__: "false",
  },
  server: {
    host: "127.0.0.1",
    port,
    strictPort: true,
    proxy: { "/api": backend, "/media": backend },
  },
  preview: { host: "127.0.0.1", port, strictPort: true },
  build: {
    target: "es2022",
    sourcemap: false,
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: isolated.map(([name, test], index) => ({ name, test, priority: 10 + index })),
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts"],
    restoreMocks: true,
  },
});
