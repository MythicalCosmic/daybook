/**
 * Performance reviews' plain logic, tested on its own: the periods a round offers, the new round's
 * defaults and checks, how far a round has got, a rating's words and colour, the pay after a raise
 * (rounded the way payroll rounds pay), and what the reviewer still has to fill before publishing.
 */
import type { StatusTone } from "@/components/StatusPill.vue";
import { addDays, addMonths, startOfMonth } from "@/lib/dates";

import type { Answers, GoalInput, Outcome, OutcomeState, Question, QuestionInput, Review, RoundInput, RoundProgress, RoundStatus } from "./types";

export const MIN_QUESTIONS = 3;
export const MAX_QUESTIONS = 10;
export const MAX_GOALS = 3;
export const RATINGS = [1, 2, 3, 4, 5] as const;

// ─── Periods ───────────────────────────────────────────────────────────────

export type PeriodPreset = "quarter" | "month" | "half" | "custom";
export interface Period {
  start: string;
  end: string;
}

/** The last full quarter before `today`'s. */
export function lastQuarter(today: string): Period {
  const [year, month] = today.split("-").map(Number) as [number, number];
  const firstMonth = 3 * Math.floor((month - 1) / 3) + 1;
  const thisQuarter = `${year}-${String(firstMonth).padStart(2, "0")}-01`;
  const start = addMonths(thisQuarter, -3);
  return { start, end: addDays(thisQuarter, -1) };
}

export function lastMonth(today: string): Period {
  const first = startOfMonth(today);
  return { start: addMonths(first, -1), end: addDays(first, -1) };
}

/** The last full half-year (January–June or July–December). */
export function lastHalf(today: string): Period {
  const [year, month] = today.split("-").map(Number) as [number, number];
  return month > 6 ? { start: `${year}-01-01`, end: `${year}-06-30` } : { start: `${year - 1}-07-01`, end: `${year - 1}-12-31` };
}

export function presetPeriod(preset: Exclude<PeriodPreset, "custom">, today: string): Period {
  if (preset === "month") return lastMonth(today);
  if (preset === "half") return lastHalf(today);
  return lastQuarter(today);
}

/** "3", "2026" for a quarter's end: the name's pieces (the words come from the dictionary). */
export function quarterOf(day: string): { quarter: number; year: number } {
  const [year, month] = day.split("-").map(Number) as [number, number];
  return { quarter: Math.floor((month - 1) / 3) + 1, year };
}

// ─── A new round ───────────────────────────────────────────────────────────

export interface RoundForm {
  name: string;
  preset: PeriodPreset;
  period_start: string;
  period_end: string;
  audience: "all" | "some";
  positions: number[];
  branches: number[];
  questions: QuestionInput[];
  self_due_on: string;
  manager_due_on: string;
}

export function blankRound(today: string, name: string, questions: QuestionInput[]): RoundForm {
  const period = lastQuarter(today);
  const selfDue = addDays(today, 7);
  return {
    name,
    preset: "quarter",
    period_start: period.start,
    period_end: period.end,
    audience: "all",
    positions: [],
    branches: [],
    questions,
    self_due_on: selfDue,
    manager_due_on: addDays(selfDue, 7),
  };
}

export type RoundStep = "basics" | "people" | "questions" | "deadlines";
export type RoundErrors = Partial<Record<"name" | "period" | "audience" | "questions" | "self_due_on" | "manager_due_on", string>>;

/** What is missing or wrong, by field (the keys of `lifecycle.reviews.error.*`). */
export function roundErrors(form: RoundForm, today: string): RoundErrors {
  const errors: RoundErrors = {};
  if (!form.name.trim()) errors.name = "name";
  if (!form.period_start || !form.period_end) errors.period = "period";
  else if (form.period_end < form.period_start) errors.period = "periodOrder";
  if (form.audience === "some" && !form.positions.length && !form.branches.length) errors.audience = "audience";
  const written = form.questions.filter((question) => question.text.trim());
  if (written.length !== form.questions.length) errors.questions = "questionText";
  else if (form.questions.length < MIN_QUESTIONS || form.questions.length > MAX_QUESTIONS) errors.questions = "questionCount";
  if (!form.self_due_on) errors.self_due_on = "required";
  else if (form.self_due_on < today) errors.self_due_on = "past";
  if (!form.manager_due_on) errors.manager_due_on = "required";
  else if (form.self_due_on && form.manager_due_on < form.self_due_on) errors.manager_due_on = "managerOrder";
  return errors;
}

