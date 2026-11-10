/**
 * Routes of the people lifecycle, children of /c/:companyId (plan §13.4): discipline,
 * suspensions, leaving (terminations) and job changes; the org chart, equipment and reviews are
 * calm "coming soon" pages until they are built. Every page loads lazily.
 */
import type { RouteRecordRaw } from "vue-router";

const soon = () => import("./pages/ComingSoonPage.vue");

export const routes: RouteRecordRaw[] = [
  {
    path: "lifecycle/discipline",
    name: "lifecycle.discipline",
    component: () => import("./pages/DisciplinePage.vue"),
    meta: { title: "lifecycle.nav.discipline", perm: ["hr.discipline", "hr.view"] },
  },
  {
    path: "lifecycle/suspensions",
    name: "lifecycle.suspensions",
    component: () => import("./pages/SuspensionsPage.vue"),
    meta: { title: "lifecycle.nav.suspensions", perm: ["hr.suspend", "hr.view"] },
  },
  { path: "lifecycle/org", name: "lifecycle.org", component: soon, props: { page: "org" }, meta: { title: "lifecycle.nav.org", perm: "hr.view" } },
  {
    path: "lifecycle/terminations",
    name: "lifecycle.terminations",
    component: () => import("./pages/TerminationsPage.vue"),
    meta: { title: "lifecycle.nav.terminations", perm: ["hr.terminate", "hr.view"] },
  },
  {
    path: "lifecycle/job-changes",
    name: "lifecycle.changes",
    component: () => import("./pages/JobChangesPage.vue"),
    meta: { title: "lifecycle.nav.changes", perm: ["hr.manage", "hr.view"] },
  },
  {
    path: "lifecycle/equipment",
    name: "lifecycle.equipment",
    component: soon,
    props: { page: "equipment" },
    meta: { title: "lifecycle.nav.equipment", perm: ["assets.manage", "hr.manage"] },
  },
  { path: "lifecycle/reviews", name: "lifecycle.reviews", component: soon, props: { page: "reviews" }, meta: { title: "lifecycle.nav.reviews", perm: "reviews.manage" } },
];
