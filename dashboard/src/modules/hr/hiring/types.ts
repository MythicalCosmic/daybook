/**
 * Shapes of the hiring endpoints (`hr/vacancies/`, `hr/applicants/`), written by hand from
 * apps/hr/hiring/serializers.py. Money is a string, dates are `YYYY-MM-DD`, instants ISO.
 */
import type { Currency, Money } from "@/api/types";

export const VACANCY_STATUSES = ["open", "paused", "draft", "closed"] as const;
export type VacancyStatus = (typeof VACANCY_STATUSES)[number];

export const STAGES = ["new", "screening", "interview", "offer", "hired", "rejected"] as const;
export type Stage = (typeof STAGES)[number];
/** The stages applicants move between freely; hired and rejected have their own actions. */
export const PIPELINE = ["new", "screening", "interview", "offer"] as const;
export type PipelineStage = (typeof PIPELINE)[number];

export const QUESTION_KINDS = ["text", "choice", "yes_no", "number"] as const;
export type QuestionKind = (typeof QUESTION_KINDS)[number];

export interface Named {
  id: number;
  name: string;
}

export interface PersonRef extends Named {
  photo_url: string | null;
}

export interface BranchRef extends Named {
  code: string;
}

export interface Question {
  /** Kept by the server across edits; a new question has none until it is saved. */
  id?: string;
  text: string;
  kind: QuestionKind;
  required: boolean;
  options: string[];
}

export type StageCounts = Record<Stage, number> & { total: number };

export interface Vacancy {
  id: number;
  title: string;
  status: VacancyStatus;
  /** The link takes applications today (open, and inside its dates). */
  accepting: boolean;
  position: Named | null;
  /** The access a person hired for it gets. */
  role: Named | null;
  branch: BranchRef | null;
  description: string;
  salary_from: Money | null;
  salary_to: Money | null;
  currency: Currency;
  questions: Question[];
  asks_document: boolean;
  opens_on: string | null;
  closes_on: string | null;
  /** "" until the employee bot's username is set on the server. */
  link: string;
  qr_link: string;
  link_opens: number;
  counts: StageCounts;
  created_by: PersonRef | null;
  created_at: string;
  published_at: string | null;
  closed_at: string | null;
  /** Why the viewer can't hire for it; null when they can. */
  hire_blocker: string | null;
}

export interface VacancyInput {
  title: string;
  position_id: number | null;
  branch_id: number | null;
  description: string;
  salary_from: Money | null;
  salary_to: Money | null;
  questions: Question[];
  asks_document: boolean;
  opens_on: string | null;
  closes_on: string | null;
  /** New vacancies only: open it to applicants at once. */
  publish?: boolean;
}

export interface Answer {
  id: string;
  text: string;
  kind: QuestionKind;
  /** "yes" / "no" for a yes-or-no question; "" when skipped. */
  answer: string;
}

export interface Applicant {
  id: number;
  vacancy: Named;
  name: string;
  phone: string;
  telegram_username: string;
  language: "uz" | "ru" | "en";
  stage: Stage;
  stage_changed_at: string | null;
  source: "link" | "qr";
  answers: Answer[];
  has_document: boolean;
  rejected_reason: string;
  member: PersonRef | null;
  hired_at: string | null;
  created_at: string;
}

export interface ApplicantEvent {
  id: number;
  kind: "applied" | "moved" | "note";
  from_stage: Stage | "";
  to_stage: Stage | "";
  text: string;
  message: string;
  notified: boolean;
  by: PersonRef | null;
  created_at: string;
}

export interface ApplicantDetail extends Applicant {
  /** A signed link to their diploma photo. */
  document: string | null;
  events: ApplicantEvent[];
}

export interface ApplicantParams {
  vacancy?: number[];
  stage?: Stage[];
  source?: "link" | "qr";
  q?: string;
  page?: number;
  page_size?: number;
}