/** Which wizard step a field belongs to (to show the step with the first error). */
export const ERROR_STEP: Record<keyof RoundErrors, RoundStep> = {
  name: "basics",
  period: "basics",
  audience: "people",
  questions: "questions",
  self_due_on: "deadlines",
  manager_due_on: "deadlines",
};

export function roundPayload(form: RoundForm, open: boolean): RoundInput {
  return {
    name: form.name.trim(),
    period_start: form.period_start,
    period_end: form.period_end,
    self_due_on: form.self_due_on,
    manager_due_on: form.manager_due_on,
    questions: form.questions.map((question) => ({ kind: question.kind, text: question.text.trim(), key: question.key ?? "" })),
    positions: form.audience === "some" ? form.positions : [],
    branches: form.audience === "some" ? form.branches : [],
    open,
  };
}

/** A template question's key stays only while its words are the template's (and comes back with them). */
export function editQuestion(question: QuestionInput, text: string, template: Question[]): QuestionInput {
  const original = template.find((item) => item.key && item.kind === question.kind && item.text === text);
  return { ...question, text, key: original ? original.key : "" };
}

export function moveItem<T>(list: T[], index: number, offset: -1 | 1): T[] {
  const target = index + offset;
  if (target < 0 || target >= list.length) return list;
  const copy = [...list];
  [copy[index], copy[target]] = [copy[target]!, copy[index]!];
  return copy;
}

// ─── A round's state ───────────────────────────────────────────────────────

export const ROUND_TONES: Record<RoundStatus, StatusTone> = { draft: "neutral", self: "info", manager: "warning", closed: "success" };
export const STAGES: RoundStatus[] = ["draft", "self", "manager", "closed"];

export function stageIndex(status: RoundStatus): number {
  return STAGES.indexOf(status);
}

/** Share of people done with the part the round is in (0–100). */
export function partDone(status: RoundStatus, progress: RoundProgress): number {
  if (!progress.people) return 0;
  const done = status === "self" ? progress.self_sent : progress.published;
  return Math.round((100 * done) / progress.people);
}

// ─── Ratings and outcomes ──────────────────────────────────────────────────

/** A rating's colour: 1–2 a concern, 3 fine, 4–5 strong. */
export function ratingTone(rating: number | null | undefined): StatusTone {
  if (!rating) return "neutral";
  if (rating <= 2) return "danger";
  if (rating === 3) return "warning";
  return "success";
}

export const OUTCOME_TONES: Record<Outcome, StatusTone> = { none: "neutral", raise: "success", bonus: "success", promotion: "primary", improvement_plan: "warning" };
export const OUTCOME_STATE_TONES: Record<OutcomeState, StatusTone> = { waiting: "warning", approved: "info", applied: "success", rejected: "danger" };

/** The mean of the ratings given (one decimal), null without any. */
export function average(answers: Answers | null | undefined, questions: Question[]): number | null {
  const ratings = questions
    .filter((question) => question.kind === "rating")
    .map((question) => answers?.[question.id]?.rating)
    .filter((rating): rating is number => typeof rating === "number" && rating > 0);
  if (!ratings.length) return null;
  return Math.round((10 * ratings.reduce((sum, rating) => sum + rating, 0)) / ratings.length) / 10;
}

/** The overall rating a reviewer would start from: their mean, rounded. */
export function suggestedRating(answers: Answers | null | undefined, questions: Question[]): number | null {
  const mean = average(answers, questions);
  return mean === null ? null : Math.min(5, Math.max(1, Math.round(mean)));
}

