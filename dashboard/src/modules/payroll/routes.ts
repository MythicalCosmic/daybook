/**
 * Routes of payroll, children of /c/:companyId (plan §6.1: payroll, payroll/runs/:id, payroll/pay,
 * payroll/adjustments, payroll/rules, payroll/advances). Pages load lazily through lazy.ts and are
 * prefetched when the pointer rests on their nav link.
 */
import type { RouteRecordRaw } from "vue-router";

/** One import for every page (lazy.ts explains why). */
export const lazy = () => import("./lazy");

export const routes: RouteRecordRaw[] = [
  {
    path: "payroll",
    name: "payroll.runs",
    component: () => lazy().then((m) => m.pages.runs()),
    meta: { title: "payroll.nav.runs", perm: "payroll.view" },
  },
  {
    path: "payroll/runs/:runId(\\d+)",
    name: "payroll.run",
    component: () => lazy().then((m) => m.pages.run()),
    meta: { title: "payroll.run.title", perm: "payroll.view" },
  },
  {
    path: "payroll/pay",
    name: "payroll.pay",
    component: () => lazy().then((m) => m.pages.pay()),
    meta: { title: "payroll.nav.pay", perm: "payroll.view" },
  },
  {
    path: "payroll/adjustments",
    name: "payroll.adjustments",
    component: () => lazy().then((m) => m.pages.adjustments()),
    meta: { title: "payroll.nav.adjustments", perm: ["payroll.view", "payroll.propose", "payroll.manage"] },
  },
  {
    path: "payroll/rules",
    name: "payroll.rules",
    component: () => lazy().then((m) => m.pages.rules()),
    meta: { title: "payroll.nav.rules", perm: "payroll.manage" },
  },
  {
    path: "payroll/advances",
    name: "payroll.advances",
    component: () => lazy().then((m) => m.pages.advances()),
    meta: { title: "payroll.nav.advances", perm: ["payroll.manage", "payroll.pay"] },
  },
];
