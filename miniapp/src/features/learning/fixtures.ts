/** Sample training as the §13 endpoints answer it, for the feature's tests (Demo Dorixona's story). */
import type {
  AssignmentCard,
  AttemptPlay,
  AttemptResult,
  CheckEntry,
  CourseCard,
  CourseDetail,
  CourseStep,
  DailyQuestion,
  LearningHome,
  LessonDetail,
  QuestionPlay,
  QuizDetail,
} from "./types";

export const course = (over: Partial<CourseCard> = {}): CourseCard => ({
  id: 4,
  title: "Sovuq zanjir",
  emoji: "",
  color: "sky",
  description: "Muzlatgich, termometr va harorat jurnali.",
  mandatory: true,
  steps: 4,
  minutes: 35,
  ...over,
});

export const assignment = (over: Partial<AssignmentCard> = {}): AssignmentCard => ({
  id: 31,
  state: "in_progress",
  percent: 50,
  steps_done: 2,
  steps_total: 4,
  due_at: "2026-10-28T18:59:59Z",
  late: false,
  completed_at: null,
  certificate_url: null,
  course: course(),
  ...over,
});

export const home = (over: Partial<LearningHome> = {}): LearningHome => ({
  todo: [
    assignment(),
    assignment({ id: 32, percent: 25, steps_done: 1, due_at: "2026-10-19T18:59:59Z", late: true, course: course({ id: 5, title: "Retsept bo‘yicha dori berish", color: "violet" }) }),
    assignment({ id: 33, percent: 0, steps_done: 0, due_at: null, course: course({ id: 6, title: "Kassa qoidalari", mandatory: false, color: "amber" }) }),
  ],
  done: [
    assignment({
      id: 20,
      state: "completed",
      percent: 100,
      steps_done: 3,
      steps_total: 3,
      due_at: null,
      completed_at: "2026-10-10T07:00:00Z",
      certificate_url: "/api/v1/files/signed-cert/",
      course: course({ id: 2, title: "Yangi xodim kursi", color: "green" }),
    }),
  ],
  catalog: [course({ id: 7, title: "Analoglar bilan ishlash", mandatory: false, color: "indigo", steps: 3, minutes: 20 })],
  certificates: 1,
  ...over,
});

export const step = (over: Partial<CourseStep> = {}): CourseStep => ({
  id: 101,
  kind: "lesson",
  title: "Muzlatgich va termometr",
  emoji: "",
  required: true,
  done: false,
  locked: false,
  done_at: null,
  lesson_id: 11,
  page_id: null,
  quiz_id: null,
  minutes: 6,
  best_percent: null,
  ...over,
});

export const courseDetail = (over: Partial<CourseDetail> = {}): CourseDetail => {
  const { steps: _count, ...card } = course();
  return {
    ...card,
    sequential: true,
    certificate: true,
    assignment: assignment(),
    can_start: false,
    steps: [
      step({ id: 101, done: true, done_at: "2026-10-15T06:00:00Z" }),
      step({ id: 102, kind: "page", title: "Harorat jurnali", lesson_id: null, page_id: 5, minutes: 4, done: true }),
      step({ id: 103, kind: "lesson", title: "Sovuq zanjir buzilsa", lesson_id: 12, minutes: 8, best_percent: 35 }),
      step({ id: 104, kind: "quiz", title: "Sovuq zanjir testi", lesson_id: null, quiz_id: 8, minutes: 10, locked: true, best_percent: 60 }),
    ],
    ...over,
  };
};

export const lesson = (over: Partial<LessonDetail> = {}): LessonDetail => ({
  id: 12,
  title: "Sovuq zanjir buzilsa",
  emoji: "",
  summary: "Harorat 2–8 °C dan chiqsa nima qilish kerak.",
  notes_html: "<p>Termometrni <strong>har kuni</strong> tekshiring.</p>",
  source: "upload",
  video: { url: "/api/v1/files/signed-video/", poster_url: "/api/v1/files/signed-poster/", duration_seconds: 120, width: 1280, height: 720 },
  youtube_id: "",
  duration_seconds: 120,
  processing: false,
  topics: [{ id: 1, name: "Sovuq zanjir", color: "sky" }],
  completion_percent: 90,
  progress: { percent: 20, position: 24, completed_at: null, ranges: [[0, 24]] },
  next: { kind: "quiz", id: 8, title: "Sovuq zanjir testi" },
  ...over,
});

