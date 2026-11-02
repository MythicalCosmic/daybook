/**
 * What the wallet shows, worked out from the API's answers without touching React: the Home
 * card, the month's parts, a payslip's state, which fines can be disputed, the advance form's
 * checks and payload, the repayment months, and a bonus rule's progress line.
 *
 * Amounts stay the server's strings: these functions pick, compare and label them, and never add
 * money up (the server's totals are the ones that count).
 */
import type { Lang } from "../../i18n";
import { amountFromTyping, compareMoney, groupDigits, decimalPoint, isDecimal, isZero, normalizeAmount } from "../../lib/money";
import type { Adjustment, AdjustmentKind, Advance, AdvanceCap, AdvanceRequest, Earnings, EarningsSums, Op, PayslipRow, Progress } from "./api";

// — the month so far —

/** What Home's card says: this month so far and the month's estimate. Nothing without a pay setup. */
export type HomePay = { amount: string; estimate: string | null; currency: string; period: string };

export function homePay(earnings: Earnings | undefined): HomePay | null {
  if (!earnings || !earnings.has_pay_setup) return null;
  const { so_far, estimate } = earnings;
  // At the month's end "so far" is the estimate: saying it twice would read as two numbers.
  const same = compareMoney(so_far.net, estimate.net) === 0;
  return { amount: so_far.net, estimate: same ? null : estimate.net, currency: earnings.currency, period: earnings.period };
}

/** The parts of a month in the order the wallet lists them. */
export const PARTS = ["base", "extra", "pieces", "bonuses", "fines", "taxes", "advances", "reimbursements"] as const;
export type Part = (typeof PARTS)[number];

/** Base pay always (even 0 on the first day), every other part only when there is some. */
export function partRows(sums: EarningsSums): { part: Part; amount: string }[] {
  return PARTS.filter((part) => part === "base" || !isZero(sums[part])).map((part) => ({ part, amount: sums[part] }));
}

// — payslips —

/**
 * new: published, not opened yet; unpaid: opened, the money hasn't gone out; confirm: paid, waiting
 * for "I received it"; received: done.
 */
export type PayslipState = "new" | "unpaid" | "confirm" | "received";

export function payslipState(row: Pick<PayslipRow, "status" | "viewed_at" | "received_at">): PayslipState {
  if (row.status === "paid") return row.received_at ? "received" : "confirm";
  return row.viewed_at ? "unpaid" : "new";
}

/** Payslips that ask something of the person (open it, say it arrived): the Me row's bubble. */
export function payslipsToSee(rows: readonly PayslipRow[] | undefined): number {
  return (rows ?? []).filter((row) => {
    const state = payslipState(row);
    return state === "new" || state === "confirm";
  }).length;
}

/** The payslip Home asks about: the newest one paid and not yet confirmed, else the newest unopened one. */
export function payslipToAsk(rows: readonly PayslipRow[] | undefined): { row: PayslipRow; state: "new" | "confirm" } | null {
  const list = rows ?? [];
  const confirm = list.find((row) => payslipState(row) === "confirm");
  if (confirm) return { row: confirm, state: "confirm" };
  const fresh = list.find((row) => payslipState(row) === "new");
  return fresh ? { row: fresh, state: "new" } : null;
}

// — bonuses and fines —

const NEGATIVE: readonly AdjustmentKind[] = ["fine", "deduction"];

export const isNegative = (kind: AdjustmentKind | string): boolean => (NEGATIVE as readonly string[]).includes(kind);

/** The amount with its direction, for display: a fine of "150000.00" reads "−150 000". */
export function signedAmount(row: { kind: AdjustmentKind | string; amount?: string | null }): string | null {
  if (!row.amount) return null;
  return isNegative(row.kind) ? `-${row.amount}` : row.amount;
}

/** A fine or deduction that stands and isn't on a closed payslip can be disputed, once. */
export function canDispute(row: Adjustment): boolean {
  return isNegative(row.kind) && (row.status === "proposed" || row.status === "approved") && !row.disputed_at && !row.locked;
}

/** Where a dispute stands: none possible, can be sent, sent and waiting, answered. */
export type DisputeStage = "none" | "can" | "waiting" | "answered";

export function disputeStage(row: Adjustment): DisputeStage {
  if (row.disputed_at) return row.dispute_answered_at ? "answered" : "waiting";
  return canDispute(row) ? "can" : "none";
}

export const DISPUTE_MAX = 500;

