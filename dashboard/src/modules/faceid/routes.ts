/**
 * Routes of Face ID, children of /c/:companyId: the live feed, everyone the terminals know, the
 * terminals with their setup, and the settings. Pages load lazily through lazy.ts.
 */
import type { RouteRecordRaw } from "vue-router";

/** One import for every page (lazy.ts explains why). */
export const lazy = () => import("./lazy");

export const routes: RouteRecordRaw[] = [
  {
    path: "faceid",
    name: "faceid.live",
    component: () => lazy().then((m) => m.pages.live()),
    meta: { title: "faceid.nav.live" },
  },
  {
    path: "faceid/people",
    name: "faceid.people",
    component: () => lazy().then((m) => m.pages.people()),
    meta: { title: "faceid.nav.people" },
  },
  {
    path: "faceid/terminals",
    name: "faceid.terminals",
    component: () => lazy().then((m) => m.pages.terminals()),
    meta: { title: "faceid.nav.terminals", perm: "attendance.manage" },
  },
  {
    path: "faceid/settings",
    name: "faceid.settings",
    component: () => lazy().then((m) => m.pages.settings()),
    meta: { title: "faceid.nav.settings", perm: "attendance.manage" },
  },
];
