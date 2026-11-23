/**
 * Every lazily loaded piece of Ko‘z behind one import, so the registry (part of the first bundle)
 * carries a single `import("./lazy")` instead of one preload list per page.
 */
export const pages = {
  overview: () => import("./pages/OverviewPage.vue"),
  live: () => import("./pages/LivePage.vue"),
  alerts: () => import("./pages/AlertsPage.vue"),
  review: () => import("./pages/ReviewPage.vue"),
  cameras: () => import("./pages/CamerasPage.vue"),
  zones: () => import("./pages/ZonesPage.vue"),
  settings: () => import("./pages/SettingsPage.vue"),
};

export const parts = {
  /** Sales › Receipts: "Video" of the till at the moment of a sale. */
  saleVideo: () => import("./components/SaleVideoButton.vue"),
};
