/** Routes of the company calendar, children of /c/:companyId. */
import type { RouteRecordRaw } from "vue-router";

export const routes: RouteRecordRaw[] = [
  {
    path: "calendar",
    name: "agenda.calendar",
    component: () => import("./pages/CalendarPage.vue"),
    meta: { title: "agenda.title" },
  },
];
