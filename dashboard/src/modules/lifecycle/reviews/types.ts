/**
 * Performance reviews as the owner endpoints send them (`lifecycle/review-rounds/…`,
 * `lifecycle/reviews/…`, backend/apps/lifecycle/review_serializers.py). Hand-written until the
 * generated schema has them. Money is a string; days are company-local `YYYY-MM-DD`.
 */
import type { BranchRef, Currency, Money, PersonRef } from "@/api/types";

export const ROUND_STATUSES = ["draft", "self", "manager", "closed"] as const;
export type RoundStatus = (typeof ROUND_STATUSES)[number];
export const OUTCOMES = ["none", "raise", "bonus", "promotion", "improvement_plan"] as const;
export type Outcome = (typeof OUTCOMES)[number];
export type QuestionKind = "rating" | "text";
export type SelfState = "not_started" | "draft" | "sent";
export type ManagerState = "not_started" | "draft" | "published";
export type OutcomeState = "waiting" | "approved" | "applied" | "rejected";
export type LatePart = "self" | "manager";
export type GoalStatus = "open" | "done" | "missed";
export const ROW_STATES = ["self_late", "self_waiting", "to_write", "published"] as const;
export type RowState = (typeof ROW_STATES)[number];

export interface Ref {
  id: number;
  name: string;
}

export interface Question {
  id: string;
  kind: QuestionKind;
  text: string;
  /** The template question it is, while its words are untouched (each reader's language). */
  key: string;
}

export interface Answer {
  rating?: number | null;
  text?: string;
}
export type Answers = Record<string, Answer>;

export interface RoundProgress {
  people: number;
  self_sent: number;
  published: number;
  acknowledged: number;
  late: number;
  self_late: number;
  manager_late: number;
}

export interface Round {
  id: number;
  name: string;
  period_start: string;
  period_end: string;
  status: RoundStatus;
  self_due_on: string;
  manager_due_on: string;
  /** Before the reviewers' part: the day it begins by itself. */
  reviewers_begin_on: string | null;
  audience: { positions: Ref[]; branches: Ref[] };
  questions: Question[];
  progress: RoundProgress;
  /** Reviews waiting for the viewer to write. */
  mine: number;
  created_by: PersonRef | null;
  opened_at: string | null;
  manager_at: string | null;
  closed_at: string | null;
  created_at: string;
  can: { run: boolean; edit: boolean; open: boolean; advance: boolean; close: boolean; remind: boolean; delete: boolean };
}

export interface QuestionInput {
  kind: QuestionKind;
  text: string;
  key?: string;
}

export interface RoundInput {
  name: string;
  period_start: string;
  period_end: string;
  self_due_on: string;
  manager_due_on: string;
  questions: QuestionInput[];
  positions?: number[];
  branches?: number[];
  /** Open it at once (everyone in it hears). */
  open?: boolean;
}
export type RoundUpdate = Partial<Omit<RoundInput, "open">>;

export interface PreviewPerson {
  member: PersonRef;
  position: string | null;
  home_branch: BranchRef | null;
  reviewer: PersonRef | null;
}

export interface Preview {
  count: number;
  reviewers: { reviewer: PersonRef | null; people: number }[];
  people: PreviewPerson[];
}

export interface ReviewRow {
  id: number;
  member: PersonRef;
  position: string | null;
  home_branch: BranchRef | null;
  reviewer: PersonRef | null;
  self_state: SelfState;
  self_sent_at: string | null;
  manager_state: ManagerState;
  published_at: string | null;
  acknowledged_at: string | null;
  reminded_at: string | null;
  late: LatePart[];
  /** Published, and only for whoever may read the review. */
  rating: number | null;
  outcome: Outcome | null;
  outcome_state: OutcomeState | null;
  can_open: boolean;
}

export interface RowParams {
  q?: string;
  state?: RowState;
  mine?: boolean;
  branch?: number[];
}

