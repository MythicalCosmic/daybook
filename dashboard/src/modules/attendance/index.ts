/**
 * Attendance (package F, plan §1.8, §4.9, §6.2): the live "who's in" board, the monthly timesheet,
 * the roster builder (week grid, drag shifts, templates, publish), schedules, and the swaps and
 * corrections inboxes. Also an Overview KPI and strip, the attendance settings panel and the
 * Person 360 tab. Kept tiny: pages, widgets and the API load on first use.
 */
import { CalendarClock, CalendarPlus, Clock3, Fingerprint, Send } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";
import { counter } from "@/core/pulse";

import { lazy, routes } from "./routes";

export default defineModule({
  id: "attendance",
  group: "people",
  order: 20,
  icon: Fingerprint,
  title: "attendance.title",
  perm: "attendance.view",
  feature: "attendance",
  hotkey: "a",
  // People whose shift started and who haven't checked in.
  badge: counter("attendance.not_in"),
  routes,
  nav: [
    { key: "today", title: "attendance.nav.today", to: "attendance", exact: true },
    { key: "timesheet", title: "attendance.nav.timesheet", to: "attendance/timesheet" },
    { key: "roster", title: "attendance.nav.roster", to: "attendance/roster" },
    { key: "schedules", title: "attendance.nav.schedules", to: "attendance/schedules", perm: "attendance.manage" },
    { key: "swaps", title: "attendance.nav.swaps", to: "attendance/swaps", perm: "attendance.manage", badge: counter("attendance.swaps") },
    {
      key: "corrections",
      title: "attendance.nav.corrections",
      to: "attendance/corrections",
      perm: "attendance.manage",
      badge: counter("attendance.corrections"),
    },
  ],
  // Check-ins, roster changes, schedules, swaps and corrections (apps/attendance/hooks.py).
  invalidates: ["attendance"],
  commands: (ctx) => [
    {
      id: "attendance.board",
      title: ctx.t("attendance.cmd.board"),
      icon: Clock3,
      keywords: ["who", "kim", "кто", "present", "keldi"],
      run: () => ctx.go("attendance"),
    },
    {
      id: "attendance.addShift",
      title: ctx.t("attendance.cmd.addShift"),
      icon: CalendarPlus,
      keywords: ["roster", "jadval", "смена", "smena"],
      perm: "attendance.manage",
      run: () => ctx.go("attendance/roster?add=1"),
    },
    {
      id: "attendance.publish",
      title: ctx.t("attendance.cmd.publish"),
      icon: Send,
      keywords: ["roster", "publish", "e’lon", "опубликовать"],
      perm: "attendance.manage",
      run: () => ctx.go("attendance/roster?publish=1"),
    },
    {
      id: "attendance.timesheet",
      title: ctx.t("attendance.cmd.timesheet"),
      icon: CalendarClock,
      keywords: ["tabel", "табель", "hours", "soat"],
      run: () => ctx.go("attendance/timesheet"),
    },
  ],
  widgets: [
    {
      id: "attendance.kpi.present",
      span: 1,
      order: 20,
      kind: "kpi",
      perm: "attendance.view",
      feature: "attendance",
      component: defineAsyncComponent(() => lazy().then((m) => m.widgets.present())),
    },
    {
      id: "attendance.strip",
      span: 2,
      order: 60,
      kind: "chart",
      perm: "attendance.view",
      feature: "attendance",
      component: defineAsyncComponent(() => lazy().then((m) => m.widgets.strip())),
    },
  ],
  settings: [
    {
      id: "attendance",
      title: "attendance.settings.title",
      perm: "attendance.manage",
      feature: "attendance",
      order: 40,
      icon: Fingerprint,
      component: defineAsyncComponent(() => lazy().then((m) => m.panels.settings())),
    },
  ],
  personTabs: [
    {
      id: "attendance",
      title: "attendance.personTab",
      perm: "attendance.view",
      feature: "attendance",
      order: 30,
      component: defineAsyncComponent(() => lazy().then((m) => m.panels.person())),
    },
  ],
  // Telegram `startapp=attendance`, `roster_2026-10-26`, `swaps`, `corrections`.
  deepLinks: {
    attendance: () => "attendance",
    roster: (week) => (week ? `attendance/roster?week=${week}` : "attendance/roster"),
    swaps: () => "attendance/swaps",
    corrections: () => "attendance/corrections",
  },
  messages: (language) => import(`./i18n/${language}.json`),
});
