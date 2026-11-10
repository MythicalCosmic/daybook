/**
 * Hiring's small rules, kept free of components so they can be tested: stage colours and order,
 * what a vacancy's state reads as, which moves tell the applicant by default, the questions a
 * pharmacist's vacancy usually asks, and the checks the vacancy form runs before saving.
 */
import type { StatusTone } from "@/components/StatusPill.vue";

import { PIPELINE, STAGES, type Answer, type Applicant, type PipelineStage, type Question, type Stage, type Vacancy, type VacancyStatus } from "./types";

export const MAX_QUESTIONS = 8;
export const MAX_OPTIONS = 6;
export const TEXT_MAX = 200;
export const OPTION_MAX = 40;

export const STAGE_TONES: Record<Stage, StatusTone> = {
  new: "primary",
  screening: "info",
  interview: "warning",
  offer: "success",
  hired: "success",
  rejected: "neutral",
};

/** Column dots on the board and the segments of a vacancy's stage bar. */
export const STAGE_COLORS: Record<Stage, string> = {
  new: "var(--c-primary)",
  screening: "var(--c-info)",
  interview: "var(--c-warning)",
  offer: "var(--c-chart-6)",
  hired: "var(--c-success)",
  rejected: "var(--c-border-strong)",
};

export const STATUS_TONES: Record<VacancyStatus, StatusTone> = {
  open: "success",
  paused: "warning",
  draft: "neutral",
  closed: "neutral",
};

/** Where an applicant goes next on the way to the hire (null once there is no next step). */
export function nextStage(stage: Stage): PipelineStage | "hired" | null {
  if (stage === "hired" || stage === "rejected") return null;
  const index = PIPELINE.indexOf(stage);
  return index < PIPELINE.length - 1 ? PIPELINE[index + 1]! : "hired";
}

/** Moves the bot tells the applicant about unless the hirer says otherwise. */
export function toldByDefault(stage: PipelineStage): boolean {
  return stage === "interview" || stage === "offer";
}

/** Where a card may be dropped: anywhere but from "hired" (and never onto the same column). */
export function canDrop(applicant: Pick<Applicant, "stage">, from: string, to: string): boolean {
  if (from === to) return true;
  if (applicant.stage === "hired") return false;
  return (STAGES as readonly string[]).includes(to);
}

export type VacancyState = "open" | "scheduled" | "ended" | "paused" | "draft" | "closed";

/** What the vacancy's badge says: open but not yet started, past its last day, or its status. */
export function vacancyState(vacancy: Pick<Vacancy, "status" | "accepting" | "opens_on" | "closes_on">, today: string): VacancyState {
  if (vacancy.status !== "open") return vacancy.status;
  if (vacancy.closes_on && vacancy.closes_on < today) return "ended";
  if (vacancy.opens_on && vacancy.opens_on > today) return "scheduled";
  return "open";
}

export const STATE_TONES: Record<VacancyState, StatusTone> = {
  open: "success",
  scheduled: "info",
  ended: "neutral",
  paused: "warning",
  draft: "neutral",
  closed: "neutral",
};

type MoneyFormat = (value: string, currency: Vacancy["currency"], options?: { currencyDisplay?: "label" | "none" }) => string;

/** "4 500 000 – 6 000 000 so‘m", "from 4 500 000 so‘m", "up to …", or null without pay. */
export function salaryText(vacancy: Pick<Vacancy, "salary_from" | "salary_to" | "currency">, money: MoneyFormat, t: (key: string, values: Record<string, string>) => string): string | null {
  const { salary_from: low, salary_to: high, currency } = vacancy;
  if (low && high) return low === high ? money(low, currency) : `${money(low, currency, { currencyDisplay: "none" })} – ${money(high, currency)}`;
  if (low) return t("hr.hiring.salaryFrom", { amount: money(low, currency) });
  if (high) return t("hr.hiring.salaryUpTo", { amount: money(high, currency) });
  return null;
}

/** Applicants still on the way (neither hired nor turned down). */
export function inProgress(counts: Vacancy["counts"]): number {
  return counts.new + counts.screening + counts.interview + counts.offer;
}

/** The stage bar's segments: stages with applicants, in order, with their share. */
export function stageSegments(counts: Vacancy["counts"]): Array<{ stage: Stage; count: number; share: number }> {
  const total = STAGES.reduce((sum, stage) => sum + counts[stage], 0);
  if (!total) return [];
  return STAGES.filter((stage) => counts[stage] > 0).map((stage) => ({ stage, count: counts[stage], share: counts[stage] / total }));
}

