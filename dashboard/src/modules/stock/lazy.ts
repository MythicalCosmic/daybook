/** Every lazily loaded piece of the stock module, behind one import (see payroll/lazy.ts). */
export const pages = {
  products: () => import("./pages/ProductsPage.vue"),
  levels: () => import("./pages/LevelsPage.vue"),
  expiry: () => import("./pages/ExpiryPage.vue"),
  receipts: () => import("./pages/ReceiptsPage.vue"),
  receipt: () => import("./pages/ReceiptPage.vue"),
  transfers: () => import("./pages/TransfersPage.vue"),
  writeoffs: () => import("./pages/WriteOffsPage.vue"),
  writeoff: () => import("./pages/WriteOffPage.vue"),
  counts: () => import("./pages/CountsPage.vue"),
  count: () => import("./pages/CountPage.vue"),
  recalls: () => import("./pages/RecallsPage.vue"),
  defektura: () => import("./pages/DefekturaPage.vue"),
  suppliers: () => import("./pages/SuppliersPage.vue"),
  journals: () => import("./pages/JournalsPage.vue"),
};

export const panels = {
  settings: () => import("./components/SettingsPanel.vue"),
};
