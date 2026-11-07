/**
 * The learning endpoints' shapes (docs/PLAN-LEARNING.md §13, the contract with Q1 and Q2), written
 * by hand until the lead regenerates the schema. JSON is snake_case, times are ISO in UTC (the app
 * shows them in the company's zone), and a person only ever sees their own training.
 */

// — Q1: courses and lessons —

/** A palette key (`knowledge.topics.COLORS`): gray, red, orange, amber, green, teal, sky, blue, indigo, violet, pink. */
export type PaletteKey = string;

export type CourseCard = {
  id: number;
  title: string;
  /** The owner's own emoji for the course; empty when none (the app adds none of its own). */
  emoji: string;
  color: PaletteKey;
  description: string;
  mandatory: boolean;
  /** How many steps the course has. */
  steps: number;
  /** About how long it takes, in minutes. */
  minutes: number;
};

export type AssignmentState = "assigned" | "in_progress" | "completed" | "exempt" | "cancelled";

export type AssignmentCard = {
  id: number;
  state: AssignmentState;
  percent: number;
  steps_done: number;
  steps_total: number;
  due_at: string | null;
  late: boolean;
  completed_at: string | null;
  /** A signed link to the certificate PDF, once there is one. */
  certificate_url: string | null;
  course: CourseCard;
};

/** GET learning/ */
export type LearningHome = {
  todo: AssignmentCard[];
  /** The newest 20. */
  done: AssignmentCard[];
  catalog: CourseCard[];
  certificates: number;
};

export type StepKind = "lesson" | "page" | "quiz";

export type CourseStep = {
  id: number;
  kind: StepKind;
  title: string;
  emoji: string;
  required: boolean;
  done: boolean;
  locked: boolean;
  done_at: string | null;
  lesson_id: number | null;
  page_id: number | null;
  quiz_id: number | null;
  minutes: number | null;
  /** A quiz step's best result so far. */
  best_percent: number | null;
};

/** GET learning/courses/{id}/: the card's fields with the steps themselves in place of their count. */
export type CourseDetail = Omit<CourseCard, "steps"> & {
  sequential: boolean;
  certificate: boolean;
  assignment: AssignmentCard | null;
  can_start: boolean;
  steps: CourseStep[];
};

export type TopicRef = { id: number; name: string; color: PaletteKey };

/** Media seconds, whole, sorted and merged on the server. */
export type Range = [number, number];

export type LessonVideo = {
  /** Signed, valid 6 h. */
  url: string;
  poster_url: string | null;
  duration_seconds: number;
  width: number;
  height: number;
};

export type LessonProgress = {
  percent: number;
  position: number;
  completed_at: string | null;
  ranges: Range[];
};

/** What comes after this lesson in the course it was opened from (`id` is the lesson's, page's or quiz's). */
export type NextStep = { kind: StepKind; id: number; title: string };

/** GET learning/lessons/{id}/?course=<id> */
export type LessonDetail = {
  id: number;
  title: string;
  emoji: string;
  summary: string;
  notes_html: string;
  source: "upload" | "youtube";
  video: LessonVideo | null;
  youtube_id: string;
  duration_seconds: number;
  processing: boolean;
  topics: TopicRef[];
  /** Watched at this percent (the company's setting, 90 by default). */
  completion_percent: number;
  progress: LessonProgress | null;
  next: NextStep | null;
};

/** POST learning/lessons/{id}/progress/: what was played since the previous report. */
export type ProgressReport = {
  /** A random id per opening of the lesson. */
  session: string;
  position: number;
  duration: number;
  ranges: Range[];
  playing: boolean;
};

export type ProgressAnswer = {
  percent: number;
  position: number;
  completed: boolean;
  completed_now: boolean;
  points: number | null;
};

/** POST knowledge/pages/{id}/view/ (always on, 204). */
export type PageViewReport = { session: string; seconds: number; scrolled: number };

// — Q2: quizzes, the question of the day, checks —

export type QuestionKind = "single" | "multi" | "true_false" | "order" | "match" | "text" | "number";

export type Choice = { id: string; text: string };

