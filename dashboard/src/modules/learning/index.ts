/**
 * Training (O‘qitish): courses that mix video lessons, knowledge base pages and quizzes, made
 * mandatory for positions or branches with a deadline and a renewal; lessons with an uploaded
 * video or a YouTube link and "who watched what"; the people × mandatory courses grid and each
 * person's training (docs/PLAN-LEARNING.md §11 Q1). Quizzes and the tutor are the `quizzes`
 * module; both fill the extension points `learning.overview.cards` and `learning.person.panels`.
 * Behind the `learning` switch.
 */
import { BookOpenCheck, GraduationCap, Plus, Users } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";

import { lazy, routes } from "./routes";

const READ = ["learning.view", "learning.manage"] as const;

export default defineModule({
  id: "learning",
  group: "people",
  order: 55,
  icon: GraduationCap,
  title: "learning.title",
  perm: READ,
  feature: "learning",
  hotkey: "l",
  routes,
  nav: [
    { key: "overview", title: "learning.nav.overview", to: "learning" },
    { key: "courses", title: "learning.nav.courses", to: "learning/courses" },
    { key: "lessons", title: "learning.nav.lessons", to: "learning/lessons" },
    { key: "people", title: "learning.nav.people", to: "learning/people" },
  ],
  invalidates: ["learning.courses", "learning.lessons"],
  commands: (ctx) => [
    {
      id: "learning.newCourse",
      title: ctx.t("learning.cmd.newCourse"),
      icon: Plus,
      keywords: ["kurs", "курс", "course", "training", "o‘qitish", "обучение"],
      perm: "learning.manage",
      run: () => ctx.go("learning/courses?new=1"),
    },
    {
      id: "learning.newLesson",
      title: ctx.t("learning.cmd.newLesson"),
      icon: BookOpenCheck,
      keywords: ["dars", "урок", "lesson", "video", "видео"],
      perm: "learning.manage",
      run: () => ctx.go("learning/lessons?new=1"),
    },
    {
      id: "learning.people",
      title: ctx.t("learning.cmd.people"),
      icon: Users,
      keywords: ["majburiy", "обязательное", "mandatory", "kechikkan", "просрочено", "late"],
      perm: READ,
      run: () => ctx.go("learning/people"),
    },
  ],
  // Today: how much mandatory training is done and who is late with it.
  widgets: [
    {
      id: "learning.compliance",
      span: 1,
      order: 62,
      kind: "card",
      perm: READ,
      feature: "learning",
      component: defineAsyncComponent(() => import("./widgets/ComplianceWidget.vue")),
    },
  ],
  settings: [
    {
      id: "learning",
      title: "learning.settings.title",
      perm: "learning.manage",
      feature: "learning",
      order: 48,
      icon: GraduationCap,
      component: defineAsyncComponent(() => lazy().then((m) => m.panels.settings())),
    },
  ],
  // `startapp=learn_<course id>` opens a course, `learning` the overview.
  deepLinks: {
    learning: () => "learning",
    learn: (id) => (/^\d+$/.test(id) ? `learning/courses/${id}` : "learning/courses"),
  },
  messages: (language) => import(`./i18n/${language}.json`),
});
