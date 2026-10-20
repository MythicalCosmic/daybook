/** Routes of reminders, children of /c/:companyId (plan §6.1 `reminders`). */
import type { RouteRecordRaw } from "vue-router";

export const routes: RouteRecordRaw[] = [
  {
    path: "reminders",
    name: "reminders.page",
    component: () => import("./pages/RemindersPage.vue"),
    meta: { title: "reminders.title" },
  },
];
