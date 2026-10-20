/** Routes of time off, children of /c/:companyId (plan §6.1). Package L adds balances and types. */
import type { RouteRecordRaw } from "vue-router";

export const routes: RouteRecordRaw[] = [
  {
    path: "time-off",
    name: "timeoff.calendar",
    component: () => import("./pages/TimeOffPage.vue"),
    meta: { title: "timeoff.nav.calendar", perm: "time_off.approve" },
  },
  {
    path: "time-off/holidays",
    name: "timeoff.holidays",
    component: () => import("./pages/HolidaysPage.vue"),
    meta: { title: "timeoff.nav.holidays", perm: "time_off.approve" },
  },
];
