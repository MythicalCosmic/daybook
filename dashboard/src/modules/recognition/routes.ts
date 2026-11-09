/** Routes of recognition, children of /c/:companyId. Pages load lazily through lazy.ts. */
import type { RouteRecordRaw } from "vue-router";

import { READ } from "./lib";

export const lazy = () => import("./lazy");

export const routes: RouteRecordRaw[] = [
  {
    path: "recognition",
    name: "recognition.leaderboard",
    component: () => lazy().then((m) => m.pages.leaderboard()),
    meta: { title: "recognition.nav.leaderboard", perm: READ, feature: "recognition" },
  },
  {
    path: "recognition/kudos",
    name: "recognition.kudos",
    component: () => lazy().then((m) => m.pages.kudos()),
    meta: { title: "recognition.nav.kudos", perm: READ, feature: "recognition" },
  },
  {
    path: "recognition/badges",
    name: "recognition.badges",
    component: () => lazy().then((m) => m.pages.badges()),
    meta: { title: "recognition.nav.badges", perm: READ, feature: "recognition" },
  },
];
