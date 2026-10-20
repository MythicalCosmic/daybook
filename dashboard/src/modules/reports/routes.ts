/** Routes of team reports, children of /c/:companyId (plan §6.1: reports/team, reports/routines). */
import type { RouteRecordRaw } from "vue-router";

export const routes: RouteRecordRaw[] = [
  { path: "reports/team", name: "reports.team", component: () => import("./pages/TeamReportPage.vue"), meta: { title: "reports.tabs.team" } },
  { path: "reports/routines", name: "reports.routines", component: () => import("./pages/RoutineReportPage.vue"), meta: { title: "reports.tabs.routines" } },
];
