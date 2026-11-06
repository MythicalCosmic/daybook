/** Routes of fixed assets, children of /c/:companyId. Pages load lazily through lazy.ts. */
import type { RouteRecordRaw } from "vue-router";

export const lazy = () => import("./lazy");

const READ = ["assets.manage", "finance.view"] as const;

export const routes: RouteRecordRaw[] = [
  { path: "assets", redirect: (to) => ({ path: `/c/${String(to.params.companyId)}/assets/items` }) },
  {
    path: "assets/items",
    name: "assets.items",
    component: () => lazy().then((m) => m.pages.register()),
    meta: { title: "assets.nav.items", perm: READ },
  },
  {
    path: "assets/items/:assetId(\\d+)",
    name: "assets.item",
    component: () => lazy().then((m) => m.pages.asset()),
    meta: { title: "assets.item.title", perm: READ },
  },
  {
    path: "assets/depreciation",
    name: "assets.depreciation",
    component: () => lazy().then((m) => m.pages.depreciation()),
    meta: { title: "assets.nav.depreciation", perm: READ },
  },
  {
    path: "assets/planning",
    name: "assets.planning",
    component: () => lazy().then((m) => m.pages.planning()),
    meta: { title: "assets.nav.planning", perm: READ },
  },
  {
    path: "assets/counts",
    name: "assets.counts",
    component: () => lazy().then((m) => m.pages.counts()),
    meta: { title: "assets.nav.counts", perm: READ },
  },
  {
    path: "assets/permits",
    name: "assets.permits",
    component: () => lazy().then((m) => m.pages.permits()),
    meta: { title: "assets.nav.permits", perm: READ },
  },
];