/** How many questions have an answer (a rating, or words for a text question). */
export function answeredCount(answers: Answers | null | undefined, questions: Question[]): number {
  return questions.filter((question) => {
    const answer = answers?.[question.id];
    return question.kind === "rating" ? !!answer?.rating : !!answer?.text?.trim();
  }).length;
}

/**
 * The pay after a raise of `percent` %, rounded to payroll's step (as the server counts it): a
 * string with two decimals, or null when something is missing.
 */
export function payAfter(amount: string | null | undefined, percent: string | number | null | undefined, step: string | null | undefined): string | null {
  const now = Number(amount);
  const rate = Number(String(percent ?? "").replace(",", "."));
  if (!amount || !Number.isFinite(now) || !Number.isFinite(rate) || rate <= 0) return null;
  const unit = Number(step) > 0 ? Number(step) : 0.01;
  const raised = (now * (100 + rate)) / 100;
  const rounded = Math.round(raised / unit) * unit;
  return rounded.toFixed(2);
}

/** The first day of next month: when a raise or a promotion starts by default. */
export function nextFirst(today: string): string {
  return addMonths(startOfMonth(today), 1);
}

// ─── The reviewer's part ───────────────────────────────────────────────────

export interface ManagerForm {
  answers: Answers;
  rating: number | null;
  summary: string;
  outcome: Outcome;
  raise_percent: string | null;
  bonus_amount: string | null;
  promotion_position: number | null;
  effective_on: string | null;
  goals: GoalInput[];
}

export function managerForm(review: Review): ManagerForm {
  return {
    // A copy the form may change (the review itself is the query's).
    answers: JSON.parse(JSON.stringify(review.manager_answers ?? {})) as Answers,
    rating: review.rating,
    summary: review.summary ?? "",
    outcome: review.outcome,
    raise_percent: review.raise_percent,
    bonus_amount: review.bonus_amount,
    promotion_position: review.promotion_position?.id ?? null,
    effective_on: review.effective_on,
    goals: review.goals.map((goal) => ({ title: goal.title, due_on: goal.due_on, target: goal.target, unit: goal.unit })),
  };
}

export type PublishProblem = "ratings" | "rating" | "raise" | "bonus" | "position" | "day" | "goals" | "goalDay";

/** What still stops publishing (the keys of `lifecycle.reviews.publishNeeds.*`). */
export function publishProblems(form: ManagerForm, questions: Question[], today: string): PublishProblem[] {
  const problems: PublishProblem[] = [];
  const unrated = questions.filter((question) => question.kind === "rating" && !form.answers[question.id]?.rating);
  if (unrated.length) problems.push("ratings");
  if (!form.rating) problems.push("rating");
  if (form.outcome === "raise" && !(Number(form.raise_percent) > 0)) problems.push("raise");
  if (form.outcome === "bonus" && !(Number(form.bonus_amount) > 0)) problems.push("bonus");
  if (form.outcome === "promotion" && !form.promotion_position) problems.push("position");
  if ((form.outcome === "raise" || form.outcome === "promotion") && (!form.effective_on || form.effective_on < today)) problems.push("day");
  if (form.outcome === "improvement_plan") {
    const goals = form.goals.filter((goal) => goal.title.trim());
    if (!goals.length) problems.push("goals");
    else if (goals.some((goal) => !goal.due_on || goal.due_on < today)) problems.push("goalDay");
  }
  return problems;
}

/** The body of PATCH lifecycle/reviews/{id}/ from the form. */
export function managerPayload(form: ManagerForm): Record<string, unknown> {
  return {
    answers: form.answers,
    rating: form.rating,
    summary: form.summary,
    outcome: form.outcome,
    raise_percent: form.outcome === "raise" || form.outcome === "promotion" ? form.raise_percent || null : null,
    bonus_amount: form.outcome === "bonus" ? form.bonus_amount || null : null,
    promotion_position_id: form.outcome === "promotion" ? form.promotion_position : null,
    effective_on: form.outcome === "none" || form.outcome === "improvement_plan" ? null : form.effective_on,
    goals: form.goals.filter((goal) => goal.title.trim() || goal.due_on).map((goal) => ({ ...goal, title: goal.title.trim(), target: goal.target || null })),
  };
}
