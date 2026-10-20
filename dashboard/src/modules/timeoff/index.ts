/**
 * Time off (plan §6.2, package C; L adds balances and leave types): the month calendar with leave
 * bars and holidays, requests to decide, time off recorded for someone (past days allowed),
 * revoking approved time off, and the holidays editor. Adds a "Time off" tab to Person 360.
 */
import { CalendarPlus, PartyPopper, TreePalm } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";
import { counter } from "@/core/pulse";

import { routes } from "./routes";

export default defineModule({
  id: "timeoff",
  group: "people",
  order: 30,
  icon: TreePalm,
  title: "timeoff.title",
  perm: ["time_off.approve", "time_off.manage"],
  badge: counter("timeoff.pending"),
  routes,
  nav: [
    { key: "calendar", title: "timeoff.nav.calendar", to: "time-off", perm: "time_off.approve", exact: true, badge: counter("timeoff.pending") },
    { key: "holidays", title: "timeoff.nav.holidays", to: "time-off/holidays", perm: "time_off.approve" },
  ],
  invalidates: ["timeoff"],
  commands: (ctx) => [
    {
      id: "timeoff.record",
      title: ctx.t("timeoff.cmd.record"),
      icon: CalendarPlus,
      perm: "time_off.approve",
      keywords: ["sick", "leave", "kasal", "больничный", "отпуск", "ta’til"],
      run: () => ctx.go("time-off?record=1"),
    },
    {
      id: "timeoff.holiday",
      title: ctx.t("timeoff.cmd.holiday"),
      icon: PartyPopper,
      perm: "time_off.approve",
      keywords: ["holiday", "bayram", "праздник"],
      run: () => ctx.go("time-off/holidays?add=1"),
    },
  ],
  personTabs: [
    {
      id: "time-off",
      title: "timeoff.tab",
      perm: "time_off.approve",
      order: 60,
      component: defineAsyncComponent(() => import("./components/PersonTimeOffTab.vue")),
    },
  ],
  widgets: [
    {
      id: "timeoff.today",
      span: 1,
      order: 65,
      kind: "card",
      perm: "time_off.approve",
      component: defineAsyncComponent(() => import("./widgets/OffTodayWidget.vue")),
    },
  ],
  deepLinks: {
    timeoff: (id) => (/^\d+$/.test(id) ? `time-off?request=${id}` : "time-off"),
  },
  messages: async () => {
    const [uz, ru, en] = await Promise.all([import("./i18n/uz.json"), import("./i18n/ru.json"), import("./i18n/en.json")]);
    return { uz: uz.default, ru: ru.default, en: en.default };
  },
});