/** Initials for an avatar without a photo: "Aziza Karimova" → "AK", "Елена Ким" → "ЕК". */
export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  return (words.slice(0, 2).map((word) => word[0]!.toLocaleUpperCase()).join("") || "?").slice(0, 2);
}

/** Up to `count` answers worth showing on a card: answered ones, in order. */
export function highlights(answers: Answer[], count = 2): Answer[] {
  return answers.filter((row) => row.answer).slice(0, count);
}

/** `tel:` link of a phone number as stored ("+998901234567"). */
export function telLink(phone: string): string {
  return `tel:${phone.replace(/[^\d+]/g, "")}`;
}

/** "+998 90 123 45 67" for an Uzbek number, else as stored. */
export function formatPhone(phone: string): string {
  const digits = phone.replace(/\D/g, "");
  if (digits.length === 12 && digits.startsWith("998")) {
    return `+998 ${digits.slice(3, 5)} ${digits.slice(5, 8)} ${digits.slice(8, 10)} ${digits.slice(10)}`;
  }
  return phone;
}

// The vacancy form -------------------------------------------------------------------------

/** A question in the form, with a key of its own so the list animates and reorders cleanly. */
export interface DraftQuestion extends Question {
  key: string;
}

let drafted = 0;
const draftKey = () => `draft-${++drafted}`;

export function emptyQuestion(kind: Question["kind"] = "text"): DraftQuestion {
  return { key: draftKey(), text: "", kind, required: true, options: kind === "choice" ? ["", ""] : [] };
}

export function toDrafts(questions: Question[]): DraftQuestion[] {
  return questions.map((question) => ({ ...question, options: [...question.options], key: question.id ?? draftKey() }));
}

/** What a pharmacist's vacancy usually asks (docs/PLAN-OWNER.md §14.9), in the company's language. */
export function pharmacistQuestions(t: (key: string) => string): DraftQuestion[] {
  return toDrafts([
    { text: t("hr.hiring.suggest.education"), kind: "yes_no", required: true, options: [] },
    { text: t("hr.hiring.suggest.certificate"), kind: "yes_no", required: true, options: [] },
    { text: t("hr.hiring.suggest.years"), kind: "number", required: true, options: [] },
    {
      text: t("hr.hiring.suggest.shift"),
      kind: "choice",
      required: true,
      options: [t("hr.hiring.suggest.shiftDay"), t("hr.hiring.suggest.shiftNight"), t("hr.hiring.suggest.shiftAny")],
    },
    { text: t("hr.hiring.suggest.about"), kind: "text", required: false, options: [] },
  ]);
}

export type QuestionProblem = "text" | "textLong" | "options" | "optionLong" | "optionTwice";

/** The first thing wrong with a question, or null. */
export function questionProblem(question: Question): QuestionProblem | null {
  const text = question.text.trim();
  if (!text) return "text";
  if (text.length > TEXT_MAX) return "textLong";
  if (question.kind !== "choice") return null;
  const options = question.options.map((option) => option.trim()).filter(Boolean);
  if (options.length < 2) return "options";
  if (options.some((option) => option.length > OPTION_MAX)) return "optionLong";
  if (new Set(options.map((option) => option.toLocaleLowerCase())).size !== options.length) return "optionTwice";
  return null;
}

/** The questions as the server takes them: trimmed, options only for a choice. */
export function cleanQuestions(questions: Question[]): Question[] {
  return questions.map((question) => ({
    ...(question.id ? { id: question.id } : {}),
    text: question.text.trim(),
    kind: question.kind,
    required: question.required,
    options: question.kind === "choice" ? question.options.map((option) => option.trim()).filter(Boolean) : [],
  }));
}

export type VacancyProblem = "title" | "salary" | "dates";

export function vacancyProblem(form: { title: string; salary_from: string | null; salary_to: string | null; opens_on: string | null; closes_on: string | null }): VacancyProblem | null {
  if (!form.title.trim()) return "title";
  if (form.salary_from && form.salary_to && Number(form.salary_to) < Number(form.salary_from)) return "salary";
  if (form.opens_on && form.closes_on && form.closes_on < form.opens_on) return "dates";
  return null;
}
