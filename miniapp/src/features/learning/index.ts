/**
 * Training for pharmacy staff (docs/PLAN-LEARNING.md §12.1, package P) on the learning module's
 * employee endpoints (§13 Q1 and Q2): the learning home (to do, done, catalogue, certificates,
 * checks), a course with its steps, the video lesson player that reports what was really watched,
 * quizzes (intro, player for the seven kinds of question, result with the review), the question
 * of the day and regular checks. Home: a check card while a round is open, the question of the
 * day answered in place, the open mandatory courses; Me: "My training". Shown while the company
 * has `learning` on, to people who work here.
 *
 * Deep links: `learning`, `course:<id>`, `lesson:<id>`, `quiz:<id>`, `check:<entry id>`, `daily`,
 * `startapp=learn-<course id>` (and `learning.attempt:<id>`).
 */
import { GraduationCap } from "lucide-react";
import { lazy } from "react";

import { defineFeature } from "../registry";
import { learningVisible } from "./lib";
import { messages } from "./messages";
import { CheckCard, DailyCard, TrainingCard, useMeStatus } from "./slots";

export default defineFeature({
  id: "learning",
  messages,
  visible: (member) => learningVisible(member),
  pages: {
    home: lazy(() => import("./LearningHome")),
    course: lazy(() => import("./CoursePage")),
    lesson: lazy(() => import("./LessonPage")),
    quiz: lazy(() => import("./QuizPage")),
    attempt: lazy(() => import("./AttemptPage")),
    check: lazy(() => import("./CheckPage")),
    daily: lazy(() => import("./Daily")),
  },
  homeCards: [
    // A check has a deadline today or tomorrow: before the day's question and the courses.
    { id: "check", component: CheckCard, order: 33 },
    { id: "daily", component: DailyCard, order: 36 },
    { id: "training", component: TrainingCard, order: 42 },
  ],
  meItems: [{ id: "training", group: "work", label: "me.training", icon: GraduationCap, open: { page: "home" }, order: 25, useStatus: useMeStatus }],
  routes: {
    learning: { page: "home", tab: "profile" },
    course: "course",
    learn: "course",
    lesson: "lesson",
    quiz: "quiz",
    check: "check",
    daily: "daily",
  },
});
