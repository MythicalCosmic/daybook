/**
 * Reminders (plan §6.1, package B): policies with a visual timeline and texts per step, the
 * reminder log, the blocked-bot list, and the "Reminder defaults" settings panel.
 */
import { BellRing, ScrollText } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";

import { routes } from "./routes";

export default defineModule({
  id: "reminders",
  group: "work",
  order: 40,
  icon: BellRing,
  title: "reminders.title",
  perm: "reminders.configure",
  routes,
  nav: [{ key: "policies", title: "reminders.title", to: "reminders" }],
  // apps.reminders' "reminders.policies"; the log and blocked list move with tasks.
  invalidates: ["reminders", "tasks.tasks"],
  commands: (ctx) => [
    {
      id: "reminders.policies",
      title: ctx.t("reminders.cmd.policies"),
      icon: BellRing,
      keywords: ["reminder", "eslatma", "напоминание", "policy"],
      run: () => ctx.go("reminders"),
    },
    {
      id: "reminders.log",
      title: ctx.t("reminders.cmd.log"),
      icon: ScrollText,
      keywords: ["log", "jurnal", "журнал"],
      run: () => ctx.go("reminders?tab=log"),
    },
  ],
  settings: [
    {
      id: "reminders.defaults",
      title: "reminders.defaults.title",
      perm: "reminders.configure",
      order: 60,
      icon: BellRing,
      component: defineAsyncComponent(() => import("./components/DefaultsPanel.vue")),
    },
  ],
  messages: async () => {
    const [uz, ru, en] = await Promise.all([import("./i18n/uz.json"), import("./i18n/ru.json"), import("./i18n/en.json")]);
    return { uz: uz.default, ru: ru.default, en: en.default };
  },
});
