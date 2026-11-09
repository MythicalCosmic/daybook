/**
 * The learning feature's small rules: who sees it, the order of the to-do list, which step comes
 * next, when a question counts as answered, and the words for dates (all in the company's zone).
 */
import { hasModule, isSuspended } from "../../api/membership";
import type { Membership } from "../../api/types";
import { clock, dayKey, dayMonth, daysFromToday, weekdayLong } from "../../lib/time";
import type { LearningT } from "./text";
import type { Answer, AssignmentCard, CourseDetail, CourseStep, QuestionPlay } from "./types";

/** The module switch (`companies.Feature.LEARNING`), read like every module's (`api/membership.ts`). */
export function learningOn(member: Pick<Membership, "company">): boolean {
  return hasModule(member, "learning");
}

/** The whole feature: the module is on and the person works here (a suspended person doesn't train). */
export function learningVisible(member: Pick<Membership, "company" | "status">): boolean {
  return learningOn(member) && member.status === "approved" && !isSuspended(member);
}

/** Open courses in the order they matter: late first, then the nearest deadline, then the rest. */
export function sortTodo(cards: readonly AssignmentCard[]): AssignmentCard[] {
  const due = (card: AssignmentCard) => (card.due_at ? Date.parse(card.due_at) : Number.POSITIVE_INFINITY);
  return [...cards].sort((a, b) => Number(b.late) - Number(a.late) || due(a) - due(b) || a.course.title.localeCompare(b.course.title));
}

/** The open mandatory courses (Home's card, the Me badge). */
export function openMandatory(cards: readonly AssignmentCard[] | undefined): AssignmentCard[] {
  return sortTodo((cards ?? []).filter((card) => card.course.mandatory && card.state !== "completed"));
}

/** The step "Continue" opens: the first one open and not done (a required one before an optional one). */
export function continueStep(course: Pick<CourseDetail, "steps">): CourseStep | null {
  const open = course.steps.filter((step) => !step.done && !step.locked);
  return open.find((step) => step.required) ?? open[0] ?? null;
}

/** What a step leads to, as the course page and "Next step" open it. */
export function stepTarget(kind: CourseStep["kind"], id: number, course: number | null, assignment: number | null) {
  const extra: Record<string, number> = {};
  if (course) extra.course = course;
  if (kind === "page") return { feature: "knowledge", page: "page", params: { id, ...extra } };
  if (kind === "quiz") return { feature: "learning", page: "quiz", params: { id, ...extra, ...(assignment ? { assignment } : {}) } };
  return { feature: "learning", page: "lesson", params: { id, ...extra } };
}

/** The step's target id (its lesson, page or quiz). */
export function stepObjectId(step: CourseStep): number | null {
  return step.kind === "lesson" ? step.lesson_id : step.kind === "page" ? step.page_id : step.quiz_id;
}

/**
 * Whether an answer is whole enough to save: an option picked, at least one ticked, every pair
 * matched, some text, a number. `order` always is (the shown order is an answer too).
 */
export function isAnswered(question: QuestionPlay, answer: Answer | undefined | null): boolean {
  if (!answer) return false;
  switch (question.kind) {
    case "single":
      return "option" in answer && Boolean(answer.option);
    case "multi":
      return "options" in answer && answer.options.length > 0;
    case "true_false":
      return "value" in answer && typeof answer.value === "boolean";
    case "order":
      return "order" in answer && answer.order.length === question.options.length;
    case "match":
      return "pairs" in answer && question.left.every((left) => Boolean(answer.pairs[left.id]));
    case "text":
      return "text" in answer && answer.text.trim().length > 0;
    case "number":
      return "value" in answer && typeof answer.value === "number" && Number.isFinite(answer.value);
  }
}

/** "4,5" or "4.5" as typed in Uzbek and Russian (a comma) or English; null for anything else. */
export function parseNumber(text: string): number | null {
  const clean = text.replace(/\s/g, "").replace(",", ".").replace(/[−–]/g, "-");
  if (!/^-?\d+(\.\d+)?$|^-?\.\d+$/.test(clean)) return null;
  const value = Number(clean);
  return Number.isFinite(value) ? value : null;
}

/** A number as the language writes it (4,5 in Uzbek and Russian). */
export function formatNumber(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 4 }).format(value);
}

/** A share of the points (0–1) as a whole percent. */
export const sharePercent = (share: number) => Math.round(Math.max(0, Math.min(1, share)) * 100);

/** "12.50" or 12.5 → 12.5 (decimals arrive as strings). */
export const num = (value: number | string | null | undefined): number => (value === null || value === undefined ? 0 : Number(value) || 0);

/** A score without trailing zeros: 12, 12.5. */
export function scoreText(value: number | string, locale: string): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(num(value));
}

/** "today, 10:00", "tomorrow, 10:00", "Wednesday, 10:00" (this week) or "12 Nov, 10:00". */
export function whenText(moment: string, now: Date, timeZone: string, locale: string, t: LearningT): string {
  const days = daysFromToday(moment, now, timeZone);
  const time = clock(moment, timeZone, locale);
  if (days === 0) return t("when.today", { time });
  if (days === 1) return t("when.tomorrow", { time });
  if (days > 1 && days < 7) return t("when.weekday", { day: weekdayLong(moment, timeZone, locale), time });
  return t("when.date", { date: dayMonth(moment, timeZone, locale), time });
}

/** The deadline line of a course: "Late since 5 Nov", "Due today", "Due tomorrow", "Due 12 Nov". */
export function dueText(card: Pick<AssignmentCard, "due_at" | "late">, now: Date, timeZone: string, locale: string, t: LearningT): string | null {
  if (!card.due_at) return null;
  if (card.late) return t("due.late", { date: dayMonth(card.due_at, timeZone, locale) });
  const days = daysFromToday(card.due_at, now, timeZone);
  if (days === 0) return t("due.today");
  if (days === 1) return t("due.tomorrow");
  return t("due.date", { date: dayMonth(card.due_at, timeZone, locale) });
}

/** Whether a moment is still ahead. */
export const isAhead = (moment: string | null | undefined, now: Date) => Boolean(moment && Date.parse(moment) > now.getTime());

/** The same calendar day in the company's zone. */
export const sameDay = (a: string | Date, b: string | Date, timeZone: string) => dayKey(a, timeZone) === dayKey(b, timeZone);

/** "4:05" or "1:02:05" for a countdown. */
export function countdown(seconds: number): string {
  const total = Math.max(0, Math.ceil(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;
  const two = (value: number) => String(value).padStart(2, "0");
  return hours ? `${hours}:${two(minutes)}:${two(rest)}` : `${minutes}:${two(rest)}`;
}

/** Whole minutes for a duration in seconds (at least 1 for anything there). */
export const minutesOf = (seconds: number) => (seconds > 0 ? Math.max(1, Math.round(seconds / 60)) : 0);

/** The palette keys topics and courses use (`knowledge.topics.COLORS`); anything else is plain. */
export const PALETTE = ["gray", "red", "orange", "amber", "green", "teal", "sky", "blue", "indigo", "violet", "pink"] as const;

export function hueClass(color: string | null | undefined): string {
  return (PALETTE as readonly string[]).includes(color ?? "") ? `lrn-hue--${color}` : "lrn-hue--plain";
}

/** Letters for options: A–F (the bot's buttons say the same). */
export const letter = (index: number) => String.fromCharCode(65 + index);
