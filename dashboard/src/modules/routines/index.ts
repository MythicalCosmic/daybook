/**
 * Routines (plan §6.1, package B): daily templates with who gets them, a "who gets it tomorrow"
 * preview and 30-day completion, plus onboarding templates for new people.
 */
import { GraduationCap, Plus, Repeat } from "@lucide/vue";

import { defineModule } from "@/core/modules";

import { routes } from "./routes";

export default defineModule({
  id: "routines",
  group: "work",
  order: 30,
  icon: Repeat,
  title: "routines.title",
  perm: "tasks.templates",
  hotkey: "r",
  routes,
  nav: [{ key: "all", title: "routines.title", to: "routines" }],
  // apps.tasks registers "tasks.routines" (a routine changed) and "tasks.tasks" (stats move).
  invalidates: ["tasks.routines", "tasks.tasks"],
  commands: (ctx) => [
    {
      id: "routines.new",
      title: ctx.t("routines.cmd.new"),
      icon: Plus,
      keywords: ["routine", "daily", "kundalik", "ежедневн"],
      run: () => ctx.go("routines?new=1"),
    },
    {
      id: "routines.onboarding",
      title: ctx.t("routines.cmd.onboarding"),
      icon: GraduationCap,
      keywords: ["onboarding", "new staff", "yangi xodim", "адаптация"],
      run: () => ctx.go("routines/onboarding"),
    },
  ],
  messages: (language) => import(`./i18n/${language}.json`),
});
