/**
 * Every lazily loaded piece of Face ID behind one import, so the registry (part of the first
 * bundle) carries a single `import("./lazy")` instead of one preload list per page.
 */
export const pages = {
  live: () => import("./pages/LivePage.vue"),
  people: () => import("./pages/PeoplePage.vue"),
  terminals: () => import("./pages/TerminalsPage.vue"),
  settings: () => import("./pages/SettingsPage.vue"),
};
