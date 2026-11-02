/**
 * Every lazily loaded piece of the payroll module, behind one import.
 *
 * The registry (index.ts, routes.ts) is part of the first bundle every page loads, and each
 * `import()` written there carries its chunk's preload list into that bundle. Written here
 * instead, those lists live in this small chunk, which the registry loads with a single
 * `import("./lazy")` the first time any payroll piece is needed (attendance does the same).
 */
export const pages = {
  runs: () => import("./pages/RunsPage.vue"),
  run: () => import("./pages/RunPage.vue"),
  pay: () => import("./pages/PayPage.vue"),
  adjustments: () => import("./pages/AdjustmentsPage.vue"),
  rules: () => import("./pages/RulesPage.vue"),
  advances: () => import("./pages/AdvancesPage.vue"),
};

export const widgets = {
  next: () => import("./widgets/NextPayrollWidget.vue"),
};

export const panels = {
  settings: () => import("./components/SettingsPanel.vue"),
  person: () => import("./components/PersonPayTab.vue"),
};
