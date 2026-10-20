/**
 * Routes of attendance, children of /c/:companyId (plan §6.1: attendance, attendance/timesheet,
 * attendance/roster, attendance/schedules, attendance/swaps, attendance/corrections). Pages load
 * lazily (through lazy.ts) and are prefetched when the pointer rests on their nav link.
 */
import type { RouteRecordRaw } from "vue-router";

/** One import for every page (lazy.ts explains why). */
export const lazy = () => import("./lazy");

export const routes: RouteRecordRaw[] = [
  {
    path: "attendance",
    name: "attendance.today",
    component: () => lazy().then((m) => m.pages.today()),
    meta: { title: "attendance.nav.today" },
  },
  {
    path: "attendance/timesheet",
    name: "attendance.timesheet",
    component: () => lazy().then((m) => m.pages.timesheet()),
    meta: { title: "attendance.nav.timesheet" },
  },
  {
    path: "attendance/roster",
    name: "attendance.roster",
    component: () => lazy().then((m) => m.pages.roster()),
    meta: { title: "attendance.nav.roster" },
  },
  {
    path: "attendance/schedules",
    name: "attendance.schedules",
    component: () => lazy().then((m) => m.pages.schedules()),
    meta: { title: "attendance.nav.schedules", perm: "attendance.manage" },
  },
  {
    path: "attendance/swaps",
    name: "attendance.swaps",
    component: () => lazy().then((m) => m.pages.swaps()),
    meta: { title: "attendance.nav.swaps", perm: "attendance.manage" },
  },
  {
    path: "attendance/corrections",
    name: "attendance.corrections",
    component: () => lazy().then((m) => m.pages.corrections()),
    meta: { title: "attendance.nav.corrections", perm: "attendance.manage" },
  },
];