export interface Kpis {
  taken_at: string;
  start: string;
  end: string;
  tasks: { total: number; on_time: number; late: number; missed: number; on_time_percent: string | null };
  attendance: {
    scheduled_days: number;
    attended_days: number;
    absent_days: number;
    late_arrivals: number;
    late_minutes: number;
    leave_days: number;
    worked_hours: string;
  } | null;
  discipline: { records: number; by_kind: Record<string, number> };
  /** Only with sales.view, and only when they ran a till. */
  sales: {
    shifts: number;
    net: Money;
    receipts: number;
    avg_check: Money;
    accuracy: string | null;
    shortages: number;
    shortage_total: Money;
    currency: Currency;
  } | null;
  learning: { completed: number; open: number; late: number } | null;
  goals: { open: number; done: number; missed: number } | null;
}

export interface Goal {
  id: number;
  title: string;
  target: string | null;
  unit: string;
  progress: string | null;
  due_on: string;
  status: GoalStatus;
  note: string;
  closed_at: string | null;
}

export interface GoalInput {
  title: string;
  due_on: string | null;
  target: string | null;
  unit: string;
}

export interface Review {
  id: number;
  round: { id: number; name: string; status: RoundStatus; period_start: string; period_end: string; self_due_on: string; manager_due_on: string };
  member: PersonRef;
  position: string | null;
  home_branch: BranchRef | null;
  reviewer: PersonRef | null;
  questions: Question[];
  self_part: { visible: boolean; state: SelfState; sent_at: string | null; answers: Answers | null; average: string | null };
  manager_answers: Answers;
  manager_state: ManagerState;
  manager_average: string | null;
  manager_saved_at: string | null;
  kpis: Kpis | null;
  kpis_at: string | null;
  rating: number | null;
  summary: string;
  outcome: Outcome;
  raise_percent: string | null;
  bonus_amount: Money | null;
  bonus_currency: Currency;
  promotion_position: Ref | null;
  effective_on: string | null;
  goals: Goal[];
  /** Their pay now: payroll.view only. */
  pay: { amount: Money; currency: Currency; pay_type: string; rounding_step: Money } | null;
  /** The raise or promotion as its job change; the pay before and after only with payroll.view. */
  job_change: {
    id: number;
    status: "proposed" | "approved" | "applied" | "rejected" | "cancelled";
    effective_on: string;
    parts: string[];
    pay_before: Money | null;
    pay_after: Money | null;
    error: string;
    can_decide: boolean;
  } | null;
  bonus: { id: number; amount: Money; currency: Currency; status: string; period: string } | null;
  outcome_state: OutcomeState | null;
  published_at: string | null;
  published_by: PersonRef | null;
  acknowledged_at: string | null;
  earlier: { id: number; round: string; period_end: string; rating: number | null; outcome: Outcome; published_at: string }[];
  /** draft_summary: Claude may suggest the summary (the AI module on, ai.use). */
  can: { write: boolean; pay: boolean; reassign: boolean; remove: boolean; goals: boolean; draft_summary: boolean };
}

/** Claude's suggested summary: nothing is saved until the reviewer keeps it. */
export interface SummaryDraft {
  summary: string;
  /** "claude", or "fake" (AI_FAKE's canned draft in development). */
  engine: string;
}

export interface ManagerInput {
  answers?: Answers;
  rating?: number | null;
  summary?: string;
  outcome?: Outcome;
  raise_percent?: string | null;
  bonus_amount?: Money | null;
  promotion_position_id?: number | null;
  effective_on?: string | null;
  goals?: GoalInput[];
}

export interface Results {
  people: number;
  published: number;
  average: string | null;
  /** How many people got each rating, "1" to "5". */
  spread: Record<string, number>;
  outcomes: Record<Outcome, number>;
  questions: { id: string; text: string; self_average: string | null; manager_average: string | null }[];
  by_branch: {
    branch: Ref | null;
    people: number;
    average: string | null;
    raises: number;
    bonuses: number;
    promotions: number;
    plans: number;
    raise_cost: Money | null;
    bonus_total: Money | null;
  }[];
  /** payroll.view only. */
  cost: { currency: Currency; raises_monthly: Money; raises_waiting: Money; bonuses: Money; bonuses_waiting: Money } | null;
}

export interface CareerReview {
  id: number;
  round: Ref;
  period_start: string;
  period_end: string;
  published_at: string;
  rating: number | null;
  outcome: Outcome;
  can_open: boolean;
}
