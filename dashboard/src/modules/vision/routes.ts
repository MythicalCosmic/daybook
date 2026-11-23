/**
 * Routes of Ko‘z, children of /c/:companyId: the day's overview, the live view (and its TV mode,
 * `?tv=1`), alerts, moments worth a look, cameras and boxes with the zone editor, and the settings.
 * Pages load lazily through lazy.ts.
 */
import type { RouteRecordRaw } from "vue-router";

/** One import for every page (lazy.ts explains why). */
export const lazy = () => import("./lazy");

export const routes: RouteRecordRaw[] = [
  {
    path: "vision",
    name: "vision.overview",
    component: () => lazy().then((m) => m.pages.overview()),
    meta: { title: "vision.nav.overview" },
  },
  {
    path: "vision/live",
    name: "vision.live",
    component: () => lazy().then((m) => m.pages.live()),
    meta: { title: "vision.nav.live" },
  },
  {
    path: "vision/alerts",
    name: "vision.alerts",
    component: () => lazy().then((m) => m.pages.alerts()),
    meta: { title: "vision.nav.alerts" },
  },
  {
    path: "vision/review",
    name: "vision.review",
    component: () => lazy().then((m) => m.pages.review()),
    meta: { title: "vision.nav.review", perm: "vision.video" },
  },
  {
    path: "vision/cameras",
    name: "vision.cameras",
    component: () => lazy().then((m) => m.pages.cameras()),
    meta: { title: "vision.nav.cameras", perm: "vision.manage" },
  },
  {
    path: "vision/cameras/:cameraId(\\d+)/zones",
    name: "vision.zones",
    component: () => lazy().then((m) => m.pages.zones()),
    meta: { title: "vision.zones.title", perm: "vision.manage" },
  },
  {
    path: "vision/settings",
    name: "vision.settings",
    component: () => lazy().then((m) => m.pages.settings()),
    meta: { title: "vision.nav.settings" },
  },
];
