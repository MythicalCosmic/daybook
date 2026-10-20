/**
 * Every lazily loaded piece of the attendance module, behind one import.
 *
 * The registry (index.ts, routes.ts) is part of the first bundle every page loads. Each `import()`
 * written there carries its chunk's preload list into that bundle, so the module's ten lazy pieces
 * would add a few kilobytes for everyone. Written here instead, those lists live in this small chunk,
 * which the registry loads with a single `import("./lazy")` the first time any piece is needed.
 */
export const pages = {
  today: () => import("./pages/TodayPage.vue"),
  timesheet: () => import("./pages/TimesheetPage.vue"),
  roster: () => import("./pages/RosterPage.vue"),
  schedules: () => import("./pages/SchedulesPage.vue"),
  swaps: () => import("./pages/SwapsPage.vue"),
  corrections: () => import("./pages/CorrectionsPage.vue"),
};

export const widgets = {
  present: () => import("./widgets/PresentWidget.vue"),
  strip: () => import("./widgets/StripWidget.vue"),
};

export const panels = {
  settings: () => import("./components/SettingsForm.vue"),
  person: () => import("./components/PersonMonth.vue"),
};