/** The dispute's body, or null while there is nothing (or too much) to send. */
export function disputePayload(text: string): { text: string } | null {
  const clean = text.trim();
  return clean && clean.length <= DISPUTE_MAX ? { text: clean } : null;
}

/** Rows grouped by month, newest first (the API sends them in that order). */
export function byMonth<T extends { period: string }>(rows: readonly T[]): { period: string; rows: T[] }[] {
  const groups: { period: string; rows: T[] }[] = [];
  for (const row of rows) {
    const last = groups.at(-1);
    if (last && last.period === row.period) last.rows.push(row);
    else groups.push({ period: row.period, rows: [row] });
  }
  return groups;
}

// — advances —

export const REASON_MAX = 300;
export const MAX_INSTALLMENTS = 12;

export type AdvanceProblem = "empty" | "zero" | "overCap" | "noRoom" | "reasonTooLong";
export type AdvanceDraft = { typing: string; installments: number; reason: string };

/** The request the advance form sends, or what stops it. The cap is the server's `available`. */
export function advanceDraft(draft: AdvanceDraft, cap: Pick<AdvanceCap, "available">): { payload: AdvanceRequest } | { problem: AdvanceProblem } {
  if (!isDecimal(cap.available) || compareMoney(cap.available, "0") <= 0) return { problem: "noRoom" };
  const amount = amountFromTyping(draft.typing);
  if (!amount) return { problem: "empty" };
  if (isZero(amount)) return { problem: "zero" };
  if (compareMoney(amount, cap.available) > 0) return { problem: "overCap" };
  const reason = draft.reason.trim();
  if (reason.length > REASON_MAX) return { problem: "reasonTooLong" };
  const installments = Math.min(MAX_INSTALLMENTS, Math.max(1, Math.round(draft.installments) || 1));
  return { payload: { amount: normalizeAmount(amount), installments, reason } };
}

/** Advances still going: asked, approved and waiting to be paid, or paid and being paid back. */
export const isOpenAdvance = (advance: Pick<Advance, "status">): boolean =>
  advance.status === "requested" || advance.status === "approved" || advance.status === "paid";

/** "2026-11-01" + 2 → "2027-01-01". */
export function addMonths(period: string, months: number): string {
  const [year, month] = period.split("-").map(Number);
  const index = year * 12 + (month - 1) + months;
  return `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, "0")}-01`;
}

export type RepaymentMonth = { period: string; repayment: Advance["repayments"][number] | null; done: boolean };

/**
 * The months an advance comes off the pay, from its first month, with the repayments made so
 * far against them in order (a repaid advance shows every month done).
 */
export function repaymentMonths(advance: Pick<Advance, "first_period" | "installments" | "repayments" | "status">): RepaymentMonth[] {
  const count = Math.max(1, advance.installments);
  return Array.from({ length: count }, (_, index) => {
    const repayment = advance.repayments[index] ?? null;
    return { period: addMonths(advance.first_period, index), repayment, done: advance.status === "repaid" || repayment !== null };
  });
}

// — bonus rules' progress —

/** Metrics where less is better: "at most 2 late arrivals" keeps a bonus. */
const LOWER_IS_BETTER = new Set([
  "tasks.late",
  "tasks.missed",
  "tasks.reminders_per_task",
  "tasks.avg_delay_minutes",
  "attendance.late_arrivals",
  "attendance.late_minutes",
  "attendance.absences",
  "attendance.early_leaves",
]);
const COUNTS = new Set(["tasks.done", "tasks.late", "tasks.missed", "attendance.late_arrivals", "attendance.absences", "attendance.early_leaves"]);
const MINUTES = new Set(["tasks.avg_delay_minutes", "attendance.late_minutes"]);
const TASK_METRICS = new Set(["tasks.on_time_percent", "tasks.done", "tasks.late", "tasks.missed", "tasks.reminders_per_task", "tasks.avg_delay_minutes"]);

export type MetricUnit = "percent" | "count" | "minutes" | "hours" | "money" | "number";

export function metricUnit(metric: string): MetricUnit {
  if (metric === "tasks.on_time_percent") return "percent";
  if (metric === "sales.net") return "money";
  if (metric === "attendance.hours") return "hours";
  if (COUNTS.has(metric)) return "count";
  if (MINUTES.has(metric)) return "minutes";
  return "number";
}

