/**
 * The company calendar (plan §13.5, package Q): every module's dates on one calendar (month, week
 * and agenda views with source toggles) and the company's own events with attendees, answers and
 * bot reminders. Pages, the event dialog and the widget load on first use.
 */
import { CalendarDays, CalendarPlus } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";

import { routes } from "./routes";

export default defineModule({
  id: "agenda",
  group: "comms",
  order: 30,
  icon: CalendarDays,
  title: "agenda.title",
  hotkey: "c",
  routes,
  nav: [{ key: "calendar", title: "agenda.title", to: "calendar" }],
  // The calendar shows dates from many modules: refresh when any of them changes.
  invalidates: ["agenda", "timeoff", "hr", "lifecycle", "attendance", "payroll", "finance", "projects", "tasks", "crm"],
  commands: (ctx) => [
    {
      id: "agenda.new-event",
      title: ctx.t("agenda.cmd.newEvent"),
      icon: CalendarPlus,
      perm: "agenda.manage",
      keywords: ["meeting", "event", "yig‘ilish", "tadbir", "встреча", "событие"],
      run: () => ctx.go("calendar?new=1"),
    },
    {
      id: "agenda.today",
      title: ctx.t("agenda.cmd.today"),
      icon: CalendarDays,
      keywords: ["calendar", "taqvim", "календарь"],
      run: () => ctx.go("calendar?view=agenda"),
    },
  ],
  searchResults: {
    "agenda.event": defineAsyncComponent(() => import("./components/SearchHit.vue")),
  },
  widgets: [
    {
      id: "agenda.upcoming",
      span: 2,
      order: 60,
      kind: "card",
      component: defineAsyncComponent(() => import("./widgets/UpcomingWidget.vue")),
    },
  ],
  settings: [
    {
      id: "agenda",
      title: "agenda.settings.title",
      perm: "agenda.manage",
      icon: CalendarDays,
      component: defineAsyncComponent(() => import("./components/AgendaSettingsPanel.vue")),
    },
  ],
  // Telegram `startapp=event_12` opens the event.
  deepLinks: {
    event: (argument) => (/^\d+$/.test(argument) ? `calendar?event=${argument}` : "calendar"),
  },
  messages: async () => {
    const [uz, ru, en] = await Promise.all([import("./i18n/uz.json"), import("./i18n/ru.json"), import("./i18n/en.json")]);
    return { uz: uz.default, ru: ru.default, en: en.default };
  },
});
