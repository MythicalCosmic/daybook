import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

// Ports per package come from the environment (plan §2.4, §6.5): DEV_PORT for this server,
// API_PORT for the Django it proxies to.
const port = Number(process.env.DEV_PORT ?? 28174);
const backend = `http://127.0.0.1:${Number(process.env.API_PORT ?? 28000)}`;

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
    // vue-i18n without its message compiler (~10 KB gzipped): src/i18n/compile.ts compiles the
    // console's messages instead (`messageCompiler` in src/i18n/index.ts).
    __INTLIFY_DROP_MESSAGE_COMPILER__: "true",
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