/** A question as the person sees it: never the right answer. */
export type QuestionPlay = {
  id: number;
  kind: QuestionKind;
  text: string;
  image_url: string | null;
  points: number;
  /** single, multi, order (shuffled as shown). */
  options: Choice[];
  /** match: the left side as written. */
  left: Choice[];
  /** match: the right side, shuffled (the pairs' ids). */
  right: Choice[];
  /** number: the unit after the box ("ml", "°C"). */
  unit: string | null;
};

/** The answer shapes of §4.3, one per kind. */
export type SingleAnswer = { option: string };
export type MultiAnswer = { options: string[] };
export type TrueFalseAnswer = { value: boolean };
export type OrderAnswer = { order: string[] };
export type MatchAnswer = { pairs: Record<string, string> };
export type TextAnswer = { text: string };
export type NumberAnswer = { value: number };
export type Answer = SingleAnswer | MultiAnswer | TrueFalseAnswer | OrderAnswer | MatchAnswer | TextAnswer | NumberAnswer;

/**
 * A right answer as the server reveals it after answering. Its shape follows the answer's; text
 * questions may list every accepted answer and number ones their tolerance and unit.
 */
export type RightAnswer = Partial<SingleAnswer & MultiAnswer & OrderAnswer & MatchAnswer & TextAnswer> & {
  value?: number | boolean | string;
  answers?: string[];
  tolerance?: number;
  unit?: string | null;
};

/** GET learning/quizzes/{id}/?assignment=<id>&entry=<id> */
export type QuizDetail = {
  id: number;
  title: string;
  emoji: string;
  description: string;
  questions: number;
  time_limit_seconds: number | null;
  pass_percent: number;
  max_attempts: number | null;
  attempts_used: number;
  /** When the cool-down after the last attempt ends. */
  retry_at: string | null;
  best: { percent: number; passed: boolean } | null;
  /** The attempt in progress, to resume. */
  in_progress: number | null;
  can_start: boolean;
  /** Why not, when `can_start` is false. */
  reason: string | null;
};

/** POST learning/quizzes/{id}/attempts/, and GET learning/attempts/{id}/ while it runs. */
export type AttemptPlay = {
  id: number;
  quiz: { id: number; title: string; emoji: string; pass_percent: number };
  number: number;
  started_at: string;
  deadline_at: string | null;
  questions: QuestionPlay[];
  /** What was saved so far, by question id. */
  answers: Record<string, Answer>;
};

export type AttemptState = "in_progress" | "finished" | "expired" | "abandoned";

export type ReviewItem = {
  question: QuestionPlay;
  answer: Answer | null;
  correct: boolean;
  /** The part of the points earned, 0 to 1 (partial credit). */
  share: number;
  right_answer: RightAnswer | null;
  explanation: string | null;
};

/** POST learning/attempts/{id}/finish/, and GET learning/attempts/{id}/ once it's over. */
export type AttemptResult = {
  id: number;
  state: AttemptState;
  /** Decimals may arrive as strings ("12.50"). */
  score: number | string;
  max_score: number | string;
  percent: number;
  passed: boolean;
  points: number | null;
  retry_at: string | null;
  course_step_done: boolean;
  /** What the quiz allows to be shown (`show_answers`); null when it shows nothing. */
  review: ReviewItem[] | null;
};

export type AttemptView = AttemptPlay | AttemptResult;

export type DailyQuestion = {
  id: number;
  day: string;
  question: QuestionPlay;
  answered: boolean;
  correct: boolean | null;
  answer: Answer | null;
  right_answer: RightAnswer | null;
  explanation: string | null;
};

/** GET learning/daily/ */
export type DailyView = { daily: DailyQuestion | null; streak: number | null };

/** POST learning/daily/{id}/answer/ */
export type DailyResult = {
  correct: boolean;
  share: number;
  right_answer: RightAnswer | null;
  explanation: string | null;
  points: number | null;
  streak: number | null;
};

/** A row of GET learning/checks/: open rounds and the last closed ones. */
export type CheckEntry = {
  entry_id: number;
  title: string;
  quiz_id: number;
  due_at: string;
  done: boolean;
  passed: boolean | null;
};
