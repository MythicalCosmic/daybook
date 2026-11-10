/**
 * Where a disciplinary record stands for the person, without React: what it asks of them, which
 * still count, and the explanation's checks. Calm by design: nothing here grades anybody. Below:
 * the same for my leaving (what the page shows, the request's and the answers' bodies, the
 * handover's progress) and my career (changes to come and done, one line per part).
 */
import { addDays } from "../../lib/time";
import type { DisciplinaryRecord, ExitReason, JobPart, JobPay, LeavingState, MyHandoverItem, MyJobChange, Recommend } from "./api";

/**
 * withdrawn: taken back; read: issued and waiting for "Tanishdim"; done: acknowledged; past: no
 * longer counts (its time ran out).
 */
export type RecordStage = "withdrawn" | "toRead" | "done" | "past";

export function recordStage(record: Pick<DisciplinaryRecord, "status" | "active">): RecordStage {
  if (record.status === "withdrawn") return "withdrawn";
  if (record.status === "issued") return "toRead";
  return record.active ? "done" : "past";
}

/** Records that ask the person to acknowledge them: Home's card and Me's bubble. */
export function toAcknowledge(records: readonly DisciplinaryRecord[] | undefined): DisciplinaryRecord[] {
  return (records ?? []).filter((record) => recordStage(record) === "toRead");
}

/** The ones that still count first (newest first, as the API sends them), then the rest. */
export function splitRecords(records: readonly DisciplinaryRecord[]): { current: DisciplinaryRecord[]; earlier: DisciplinaryRecord[] } {
  const current = records.filter((record) => record.active && record.status !== "withdrawn");
  return { current, earlier: records.filter((record) => !current.includes(record)) };
}

/** An explanation is written once, on a record that stands. */
export const canExplain = (record: Pick<DisciplinaryRecord, "status" | "employee_response">): boolean =>
  record.status !== "withdrawn" && !record.employee_response;

export const EXPLAIN_MAX = 2000;

/** The explanation's body, or null while there is nothing (or too much) to send. */
export function explainPayload(text: string): { text: string } | null {
  const clean = text.trim();
  return clean && clean.length <= EXPLAIN_MAX ? { text: clean } : null;
}

// — My leaving —

/**
 * What the leaving page shows: the request waiting for the manager, the day agreed, the form to
 * ask (nothing open and I may ask), or none (I can't ask from here: suspended, say).
 */
export type LeavingStage = "requested" | "agreed" | "form" | "none";

export function leavingStage(state: Pick<LeavingState, "current" | "can_request">): LeavingStage {
  const status = state.current?.status;
  if (status === "requested") return "requested";
  if (status === "agreed") return "agreed";
  return state.can_request ? "form" : "none";
}

/** A request closed lately, said above the form: declined, withdrawn by me, or called off by HR. */
export type ClosedNote = "declined" | "withdrawnByMe" | "calledOff";

export function closedNote(state: Pick<LeavingState, "current">): ClosedNote | null {
  const current = state.current;
  if (current?.status === "declined") return "declined";
  if (current?.status === "withdrawn") return current.closed_by_me ? "withdrawnByMe" : "calledOff";
  return null;
}

/** Whole calendar days from `from` to `to` ("YYYY-MM-DD"): 0 the same day, 1 the next. */
export function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000);
}

/** The last day the form suggests: the usual notice after today. */
export const suggestedLastDay = (state: Pick<LeavingState, "today" | "notice_days">): string => addDays(state.today, state.notice_days);

export const LEAVE_REASON_MAX = 2000;
export const EXIT_BETTER_MAX = 1000;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** The request's body, or null while it can't go (no day, a day already past, too long a reason). */
export function leavePayload(day: string, reason: string, today: string): { wished_last_day: string; reason: string } | null {
  const clean = reason.trim();
  if (!DAY.test(day) || day < today || clean.length > LEAVE_REASON_MAX) return null;
  return { wished_last_day: day, reason: clean };
}

/** The answers' body: a main reason is the one thing asked for; the rest may stay empty. */
export function exitPayload(
  reason: ExitReason | null,
  better: string,
  recommend: Recommend | null,
): { reason: ExitReason; better: string; recommend: Recommend | "" } | null {
  const clean = better.trim();
  if (!reason || clean.length > EXIT_BETTER_MAX) return null;
  return { reason, better: clean, recommend: recommend ?? "" };
}

/** How far the handover list is: handed over, and the whole list. */
export function handoverProgress(items: readonly Pick<MyHandoverItem, "done">[]): { done: number; total: number } {
  return { done: items.filter((item) => item.done).length, total: items.length };
}

// — My career —

/** My job changes: those to come (the soonest first), then those that took effect (latest first). */
export function splitCareer(changes: readonly MyJobChange[]): { coming: MyJobChange[]; applied: MyJobChange[] } {
  const coming = changes.filter((change) => change.status === "approved").sort((a, b) => a.effective_on.localeCompare(b.effective_on));
  const applied = changes.filter((change) => change.status === "applied").sort((a, b) => b.effective_on.localeCompare(a.effective_on));
  return { coming, applied };
}

/** One line per part a change touches: what it was and what it becomes (null: none). */
export type PartChange = { part: JobPart; was: string | null; now: string | null };

export function partChanges(change: Pick<MyJobChange, "parts" | "before" | "after">, pay: (value: JobPay) => string): PartChange[] {
  return change.parts.map((part) => {
    if (part === "pay") {
      return { part, was: change.before.pay ? pay(change.before.pay) : null, now: change.after.pay ? pay(change.after.pay) : null };
    }
    return { part, was: change.before[part]?.name ?? null, now: change.after[part]?.name ?? null };
  });
}