/** A metric's number as people read it: "90.30" → "90,3", "1250.00" → "1 250". */
export function plainNumber(value: string, lang: Lang): string {
  const [whole, fraction = ""] = value.replace(/^-/, "").split(".");
  const trimmed = fraction.replace(/0+$/, "");
  const sign = value.startsWith("-") ? "−" : "";
  return sign + groupDigits(whole, lang) + (trimmed ? decimalPoint(lang) + trimmed : "");
}

const number = (value: string | null | undefined): number | null => {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

/** What a rule's line under its bar says (keys in messages.ts; amounts stay the server's strings). */
export type ProgressCaption =
  | { key: "progress.next"; target: string; amount: string }
  | { key: "progress.atMost"; target: string; amount: string }
  | { key: "progress.keepLate"; count: number }
  | { key: "progress.keepLeft"; count: number }
  | { key: "progress.keepMinutes"; count: number }
  | { key: "progress.keepLast" }
  | { key: "progress.keepLimit"; limit: string }
  | { key: "progress.kept" }
  | { key: "progress.earned"; amount: string }
  | { key: "progress.none" }
  | { key: "progress.minTasks"; min: number; count: number };

export type ProgressView = {
  /** The rule's own name, as the owner wrote it. */
  name: string;
  metric: string;
  unit: MetricUnit;
  /** The metric so far (the server's string). */
  value: string;
  /** What the rule gives right now, when anything. */
  earned: string | null;
  /** How far along to the next step (more-is-better rules only). */
  bar: { value: number; total: number } | null;
  caption: ProgressCaption;
  /** Sage while the bonus is earned or kept; plain otherwise. */
  good: boolean;
};

/** The rule's own direction; a server from before `op` leaves it to the metric. */
function lowerIsBetter(row: Progress): boolean {
  const op = row.op as Op | undefined;
  if (op) return op === "lte" || op === "lt";
  return LOWER_IS_BETTER.has(row.metric);
}

/**
 * One bonus rule as the wallet shows it: "On time 93% · next step 95% · +300 000", or, for a rule
 * that pays while a number stays low, "2 more · the bonus stays" ("2 kechikish qoldi — bonus
 * saqlanadi").
 */
export function progressView(row: Progress): ProgressView {
  const unit = metricUnit(row.metric);
  const value = number(row.value) ?? 0;
  const earned = row.earned && !isZero(row.earned) ? row.earned : null;
  const lower = lowerIsBetter(row);
  const view = { name: row.name, metric: row.metric, unit, value: row.value, earned, bar: null, good: earned !== null };

  // Task metrics count only once there are enough tasks to judge by.
  if (TASK_METRICS.has(row.metric) && row.min_tasks !== null && row.tasks !== null && row.tasks < row.min_tasks) {
    return { ...view, good: false, caption: { key: "progress.minTasks", min: row.min_tasks, count: row.tasks } };
  }

  // An at-most rule that pays now says how much room is left before the bonus goes; a better tier
  // below (no late arrivals at all) can't be reached once a count has passed it.
  if (earned && lower) {
    const limit = number(row.limit);
    if (row.limit && limit !== null) {
      if (unit === "count" || unit === "minutes") {
        // Whole units: "at most 2" with 0 so far leaves 2; "less than 3" leaves 2 as well.
        const left = Math.floor(limit - value) - (row.op === "lt" && Number.isInteger(limit - value) ? 1 : 0);
        if (left <= 0) return { ...view, caption: { key: "progress.keepLast" } };
        if (unit === "minutes") return { ...view, caption: { key: "progress.keepMinutes", count: left } };
        // The brief's own example: "2 kechikish qoldi — bonus saqlanadi".
        if (row.metric === "attendance.late_arrivals") return { ...view, caption: { key: "progress.keepLate", count: left } };
        return { ...view, caption: { key: "progress.keepLeft", count: left } };
      }
      return { ...view, caption: { key: "progress.keepLimit", limit: row.limit } };
    }
    return { ...view, caption: { key: "progress.kept" } };
  }

  const target = number(row.target);
  if (row.target !== null && target !== null && row.target_amount && !isZero(row.target_amount)) {
    if (lower) return { ...view, caption: { key: "progress.atMost", target: row.target, amount: row.target_amount } };
    return {
      ...view,
      bar: target > 0 ? { value: Math.max(0, Math.min(value, target)), total: target } : null,
      caption: { key: "progress.next", target: row.target, amount: row.target_amount },
    };
  }

  if (earned) return { ...view, bar: lower ? null : { value: 1, total: 1 }, caption: { key: "progress.earned", amount: earned } };
  return { ...view, caption: { key: "progress.none" } };
}