export const quizDetail = (over: Partial<QuizDetail> = {}): QuizDetail => ({
  id: 8,
  title: "Sovuq zanjir testi",
  emoji: "",
  description: "Muzlatgich, harorat va jurnal bo‘yicha savollar.",
  questions: 7,
  time_limit_seconds: 600,
  pass_percent: 70,
  max_attempts: 3,
  attempts_used: 1,
  retry_at: null,
  best: { percent: 60, passed: false },
  in_progress: null,
  can_start: true,
  reason: null,
  ...over,
});

const q = (over: Partial<QuestionPlay> & Pick<QuestionPlay, "id" | "kind" | "text">): QuestionPlay => ({
  image_url: null,
  points: 1,
  options: [],
  left: [],
  right: [],
  unit: null,
  ...over,
});

/** One question of every kind, as the player gets them (never the right answer). */
export const QUESTIONS: QuestionPlay[] = [
  q({ id: 1, kind: "single", text: "Insulin qaysi haroratda saqlanadi?", options: [{ id: "b", text: "15–25 °C" }, { id: "a", text: "2–8 °C" }, { id: "c", text: "Muzlatgichning muzlatgich qismida" }] }),
  q({ id: 2, kind: "multi", text: "Sovuq zanjirdagi dorilar?", options: [{ id: "a", text: "Insulin" }, { id: "b", text: "Paratsetamol" }, { id: "c", text: "Vaksinalar" }] }),
  q({ id: 3, kind: "true_false", text: "Muddati o‘tgan dori sotuvga qo‘yiladi." }),
  q({ id: 4, kind: "order", text: "Kirimni qabul qilish tartibi", options: [{ id: "c", text: "Hujjatga kiritish" }, { id: "a", text: "Nakladnoyni tekshirish" }, { id: "b", text: "Seriya va muddatni ko‘rish" }] }),
  q({ id: 5, kind: "match", text: "Moslang", left: [{ id: "l1", text: "Insulin" }, { id: "l2", text: "Sirop" }], right: [{ id: "r2", text: "15–25 °C" }, { id: "r1", text: "2–8 °C" }] }),
  q({ id: 6, kind: "text", text: "Muzlatgich harorati oralig‘i?" }),
  q({ id: 7, kind: "number", text: "Bolalar uchun sirop dozasi?", unit: "ml", points: 2 }),
];

export const attemptPlay = (over: Partial<AttemptPlay> = {}): AttemptPlay => ({
  id: 77,
  quiz: { id: 8, title: "Sovuq zanjir testi", emoji: "", pass_percent: 70 },
  number: 2,
  started_at: "2026-10-21T04:50:00Z",
  deadline_at: null,
  questions: QUESTIONS,
  answers: {},
  ...over,
});

export const attemptResult = (over: Partial<AttemptResult> = {}): AttemptResult => ({
  id: 77,
  state: "finished",
  score: "6.50",
  max_score: "8.00",
  percent: 81,
  passed: true,
  points: 20,
  retry_at: null,
  course_step_done: true,
  review: [
    { question: QUESTIONS[0], answer: { option: "a" }, correct: true, share: 1, right_answer: { option: "a" }, explanation: "Insulin 2–8 °C da saqlanadi." },
    { question: QUESTIONS[1], answer: { options: ["a"] }, correct: false, share: 0.5, right_answer: { options: ["a", "c"] }, explanation: "" },
    { question: QUESTIONS[4], answer: { pairs: { l1: "r2", l2: "r1" } }, correct: false, share: 0, right_answer: { pairs: { l1: "r1", l2: "r2" } }, explanation: "" },
    { question: QUESTIONS[5], answer: null, correct: false, share: 0, right_answer: { answers: ["2–8", "2-8"] }, explanation: "" },
    { question: QUESTIONS[6], answer: { value: 4 }, correct: false, share: 0, right_answer: { value: 5, tolerance: 0.5, unit: "ml" }, explanation: "" },
  ],
  ...over,
});

export const daily = (over: Partial<DailyQuestion> = {}): DailyQuestion => ({
  id: 501,
  day: "2026-10-21",
  question: QUESTIONS[0],
  answered: false,
  correct: null,
  answer: null,
  right_answer: null,
  explanation: null,
  ...over,
});

export const checkEntry = (over: Partial<CheckEntry> = {}): CheckEntry => ({
  entry_id: 61,
  title: "Dushanba tekshiruvi",
  quiz_id: 9,
  due_at: "2026-10-22T05:00:00Z",
  done: false,
  passed: null,
  ...over,
});
