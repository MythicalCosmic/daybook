/** Routes of routines, children of /c/:companyId (plan §6.1: routines, routines/:id, routines/onboarding). */
import type { RouteRecordRaw } from "vue-router";

const page = () => import("./pages/RoutinesPage.vue");

export const routes: RouteRecordRaw[] = [
  { path: "routines", name: "routines.list", component: page, meta: { title: "routines.title" } },
  { path: "routines/onboarding", name: "routines.onboarding", component: page, meta: { title: "routines.tabs.onboarding" } },
  { path: "routines/:id(\\d+)", name: "routines.detail", component: () => import("./pages/RoutineDetailPage.vue"), meta: { title: "routines.title" } },
];
