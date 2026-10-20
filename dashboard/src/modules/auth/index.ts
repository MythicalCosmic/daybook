/**
 * Signing in (plan §6.1 "/dashboard/login", §7): the only module with `publicRoutes`. The login
 * page shows a QR code of a Telegram deep link with number matching; inside Telegram the shell
 * signs in silently with initData (TelegramBridge), so the page never shows there. In
 * development only, `/dev/login` signs in as any Telegram id. No sidebar row, no company routes;
 * the sessions page lives in Settings.
 */
import { LogIn } from "@lucide/vue";
import type { RouteRecordRaw } from "vue-router";

import { defineModule } from "@/core/modules";

const publicRoutes: RouteRecordRaw[] = [
  { path: "/login", name: "login", component: () => import("./pages/LoginPage.vue"), meta: { title: "auth.login.title" } },
];
// `import.meta.env.DEV` is false in a build, so the developer sign-in never ships.
if (import.meta.env.DEV) {
  publicRoutes.push({ path: "/dev/login", name: "dev-login", component: () => import("./pages/DevLoginPage.vue"), meta: { title: "auth.dev.title" } });
}

export default defineModule({
  id: "auth",
  group: "company",
  order: 90,
  icon: LogIn,
  title: "auth.title",
  routes: [],
  publicRoutes,
  nav: [],
  messages: async () => {
    const [uz, ru, en] = await Promise.all([import("./i18n/uz.json"), import("./i18n/ru.json"), import("./i18n/en.json")]);
    return { uz: uz.default, ru: ru.default, en: en.default };
  },
});
