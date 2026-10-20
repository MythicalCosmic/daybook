/**
 * Routes of the inbox, children of /c/:companyId (plan §6.1). Components load lazily, so the page's
 * code arrives only when it is opened (and is prefetched when the pointer rests on the nav link).
 */
import type { RouteRecordRaw } from "vue-router";

export const routes: RouteRecordRaw[] = [
  {
    path: "inbox",
    name: "inbox.page",
    component: () => import("./pages/InboxPage.vue"),
    meta: { title: "inbox.title" },
  },
];
