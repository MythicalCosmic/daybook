/** Routes of business goals, children of /c/:companyId. The page loads lazily. */
import type { RouteRecordRaw } from "vue-router";

export const routes: RouteRecordRaw[] = [
  {
    path: "goals",
    name: "goals.list",
    component: () => import("./pages/GoalsPage.vue"),
    meta: { title: "goals.title", perm: "reports.view" },
  },
];
