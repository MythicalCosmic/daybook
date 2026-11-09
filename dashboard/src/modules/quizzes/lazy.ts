/** Every lazily loaded piece of the quizzes module, behind one import (see assets/lazy.ts). */
export const pages = {
  quizzes: () => import("./pages/QuizzesPage.vue"),
  quiz: () => import("./pages/QuizPage.vue"),
  questions: () => import("./pages/QuestionsPage.vue"),
  checks: () => import("./pages/ChecksPage.vue"),
  skills: () => import("./pages/SkillsPage.vue"),
  tutor: () => import("./pages/TutorPage.vue"),
};

export const parts = {
  dailySettings: () => import("./components/DailySettingsPanel.vue"),
  personPanel: () => import("./components/PersonPanel.vue"),
  overviewCards: () => import("./components/OverviewCards.vue"),
};
