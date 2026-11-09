/** Every lazily loaded piece of the recognition module, behind one import (see assets/lazy.ts). */
export const pages = {
  leaderboard: () => import("./pages/LeaderboardPage.vue"),
  kudos: () => import("./pages/KudosPage.vue"),
  badges: () => import("./pages/BadgesPage.vue"),
};

export const panels = {
  settings: () => import("./components/SettingsPanel.vue"),
  person: () => import("./components/PersonPanel.vue"),
  topLearners: () => import("./components/TopLearnersCard.vue"),
  sayThanks: () => import("./components/SayThanksAction.vue"),
};
