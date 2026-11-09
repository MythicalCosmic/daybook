/**
 * Quizzes, the question bank, regular checks, the skill matrix and the tutor (docs/PLAN-LEARNING.md
 * §11, package Q2): quizzes with their pass rate, an editor, a learner's preview and the results
 * (attempts, the score distribution, the hardest questions, reset); the bank with an editor per
 * kind of question and live checks, and "Write questions from…" a page; checks with their rounds;
 * people × topics; the tutor's suggestions, last report and chat. Behind the "learning" switch.
 * It also fills two slots of the learning module (a person's skills and quiz history, the
 * overview's suggestions and weakest topics) and adds the question of the day's settings.
 */
import { ClipboardCheck, GraduationCap, ListChecks, MessageCircleQuestion, PenLine, Sparkles } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";

import { lazy, MANAGE, READ, routes } from "./routes";

export default defineModule({
  id: "quizzes",
  group: "people",
  order: 56,
  icon: ListChecks,
  title: "quizzes.title",
  perm: READ,
  feature: "learning",
  hotkey: "q",
  routes,
  nav: [
    { key: "quizzes", title: "quizzes.nav.quizzes", to: "learning/quizzes" },
    { key: "questions", title: "quizzes.nav.questions", to: "learning/questions", perm: MANAGE },
    { key: "checks", title: "quizzes.nav.checks", to: "learning/checks" },
    { key: "skills", title: "quizzes.nav.skills", to: "learning/skills" },
    { key: "tutor", title: "quizzes.nav.tutor", to: "learning/tutor" },
  ],
  invalidates: ["learning.quizzes", "learning.checks", "learning.suggestions"],
  commands: (ctx) => [
    {
      id: "quizzes.newQuestion",
      title: ctx.t("quizzes.cmd.newQuestion"),
      icon: PenLine,
      keywords: ["savol", "вопрос", "question", "test", "тест"],
      perm: MANAGE,
      run: () => ctx.go("learning/questions?new=1"),
    },
    {
      id: "quizzes.newQuiz",
      title: ctx.t("quizzes.cmd.newQuiz"),
      icon: ClipboardCheck,
      keywords: ["test", "тест", "quiz", "imtihon", "экзамен"],
      perm: MANAGE,
      run: () => ctx.go("learning/quizzes?new=1"),
    },
    {
      id: "quizzes.skills",
      title: ctx.t("quizzes.cmd.skills"),
      icon: GraduationCap,
      keywords: ["ko‘nikma", "навыки", "skills", "matritsa", "матрица"],
      perm: READ,
      run: () => ctx.go("learning/skills"),
    },
    {
      id: "quizzes.tutor",
      title: ctx.t("quizzes.cmd.tutor"),
      icon: Sparkles,
      keywords: ["ustoz", "наставник", "tutor", "taklif", "предложения"],
      perm: READ,
      run: () => ctx.go("learning/tutor"),
    },
  ],
  settings: [
    {
      id: "quizzes-daily",
      title: "quizzes.daily.title",
      perm: MANAGE,
      feature: "learning",
      order: 58,
      icon: MessageCircleQuestion,
      component: defineAsyncComponent(() => lazy().then((m) => m.parts.dailySettings())),
    },
  ],
  extensions: {
    "learning.person.panels": [defineAsyncComponent(() => lazy().then((m) => m.parts.personPanel()))],
    "learning.overview.cards": [defineAsyncComponent(() => lazy().then((m) => m.parts.overviewCards()))],
  },
  // `startapp=quiz_<id>` opens a quiz's results, `tutor` the tutor's page.
  deepLinks: {
    quiz: (id) => (/^\d+$/.test(id) ? `learning/quizzes/${id}` : "learning/quizzes"),
    tutor: () => "learning/tutor",
  },
  messages: (language) => import(`./i18n/${language}.json`),
});
