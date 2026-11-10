/**
 * The owner endpoints of quizzes, the question bank, checks, skills and the tutor
 * (`/api/v1/owner/companies/{c}/learning/…`, package Q2), written by hand next to the API
 * functions until the generated schema has them (docs/PLAN-LEARNING.md §13).
 */

export type QuestionKind = "single" | "multi" | "true_false" | "order" | "match" | "text" | "number";
export type Difficulty = "easy" | "medium" | "hard";
export type QuestionState = "draft" | "active" | "archived";
export type QuestionSource = "manual" | "ai" | "rules" | "copy";
export type QuizStatus = "draft" | "published" | "archived";
export type QuizMode = "fixed" | "random";
export type ShowAnswers = "after" | "passed" | "never";
export type AttemptState = "in_progress" | "finished" | "expired" | "abandoned";
export type Band = "weak" | "ok" | "strong" | "unrated";
export type SuggestionKind = "assign" | "practice" | "lesson_needed" | "mentor" | "praise" | "overdue";
export type SuggestionState = "open" | "accepted" | "dismissed" | "done";
export type CheckEvery = "week" | "month";
export type CheckState = "active" | "paused" | "archived";

export interface TopicRef {
  id: number;
  name: string;
  color: string;
}

export interface Ref {
  id: number;
  title: string;
}

export interface PersonRef {
  id: number;
  name: string;
  photo_url: string | null;
  position: string | null;
}

