/**
 * Routes of routines, children of /c/:companyId. The Routines page is the home of routine work:
 * Today (the default), History and To confirm, then the routines themselves (All routines, with
 * onboarding templates beside them) and one routine's page.
 */
import type { RouteRecordRaw } from "vue-router";

const definitions = () => import("./pages/RoutinesPage.vue");

export const routes: RouteRecordRaw[] = [
  { path: "routines", name: "routines.today", component: () => import("./pages/TodayPage.vue"), meta: { title: "routines.title", perm: "tasks.view_all" } },
  { path: "routines/history", name: "routines.history", component: () => import("./pages/HistoryPage.vue"), meta: { title: "routines.nav.history", perm: "tasks.view_all" } },
  { path: "routines/confirm", name: "routines.confirm", component: () => import("./pages/ConfirmPage.vue"), meta: { title: "routines.nav.confirm", perm: "tasks.confirm" } },
  { path: "routines/all", name: "routines.list", component: definitions, meta: { title: "routines.nav.all", perm: "tasks.templates" } },
  { path: "routines/onboarding", name: "routines.onboarding", component: definitions, meta: { title: "routines.tabs.onboarding", perm: "tasks.templates" } },
  { path: "routines/:id(\\d+)", name: "routines.detail", component: () => import("./pages/RoutineDetailPage.vue"), meta: { title: "routines.title", perm: "tasks.templates" } },
];
