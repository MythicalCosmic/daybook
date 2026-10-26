/** Routes of People, children of /c/:companyId (plan §6.1). Pages load lazily. */
import type { RouteRecordRaw } from "vue-router";

export const routes: RouteRecordRaw[] = [
  {
    path: "people",
    name: "people.team",
    component: () => import("./pages/TeamPage.vue"),
    meta: { title: "people.team.title" },
  },
  {
    path: "people/departments",
    name: "people.departments",
    component: () => import("./pages/DepartmentsPage.vue"),
    meta: { title: "people.nav.departments" },
  },
  {
    path: "people/requests",
    name: "people.requests",
    component: () => import("./pages/RequestsPage.vue"),
    meta: { title: "people.nav.requests", perm: "members.approve" },
  },
  {
    path: "people/roles",
    name: "people.roles",
    component: () => import("./pages/RolesPage.vue"),
    meta: { title: "people.nav.roles", perm: "roles.manage" },
  },
  {
    path: "people/positions",
    name: "people.positions",
    component: () => import("./pages/PositionsPage.vue"),
    meta: { title: "people.nav.positions", perm: "positions.manage" },
  },
  {
    path: "people/:memberId(\\d+)/offboard",
    name: "people.offboard",
    component: () => import("./pages/OffboardPage.vue"),
    meta: { title: "people.offboard.title", perm: "members.manage" },
  },
  {
    path: "people/:memberId(\\d+)/:tab?",
    name: "people.person",
    component: () => import("./pages/PersonPage.vue"),
    meta: { title: "people.person.title" },
  },
];
