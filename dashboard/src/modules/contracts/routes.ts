/** Routes of the contracts vault, children of /c/:companyId. Pages load lazily through lazy.ts. */
import type { RouteRecordRaw } from "vue-router";

export const lazy = () => import("./lazy");

export const routes: RouteRecordRaw[] = [
  {
    path: "contracts",
    name: "contracts.list",
    component: () => lazy().then((m) => m.pages.list()),
    meta: { title: "contracts.title", perm: "finance.view" },
  },
  {
    path: "contracts/:contractId(\\d+)",
    name: "contracts.one",
    component: () => lazy().then((m) => m.pages.one()),
    meta: { title: "contracts.one.title", perm: "finance.view" },
  },
];
