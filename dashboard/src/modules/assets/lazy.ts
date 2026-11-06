/** Every lazily loaded piece of the assets module, behind one import (see payroll/lazy.ts). */
export const pages = {
  register: () => import("./pages/RegisterPage.vue"),
  asset: () => import("./pages/AssetPage.vue"),
  depreciation: () => import("./pages/DepreciationPage.vue"),
  planning: () => import("./pages/PlanningPage.vue"),
  counts: () => import("./pages/CountsPage.vue"),
};

export const panels = {
  settings: () => import("./components/SettingsPanel.vue"),
};
