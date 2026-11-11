/** Every lazily loaded piece of the contracts module, behind one import (see payroll/lazy.ts). */
export const pages = {
  list: () => import("./pages/ContractsPage.vue"),
  one: () => import("./pages/ContractPage.vue"),
};

export const panels = {
  settings: () => import("./components/SettingsPanel.vue"),
};
