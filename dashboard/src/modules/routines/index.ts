/**
 * Routines (plan §6.1, package B): work a routine gives each person automatically, every day it's
 * due, kept apart from one-off tasks. Today (each person's run, with proof, and who was skipped),
 * History (completion per routine per day, per person), To confirm (routine work waiting for a
 * check, by routine and day) and the routines themselves, with onboarding templates for new people.
 */
import { ClipboardCheck, GraduationCap, Plus, Repeat } from "@lucide/vue";

import { defineModule } from "@/core/modules";
import { counter } from "@/core/pulse";

import { routes } from "./routes";

export default defineModule({
  id: "routines",
  group: "work",
  order: 30,
  icon: Repeat,
  title: "routines.title",
  perm: ["tasks.templates", "tasks.view_all", "tasks.confirm"],
  hotkey: "r",
  routes,
  nav: [
    { key: "today", title: "routines.nav.today", to: "routines", perm: "tasks.view_all", exact: true },
    { key: "history", title: "routines.nav.history", to: "routines/history", perm: "tasks.view_all" },
    { key: "confirm", title: "routines.nav.confirm", to: "routines/confirm", perm: "tasks.confirm", badge: counter("tasks.routine_review") },
    { key: "all", title: "routines.nav.all", to: "routines/all", perm: "tasks.templates" },
  ],
  badge: counter("tasks.routine_review"),
  // apps.tasks' keys: tasks.routines (a routine changed), tasks.tasks (its work moved) and the
  // tasks.routine_review badge.
  invalidates: ["tasks"],
  commands: (ctx) => [
    {
      id: "routines.new",
      title: ctx.t("routines.cmd.new"),
      icon: Plus,
      keywords: ["routine", "muntazam", "регулярн", "daily"],
      perm: "tasks.templates",
      run: () => ctx.go("routines/all?new=1"),
    },
    {
      id: "routines.confirm",
      title: ctx.t("routines.cmd.confirm"),
      icon: ClipboardCheck,
      keywords: ["confirm", "tasdiqlash", "подтвердить", "routine"],
      perm: "tasks.confirm",
      run: () => ctx.go("routines/confirm"),
    },
    {
      id: "routines.onboarding",
      title: ctx.t("routines.cmd.onboarding"),
      icon: GraduationCap,
      keywords: ["onboarding", "new staff", "yangi xodim", "адаптация"],
      perm: "tasks.templates",
      run: () => ctx.go("routines/onboarding"),
    },
  ],
  messages: async () => {
    const [uz, ru, en] = await Promise.all([import("./i18n/uz.json"), import("./i18n/ru.json"), import("./i18n/en.json")]);
    return { uz: uz.default, ru: ru.default, en: en.default };
  },
});
