/**
 * Routes of projects, children of /c/:companyId (plan §13.3; paths from core/catalog.ts). The
 * project page keeps its tab in the path (`projects/12/board`), the open card in `?card=`.
 */
import type { RouteRecordRaw } from "vue-router";

export const routes: RouteRecordRaw[] = [
  {
    path: "projects",
    name: "projects.index",
    component: () => import("./pages/ProjectsPage.vue"),
    meta: { title: "projects.title" },
  },
  {
    path: "projects/roadmap",
    name: "projects.roadmap",
    component: () => import("./pages/RoadmapPage.vue"),
    meta: { title: "projects.roadmap.title" },
  },
  {
    path: "projects/:projectId(\\d+)/:tab?",
    name: "projects.project",
    component: () => import("./pages/ProjectPage.vue"),
    meta: { title: "projects.project.title" },
  },
];
