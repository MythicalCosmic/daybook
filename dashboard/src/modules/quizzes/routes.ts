/** Routes of quizzes, the question bank, checks, skills and the tutor, children of
 * /c/:companyId. Pages load lazily through lazy.ts. */
import type { RouteRecordRaw } from "vue-router";

export const lazy = () => import("./lazy");

export const READ = ["learning.view", "learning.manage"] as const;
export const MANAGE = "learning.manage";

export const routes: RouteRecordRaw[] = [
  {
    path: "learning/quizzes",
    name: "quizzes.list",
    component: () => lazy().then((m) => m.pages.quizzes()),
    meta: { title: "quizzes.nav.quizzes", perm: READ, feature: "learning" },
  },
  {
    path: "learning/quizzes/:quizId(\\d+)",
    name: "quizzes.quiz",
    component: () => lazy().then((m) => m.pages.quiz()),
    meta: { title: "quizzes.quiz.title", perm: READ, feature: "learning" },
  },
  {
    path: "learning/questions",
    name: "quizzes.questions",
    component: () => lazy().then((m) => m.pages.questions()),
    meta: { title: "quizzes.nav.questions", perm: MANAGE, feature: "learning" },
  },
  {
    path: "learning/checks",
    name: "quizzes.checks",
    component: () => lazy().then((m) => m.pages.checks()),
    meta: { title: "quizzes.nav.checks", perm: READ, feature: "learning" },
  },
  {
    path: "learning/skills",
    name: "quizzes.skills",
    component: () => lazy().then((m) => m.pages.skills()),
    meta: { title: "quizzes.nav.skills", perm: READ, feature: "learning" },
  },
  {
    path: "learning/tutor",
    name: "quizzes.tutor",
    component: () => lazy().then((m) => m.pages.tutor()),
    meta: { title: "quizzes.nav.tutor", perm: READ, feature: "learning" },
  },
];
