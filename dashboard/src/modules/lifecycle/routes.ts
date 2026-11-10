/**
 * Routes of the people lifecycle, children of /c/:companyId (plan §13.4): discipline,
 * suspensions, the org chart, leaving (terminations), job changes, equipment and reviews.
 * Every page loads lazily.
 */
import type { RouteRecordRaw } from "vue-router";

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
  {
    path: "lifecycle/org",
    name: "lifecycle.org",
    component: () => import("./org/OrgChartPage.vue"),
    meta: { title: "lifecycle.nav.org", perm: ["hr.view", "hr.manage"] },
  },
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
    component: () => import("./equipment/EquipmentPage.vue"),
    meta: { title: "lifecycle.nav.equipment", perm: ["assets.manage", "hr.manage"] },
  },
  // Performance reviews: the rounds, a round, one person's review.
  { path: "lifecycle/reviews", name: "lifecycle.reviews", component: () => import("./pages/ReviewsPage.vue"), meta: { title: "lifecycle.nav.reviews", perm: "reviews.manage" } },
  {
    path: "lifecycle/reviews/:roundId(\\d+)",
    name: "lifecycle.review-round",
    component: () => import("./pages/ReviewRoundPage.vue"),
    meta: { title: "lifecycle.nav.reviews", perm: "reviews.manage" },
  },
  {
    path: "lifecycle/reviews/:roundId(\\d+)/:reviewId(\\d+)",
    name: "lifecycle.review",
    component: () => import("./pages/ReviewPage.vue"),
    meta: { title: "lifecycle.nav.reviews", perm: "reviews.manage" },
  },
];