export interface ImageRef {
  id: number;
  url: string;
  width: number;
  height: number;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

/** `Question.data` of each kind (§4.3), as the bank stores it. */
export interface ChoiceOption {
  id?: string;
  text: string;
  correct: boolean;
}
export interface OrderItem {
  id?: string;
  text: string;
}
export interface MatchPair {
  id?: string;
  left: string;
  right: string;
}
export type QuestionData =
  | { options: ChoiceOption[] }
  | { answer: boolean }
  | { items: OrderItem[] }
  | { pairs: MatchPair[] }
  | { answers: string[]; case: boolean }
  | { value: number | null; tolerance: number; unit: string };

export interface Question {
  id: number;
  kind: QuestionKind;
  text: string;
  data: Record<string, unknown>;
  explanation: string;
  image: ImageRef | null;
  topic: TopicRef | null;
  difficulty: Difficulty;
  points: number;
  state: QuestionState;
  source: QuestionSource;
  lesson: Ref | null;
  page: Ref | null;
  draft_job_id: number | null;
  answered: number;
  correct: number;
  correct_percent: number | null;
  quizzes: number;
  created_at: string;
  updated_at: string;
}

export interface QuestionInput {
  kind?: QuestionKind;
  text?: string;
  data?: QuestionData;
  explanation?: string;
  topic_id?: number | null;
  difficulty?: Difficulty;
  points?: number;
  image_id?: number | null;
  lesson_id?: number | null;
  page_id?: number | null;
  state?: QuestionState;
}

/** A question as a learner sees it: never the right answer. */
export interface PlayOption {
  id: string;
  text: string;
}
export interface QuestionPlay {
  id: number;
  kind: QuestionKind;
  text: string;
  image_url: string | null;
  points: number;
  options: PlayOption[];
  left: PlayOption[];
  right: PlayOption[];
  unit: string | null;
}

export interface QuizRow {
  id: number;
  title: string;
  emoji: string;
  description: string;
  status: QuizStatus;
  mode: QuizMode;
  question_count: number;
  questions: number;
  topics: TopicRef[];
  pass_percent: number;
  time_limit_seconds: number | null;
  max_attempts: number | null;
  attempts: number;
  people: number;
  pass_rate: number | null;
  average: number | null;
  updated_at: string;
}

export interface Quiz extends QuizRow {
  shuffle_questions: boolean;
  shuffle_options: boolean;
  retry_after_minutes: number;
  partial_credit: boolean;
  show_answers: ShowAnswers;
  audience_all: boolean;
  position_ids: number[];
  topic_ids: number[];
  question_ids: number[];
  in_courses: number;
  in_checks: number;
}

export type QuizInput = Partial<
  Pick<
    Quiz,
    | "title"
    | "emoji"
    | "description"
    | "mode"
    | "question_count"
    | "shuffle_questions"
    | "shuffle_options"
    | "time_limit_seconds"
    | "pass_percent"
    | "max_attempts"
    | "retry_after_minutes"
    | "partial_credit"
    | "show_answers"
    | "audience_all"
    | "position_ids"
    | "topic_ids"
    | "question_ids"
  >
>;

export interface PreviewItem {
  question: QuestionPlay;
  right_answer: Record<string, unknown>;
  explanation: string;
}

export interface ResultAttempt {
  id: number;
  member: PersonRef;
  number: number;
  state: AttemptState;
  started_at: string;
  finished_at: string | null;
  percent: number | null;
  passed: boolean | null;
  score: number | null;
  max_score: number | null;
  reset: boolean;
  check: boolean;
}

export interface HardQuestion {
  id: number;
  text: string;
  kind: QuestionKind;
  answered: number;
  correct: number;
  percent: number;
}

export interface Results {
  summary: { attempts: number; people: number; passed_people: number; pass_rate: number | null; average: number | null };
  attempts: ResultAttempt[];
  distribution: { start: number; end: number; count: number }[];
  hardest: HardQuestion[];
}

export interface ReviewItem {
  question: QuestionPlay;
  answer: Record<string, unknown> | null;
  correct: boolean;
  share: number;
  right_answer: Record<string, unknown> | null;
  explanation: string | null;
}

export interface OwnerAttempt {
  id: number;
  state: AttemptState;
  score: number;
  max_score: number;
  percent: number;
  passed: boolean;
  points: number | null;
  retry_at: string | null;
  course_step_done: boolean;
  review: ReviewItem[] | null;
  member: PersonRef;
  quiz: Ref;
  number: number;
  started_at: string;
  finished_at: string | null;
  trial: boolean;
}

export interface RoundRow {
  id: number;
  starts_at: string;
  due_at: string;
  closed_at: string | null;
  people: number;
  done: number;
  passed: number;
}

export interface RoundEntry {
  id: number;
  member: PersonRef;
  done: boolean;
  passed: boolean | null;
  percent: number | null;
  attempt_id: number | null;
  reminded_at: string | null;
}

export interface RoundDetail extends RoundRow {
  entries: RoundEntry[];
  weakest: { question: number; text: string; percent: number } | null;
}

export interface Check {
  id: number;
  title: string;
  quiz: Ref;
  state: CheckState;
  every: CheckEvery;
  weekday: number | null;
  month_day: number | null;
  at: string;
  answer_within_hours: number;
  audience_all: boolean;
  position_ids: number[];
  branch_ids: number[];
  next_run_at: string | null;
  last_round: RoundRow | null;
}

export interface CheckInput {
  title?: string;
  quiz_id?: number;
  every?: CheckEvery;
  weekday?: number | null;
  month_day?: number | null;
  at?: string;
  answer_within_hours?: number;
  audience_all?: boolean;
  position_ids?: number[];
  branch_ids?: number[];
}

export interface SkillCell {
  score: number | null;
  answers: number;
  band: Band;
  last_at: string | null;
}

export interface SkillTopic {
  id: number;
  name: string;
  color: string;
  average: number | null;
  rated: number;
  weak: number;
  strong: number;
}

export interface SkillRow {
  member: PersonRef;
  average: number | null;
  answers: number;
  cells: Record<string, SkillCell>;
}

export interface SkillMatrix {
  topics: SkillTopic[];
  people: SkillRow[];
}

export interface PersonSkills {
  member: PersonRef;
  topics: (SkillCell & { topic: TopicRef })[];
  attempts: { id: number; quiz: Ref; state: AttemptState; percent: number | null; passed: boolean | null; finished_at: string | null; check: boolean }[];
  daily: { asked: number; answered: number; right: number };
}

export interface Suggestion {
  id: number;
  kind: SuggestionKind;
  state: SuggestionState;
  member: PersonRef | null;
  topic: TopicRef | null;
  course: Ref | null;
  score: number | null;
  params: Record<string, unknown>;
  text: string;
  created_at: string;
  decided_at: string | null;
}

export interface DraftJob {
  id: number;
  state: "queued" | "running" | "done" | "failed";
  engine: "claude" | "rules";
  page: Ref | null;
  lesson: Ref | null;
  topic: TopicRef | null;
  count: number;
  kinds: QuestionKind[];
  difficulty: Difficulty | "";
  made: number;
  dropped: number;
  error: string;
  created_at: string;
  finished_at: string | null;
}

export interface DraftJobDetail extends DraftJob {
  questions: Question[];
}

export interface DraftInput {
  page_id?: number | null;
  lesson_id?: number | null;
  count: number;
  kinds: QuestionKind[];
  difficulty: Difficulty | "";
  topic_id?: number | null;
  engine: "auto" | "rules";
}

export interface DailySettings {
  daily_question: boolean;
  daily_at: string;
  daily_position_ids: number[];
  today: { day: string; asked: number; answered: number; right: number };
}

export interface TutorConfig {
  weekly_report: boolean;
  report_day: string;
  at: string;
  nudge_learners: boolean;
  suggest: boolean;
  weak_threshold: number;
}

export interface TutorReportFacts {
  mandatory?: { people: number; completed: number; late: number; late_names: string[] };
  tests?: { count: number; average: number };
  weakest_topic?: { name: string; average: number; weak: number } | null;
  top?: { name: string; points: number }[];
  help?: { name: string; topics: string[]; late: boolean }[];
  suggestions?: { open: number; assign: number };
}

export interface Tutor {
  agent: {
    listed: boolean;
    enabled: boolean;
    ai_on: boolean;
    claude: string;
    chat: boolean;
    next_report_at: string | null;
    config: TutorConfig;
  };
  report: { sent_at: string | null; week: string; opening: string; lines: string[]; facts: TutorReportFacts } | null;
  suggestions: Record<string, number>;
  weakest: SkillTopic[];
  events: { at: string; text: string; level: string }[];
}

export interface Conversation {
  id: number;
  title: string;
  created_at: string;
  last_activity_at: string;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  text: string;
  created_at: string;
  steps: { label: string; status: "done" | "error"; ms: number }[];
}

export interface Turn {
  id: number;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  steps: ChatMessage["steps"];
  text: string;
  error_code: string;
  message_id: number | null;
}

/** A card of "Ask the tutor" (`learning/tutor/conversations/{id}/drafts/`): what one draft tool
 * call made, questions or a quiz, with every draft as it is now. Nothing is in use until the
 * person approves it. */
export type TutorDraftKind = "questions" | "quiz";
export type TutorDraftState = "running" | "done" | "failed";

export interface TutorDraftItem {
  id: number;
  /** Deleted since (discarded here or on the questions page). */
  deleted: boolean;
  question: Question | null;
  /** As the learner will see it, with the right answer (questions cards only). */
  preview: PreviewItem | null;
}

export interface TutorDraftQuiz {
  id: number;
  title: string;
  status: QuizStatus;
  pass_percent: number;
  time_limit_seconds: number | null;
  max_attempts: number | null;
  audience_all: boolean;
  positions: string[];
}

export interface TutorDraftCard {
  id: number;
  kind: TutorDraftKind;
  state: TutorDraftState;
  turn_id: number;
  /** The answer it goes under; null while its turn runs. */
  message_id: number | null;
  /** Questions asked for. */
  count: number;
  title: string;
  error: string;
  created_at: string;
  questions: TutorDraftItem[];
  /** Null on a quiz card once the quiz was deleted. */
  quiz: TutorDraftQuiz | null;
}

/** Pickers: topics, knowledge pages and lessons to write questions from. */
export interface TopicOption {
  id: number;
  name: string;
  color: string;
  archived: boolean;
}
