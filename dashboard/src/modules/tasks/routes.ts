/** Routes of tasks, children of /c/:companyId (plan §6.1). Pages load lazily. */
import type { RouteRecordRaw } from "vue-router";

export const routes: RouteRecordRaw[] = [
  {
    path: "tasks",
    name: "tasks.list",
    component: () => import("./pages/TasksPage.vue"),
    meta: { title: "tasks.title", perm: "tasks.view_all" },
  },
  {
    path: "tasks/reviews",
    name: "tasks.reviews",
    component: () => import("./pages/ReviewsPage.vue"),
    meta: { title: "tasks.reviews.title", perm: ["tasks.confirm", "tasks.view_all", "tasks.assign"] },
  },
  {
    path: "tasks/photos",
    name: "tasks.photos",
    component: () => import("./pages/PhotoWallPage.vue"),
    meta: { title: "tasks.photos.title", perm: "tasks.view_all" },
  },
];
