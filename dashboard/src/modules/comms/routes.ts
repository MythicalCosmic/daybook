/** Routes of announcements, children of /c/:companyId (plan §6.1). */
import type { RouteRecordRaw } from "vue-router";

export const routes: RouteRecordRaw[] = [
  {
    path: "announcements",
    name: "comms.list",
    component: () => import("./pages/AnnouncementsPage.vue"),
    meta: { title: "comms.nav.announcements" },
  },
  {
    path: "announcements/new",
    name: "comms.compose",
    component: () => import("./pages/ComposePage.vue"),
    meta: { title: "comms.compose.title" },
  },
  {
    path: "announcements/:announcementId(\\d+)",
    name: "comms.detail",
    component: () => import("./pages/AnnouncementPage.vue"),
    meta: { title: "comms.detail.title" },
  },
];
