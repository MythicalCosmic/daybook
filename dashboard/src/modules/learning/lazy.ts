/** Every lazily loaded piece of the learning module, behind one import. */
export const pages = {
  overview: () => import("./pages/OverviewPage.vue"),
  courses: () => import("./pages/CoursesPage.vue"),
  course: () => import("./pages/CoursePage.vue"),
  lessons: () => import("./pages/LessonsPage.vue"),
  lesson: () => import("./pages/LessonPage.vue"),
  people: () => import("./pages/PeoplePage.vue"),
  person: () => import("./pages/PersonPage.vue"),
};

export const panels = {
  settings: () => import("./components/SettingsPanel.vue"),
};
