/** Routes of Settings, children of /c/:companyId. `:panel` picks a panel ("settings/branches"). */
import type { RouteRecordRaw } from "vue-router";

export const routes: RouteRecordRaw[] = [
  {
    path: "settings/:panel?",
    name: "settings.page",
    component: () => import("./pages/SettingsPage.vue"),
    meta: { title: "settings.title" },
  },
];
