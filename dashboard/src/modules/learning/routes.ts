/** Routes of training (courses and lessons), children of /c/:companyId; pages load lazily. */
import type { RouteRecordRaw } from "vue-router";

export const lazy = () => import("./lazy");

const READ = ["learning.view", "learning.manage"] as const;

export const routes: RouteRecordRaw[] = [
  {
    path: "learning",
    name: "learning.overview",
    component: () => lazy().then((m) => m.pages.overview()),
    meta: { title: "learning.nav.overview", perm: READ, feature: "learning" },
  },
  {
    path: "learning/courses",
    name: "learning.courses",
    component: () => lazy().then((m) => m.pages.courses()),
    meta: { title: "learning.nav.courses", perm: READ, feature: "learning" },
  },
  {
    path: "learning/courses/:courseId(\\d+)",
    name: "learning.course",
    component: () => lazy().then((m) => m.pages.course()),
    meta: { title: "learning.course.title", perm: READ, feature: "learning" },
  },
  {
    path: "learning/lessons",
    name: "learning.lessons",
    component: () => lazy().then((m) => m.pages.lessons()),
    meta: { title: "learning.nav.lessons", perm: READ, feature: "learning" },
  },
  {
    path: "learning/lessons/:lessonId(\\d+)",
    name: "learning.lesson",
    component: () => lazy().then((m) => m.pages.lesson()),
    meta: { title: "learning.lesson.title", perm: READ, feature: "learning" },
  },
  {
    path: "learning/people",
    name: "learning.people",
    component: () => lazy().then((m) => m.pages.people()),
    meta: { title: "learning.nav.people", perm: READ, feature: "learning" },
  },
  {
    path: "learning/people/:memberId(\\d+)",
    name: "learning.person",
    component: () => lazy().then((m) => m.pages.person()),
    meta: { title: "learning.person.title", perm: READ, feature: "learning" },
  },
];
