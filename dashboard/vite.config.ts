import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

import { moduleTitles } from "./scripts/moduleTitles.mjs";

// Ports per package come from the environment (plan §2.4, §6.5): DEV_PORT for this server,
// API_PORT for the Django it proxies to, STREAM_PORT for the stream service.
const port = Number(process.env.DEV_PORT ?? 28174);
const backend = `http://127.0.0.1:${Number(process.env.API_PORT ?? 28000)}`;
const stream = `http://127.0.0.1:${Number(process.env.STREAM_PORT ?? 28001)}`;

/** Libraries that only a few pages need get their own chunks, so the shell never pays for them. */
const isolated: Array<[name: string, test: RegExp]> = [
  ["echarts", /node_modules[\\/](echarts|zrender|vue-echarts)[\\/]/],
  ["tiptap", /node_modules[\\/](@tiptap|prosemirror-[a-z-]+|orderedmap|rope-sequence|w3c-keyname|linkifyjs)[\\/]/],
  ["leaflet", /node_modules[\\/]leaflet[\\/]/],
  // MarkdownView's renderer, shared by every page that shows Markdown.
  ["markdown", /node_modules[\\/](markdown-it|mdurl|uc\.micro|linkify-it|punycode\.js|entities|dompurify)[\\/]/],
  // The framework every page needs, in one chunk: split across shared chunks it compresses worse.
  ["vendor", /node_modules[\\/](@vue|vue|vue-router|pinia|@tanstack[\\/](vue-query|query-core)|vue-i18n|@intlify)[\\/]/],
];

export default defineConfig({
  // moduleTitles: `virtual:module-titles`, every module's titles in all three languages for the palette.
  plugins: [vue(), tailwindcss(), moduleTitles(fileURLToPath(new URL("./src/modules", import.meta.url)))],
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
    // vue-i18n without its message compiler (~10 KB gzipped): src/i18n/compile.ts compiles the
    // console's messages instead (`messageCompiler` in src/i18n/index.ts).
    __INTLIFY_DROP_MESSAGE_COMPILER__: "true",
  },
  server: {
    host: "127.0.0.1",
    port,
    strictPort: true,
    // The Host header stays the dev server's own: the cookie endpoints (refresh, logout, dev login)
    // accept only a same-origin `Origin` (apps.signin.auth.FromDashboard), and Vite's string
    // shorthand would rewrite Host to the backend's and make every one of them answer 403.
    // AI answer streams go to the stream service, as deploy/Caddyfile routes them; listed first
    // because the first matching prefix wins.
    proxy: {
      "/api/v1/owner/ai/turns": { target: stream, changeOrigin: false },
      "/api": { target: backend, changeOrigin: false },
      "/media": { target: backend, changeOrigin: false },
    },
  },
  preview: { host: "127.0.0.1", port, strictPort: true },
  build: {
    target: "es2022",
    sourcemap: false,
    // Fonts are never inlined into the CSS: each loads only when its unicode-range is on screen
    // (styles/fonts.css), and a base64 copy would ride in everyone's first load.
    assetsInlineLimit: (file) => (/\.woff2?$/.test(file) ? false : undefined),
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            ...isolated.map(([name, test], index) => ({ name, test, priority: 10 + index })),
            // Everything else the first page load needs (the shell, every module's index.ts, the
            // icons they name, the reka-ui pieces the shell uses) goes into the entry chunk instead
            // of ~60 small shared chunks. Nothing enters the first load that wasn't in it already,
            // and it is much smaller: one gzip stream, and every lazy import's preload list
            // (`__vite__mapDeps`, in the first load too) names one file instead of dozens.
            // README "Budgets" explains how to measure it.
            { name: "app", tags: ["$initial" as const], priority: 1 },
          ],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts"],
    setupFiles: ["src/test/setup.ts"],
    restoreMocks: true,
  },
});
