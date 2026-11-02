/**
 * The payroll module's logic without Vue: what a run allows, which payslips a payment covers,
 * which adjustments a bulk decision takes, the rule builder's payload and preview request, the
 * pay history of a person and what is locked, and whether an amount may be shown at all.
 * Amounts are never worked out here: the server computes pay (§3.17); the only sum is the
 * total of the payslips someone is about to mark paid, added exactly with decimal.js.
 */
import type { Currency, Language, Money } from "@/api/types";
import type { StatusTone } from "@/components/StatusPill.vue";
import { addMonths, formatDay, startOfMonth } from "@/lib/dates";
import { compare, dec, sum } from "@/lib/decimal";

import type {
  Adjustment,
  AdjustmentKind,
  AdjustmentStatus,
  Advance,
  AdvanceStatus,
  BulkDecideInput,
  BulkDecideRow,
  Compensation,
  Decision,
  PayAccount,
  PayoutMethod,
  PayrollSettings,
  PayRow,
  PayType,
  Payslip,
  PayslipLine,
  PayslipLineKind,
  PayslipStatus,
  Rule,
  RuleInput,
  RuleMetric,
  RuleMode,
  RuleTier,
  Run,
  RunAction,
  RunStatus,
  RunWarning,
} from "./types";

// ─── Amounts the viewer may not see ────────────────────────────────────────

/**
 * An amount the server sent. Without `payroll.view` the API leaves amounts out (absent or null):
 * the page then says "hidden", never "0".
 */
export function hasAmount(value: Money | null | undefined): value is Money {
  return value !== undefined && value !== null && value !== "";
}

// ─── Periods ────────────────────────────────────────────────────────────────

/** The period (first day of the month) a day falls in. */
export const periodOf = (day: string): string => startOfMonth(day);

export const shiftPeriod = (period: string, months: number): string => addMonths(startOfMonth(period), months);

/** The month alone, as it starts a phrase: "Noyabr" · "ноябрь" · "November" ("Prepare November payroll"). */
export function monthName(period: string, lang: Language): string {
  return formatDay(startOfMonth(period), lang, "monthYear").replace(/,?\s*\d{4}.*$/, "");
}

/** Months that already have a regular payroll (a cancelled one doesn't count). */
export function takenPeriods(runs: readonly Pick<Run, "period" | "kind" | "status">[]): Set<string> {
  return new Set(runs.filter((run) => run.kind === "regular" && run.status !== "cancelled").map((run) => run.period));
}

/**
 * The month whose payroll to prepare next, or null when there is nothing to start: last month
 * while neither it nor this month has one (its pay is due; the 1st-of-the-month job prepares it
 * the same way), else this month (a draft that fills as the month goes).
 */
export function prepareTarget(runs: readonly Pick<Run, "period" | "kind" | "status">[], today: string): string | null {
  const taken = takenPeriods(runs);
  const current = periodOf(today);
  const previous = shiftPeriod(current, -1);
  if (!taken.has(previous) && !taken.has(current)) return previous;
  if (!taken.has(current)) return current;
  return null;
}

// ─── Statuses ───────────────────────────────────────────────────────────────

export const RUN_TONES: Record<RunStatus, StatusTone> = { draft: "warning", finalized: "info", paid: "success", cancelled: "neutral" };
export const PAYSLIP_TONES: Record<PayslipStatus, StatusTone> = { draft: "neutral", published: "info", paid: "success" };
export const ADJUSTMENT_TONES: Record<AdjustmentStatus, StatusTone> = { proposed: "warning", approved: "success", rejected: "danger", void: "neutral" };
export const ADVANCE_TONES: Record<AdvanceStatus, StatusTone> = {
  requested: "warning",
  approved: "info",
  rejected: "danger",
  paid: "primary",
  repaid: "success",
  cancelled: "neutral",
};

/** Bonuses and allowances add to pay; fines and deductions take from it. */
export const isAddition = (kind: AdjustmentKind): boolean => kind === "bonus" || kind === "allowance";

/**
 * An adjustment's amount with the sign it has on pay: the API sends every amount positive, and a
 * fine shows as "−50 000 so‘m". Only the sign changes (as text); the number is the server's.
 */
export function signedAmount(row: { kind: AdjustmentKind; amount?: Money | null }): Money | null | undefined {
  if (!hasAmount(row.amount) || isAddition(row.kind)) return row.amount;
  return row.amount.startsWith("-") ? row.amount : `-${row.amount}`;
}

// ─── Runs ───────────────────────────────────────────────────────────────────

export type Can = (perm: "payroll.view" | "payroll.propose" | "payroll.manage" | "payroll.finalize" | "payroll.pay" | "data.export") => boolean;

/**
 * What the viewer may do with a run now. The server's own `actions` win when it sends them; else
 * the status decides, and each action needs its permission (§4.11): calculating and cancelling
 * need payroll.manage, finalizing, reopening and sending payslips payroll.finalize, marking paid
 * payroll.pay, the Excel export payroll.view with data.export.
 */
export function runActions(run: Pick<Run, "status" | "actions" | "calculated_at"> & { totals?: Run["totals"] }, can: Can, payslips?: readonly Pick<Payslip, "status">[]): RunAction[] {
  const allowed: Record<RunAction, boolean> = {
    calculate: can("payroll.manage"),
    finalize: can("payroll.finalize"),
    reopen: can("payroll.finalize"),
    cancel: can("payroll.manage"),
    publish: can("payroll.finalize"),
    mark_paid: can("payroll.pay"),
    export: can("payroll.view") && can("data.export"),
  };
  let actions: RunAction[];
  if (run.actions) {
    // The server's list, and the Excel export once there is something to export.
    actions = [...run.actions, ...(run.status !== "cancelled" && run.calculated_at ? (["export"] as const) : [])];
  } else {
    const unpublished = payslips ? payslips.some((slip) => slip.status === "draft") : true;
    const unpaid = payslips ? payslips.some((slip) => slip.status !== "paid") : true;
    const anyPaid = payslips ? payslips.some((slip) => slip.status === "paid") : false;
    switch (run.status) {
      case "draft":
        actions = ["calculate", ...(run.calculated_at ? (["finalize"] as const) : []), "cancel", ...(run.calculated_at ? (["export"] as const) : [])];
        break;
      case "finalized":
        actions = [...(unpublished ? (["publish"] as const) : []), ...(unpaid ? (["mark_paid"] as const) : []), ...(anyPaid ? [] : (["reopen"] as const)), "export"];
        break;
      case "paid":
        actions = ["export"];
        break;
      default:
        actions = [];
    }
  }
  return actions.filter((action) => allowed[action]);
}

/** A payslip still waiting for its money: its run is finalized and it isn't paid. */
export function isPayable(slip: Pick<Payslip, "status">, runStatus: RunStatus): boolean {
  return runStatus === "finalized" && slip.status !== "paid";
}

export interface PaySelection {
  ids: number[];
  /** Selected rows that are already paid (or can't be paid): left out. */
  skipped: number[];
  /** One total per currency, exact. */
  totals: Array<{ currency: Currency; amount: Money; count: number }>;
}

/**
 * What "Mark paid" covers for a selection: only payslips still waiting for their money, and the
 * sum of their net per currency (so‘m and dollars are never added together).
 */
export function paySelection(payslips: readonly Payslip[], selected: Iterable<number | string>, runStatus: RunStatus): PaySelection {
  const wanted = new Set([...selected].map(Number));
  const ids: number[] = [];
  const skipped: number[] = [];
  const byCurrency = new Map<Currency, Money[]>();
  for (const slip of payslips) {
    if (!wanted.has(slip.id)) continue;
    if (!isPayable(slip, runStatus) || !hasAmount(slip.net)) {
      skipped.push(slip.id);
      continue;
    }
    ids.push(slip.id);
    byCurrency.set(slip.currency, [...(byCurrency.get(slip.currency) ?? []), slip.net]);
  }
  const totals = [...byCurrency.entries()]
    .sort(([a], [b]) => (a === "UZS" ? -1 : b === "UZS" ? 1 : a.localeCompare(b)))
    .map(([currency, values]) => ({ currency, amount: sum(values), count: values.length }));
  return { ids, skipped, totals };
}

const METHOD_KINDS: Record<PayoutMethod, readonly string[]> = { cash: ["cash", "safe", "employee"], card: ["card", "bank", "wallet"], bank: ["bank"] };

/** An account of this kind is where money paid this way usually comes from. */
export const suitsMethod = (kind: string, method: PayoutMethod): boolean => METHOD_KINDS[method].includes(kind);

/**
 * Accounts in the currency being paid, the ones that suit the method first, in the method's own
 * order (cash: the till before the safe before cash someone holds), then by name.
 */
export function accountsFor(accounts: readonly PayAccount[], currency: Currency, method: PayoutMethod): PayAccount[] {
  const rank = (kind: string) => {
    const index = METHOD_KINDS[method].indexOf(kind);
    return index === -1 ? METHOD_KINDS[method].length : index;
  };
  return accounts.filter((row) => row.currency === currency).sort((a, b) => rank(a.kind) - rank(b.kind) || a.name.localeCompare(b.name));
}

/**
 * Where a warning's "Fix" goes, relative to the company (null when there is nothing to open), for
 * the server's warning codes (apps/payroll/labels.py).
 */
export function warningLink(warning: RunWarning): string | null {
  const member = warning.member?.id;
  switch (warning.code) {
    case "no_pay_setup":
      return member ? `payroll/pay?member=${member}` : "payroll/pay?missing=1";
    case "no_usd_rate":
      return "finance/settings/rates";
    case "disputes":
      return "payroll/adjustments?tab=disputed";
    case "proposed":
      return "payroll/adjustments?tab=proposed";
    case "pending_overtime":
      return "attendance/corrections";
    case "open_attendance":
      return "attendance";
    case "deductions_capped":
    case "advance_reduced":
    case "negative_net":
    case "no_scheduled_days":
      return member ? `people/${member}/pay` : null;
    default:
      return member ? `people/${member}/pay` : null;
  }
}

// ─── Payslip lines ──────────────────────────────────────────────────────────

const DEDUCTION_KINDS: ReadonlySet<PayslipLineKind> = new Set(["fine", "deduction", "advance", "loan", "income_tax", "inps"]);

export interface LineGroups {
  earnings: PayslipLine[];
  deductions: PayslipLine[];
  /** Rounding to the company's step, and anything else that is neither. */
  other: PayslipLine[];
}

/** A line someone added by hand on a draft payslip. */
export const isManualLine = (line: Pick<PayslipLine, "kind" | "manual">): boolean => line.manual === true || line.kind === "manual";

/**
 * Lines in the payslip's order (the server's, or `order` when it sends one), in three groups:
 * what is earned, what is taken, the rest.
 */
export function lineGroups(lines: readonly PayslipLine[]): LineGroups {
  const sorted = lines.map((line, index) => ({ line, index })).sort((a, b) => (a.line.order ?? a.index) - (b.line.order ?? b.index) || a.index - b.index);
  const groups: LineGroups = { earnings: [], deductions: [], other: [] };
  for (const { line } of sorted) {
    if (line.kind === "rounding") groups.other.push(line);
    else if (DEDUCTION_KINDS.has(line.kind) || (isManualLine(line) && dec(line.amount).isNegative())) groups.deductions.push(line);
    else groups.earnings.push(line);
  }
  return groups;
}

/**
 * "24 × 200 000": how a line was worked out, when the server's quantity times its rate is the
 * line's amount to the tiyin. Otherwise (a rounded quantity, a multiplier on top) the server's
 * label says how, and a product that doesn't add up is never shown.
 */
export function lineHow(line: Pick<PayslipLine, "quantity" | "rate" | "amount">): { quantity: string; rate: Money } | null {
  if (line.quantity === null || line.quantity === undefined || !hasAmount(line.rate)) return null;
  if (!dec(line.quantity).times(dec(line.rate)).toDecimalPlaces(2).abs().eq(dec(line.amount).abs())) return null;
  return { quantity: line.quantity, rate: line.rate };
}

/** A quantity as people write it: "24", "1,5" / "1.5" (no trailing zeros). */
export function quantityText(quantity: string, lang: "uz" | "ru" | "en"): string {
  const trimmed = dec(quantity).toString();
  return lang === "en" ? trimmed : trimmed.replace(".", ",");
}

// ─── Adjustments ────────────────────────────────────────────────────────────

/** An adjustment someone can still approve or reject. */
export const isDecidable = (row: Pick<Adjustment, "status">): boolean => row.status === "proposed";

/** An approved adjustment no finalized payslip took yet: it can still be voided. */
export const isVoidable = (row: Pick<Adjustment, "status" | "payslip" | "locked">): boolean => row.status === "approved" && !row.payslip && !row.locked;

export interface BulkPlan {
  ids: number[];
  /** Selected rows that are no longer waiting (decided meanwhile): left out. */
  skipped: number[];
  body: BulkDecideInput;
}

/** The bulk-decide request for a selection: only proposed rows, with the reason for a rejection. */
export function bulkPlan(rows: readonly Adjustment[], selected: Iterable<number | string>, decision: Decision, reason = ""): BulkPlan {
  const wanted = new Set([...selected].map(Number));
  const ids: number[] = [];
  const skipped: number[] = [];
  for (const row of rows) {
    if (!wanted.has(row.id)) continue;
    (isDecidable(row) ? ids : skipped).push(row.id);
  }
  const body: BulkDecideInput = decision === "reject" ? { ids, approve: false, reason: reason.trim() } : { ids, approve: true };
  return { ids, skipped, body };
}

/** How a bulk decision went, from the server's rows: decided, and the ones it refused with why. */
export function bulkOutcome(rows: readonly BulkDecideRow[]): { decided: number; refused: BulkDecideRow[] } {
  const refused = rows.filter((row) => !row.ok);
  return { decided: rows.length - refused.length, refused };
}

// ─── Rules ──────────────────────────────────────────────────────────────────

export type MetricUnit = "percent" | "count" | "minutes" | "hours" | "money" | "ratio";

export const METRICS: readonly RuleMetric[] = [
  "tasks.on_time_percent",
  "tasks.done",
  "tasks.late",
  "tasks.missed",
  "tasks.reminders_per_task",
  "tasks.avg_delay_minutes",
  "attendance.late_arrivals",
  "attendance.late_minutes",
  "attendance.absences",
  "attendance.early_leaves",
  "attendance.hours",
  "sales.net",
];

export function metricUnit(metric: RuleMetric): MetricUnit {
  switch (metric) {
    case "tasks.on_time_percent":
      return "percent";
    case "tasks.avg_delay_minutes":
    case "attendance.late_minutes":
      return "minutes";
    case "attendance.hours":
      return "hours";
    case "tasks.reminders_per_task":
      return "ratio";
    case "sales.net":
      return "money";
    default:
      return "count";
  }
}

export const metricArea = (metric: RuleMetric): "tasks" | "attendance" | "sales" => metric.slice(0, metric.indexOf(".")) as "tasks" | "attendance" | "sales";

/** Task metrics count only people with at least `min_tasks` tasks in the period. */
export const usesMinTasks = (metric: RuleMetric): boolean => metricArea(metric) === "tasks";

/** "Per unit" pays for each unit (a late arrival, a minute); a percentage has no units. */
export const allowsPerUnit = (metric: RuleMetric): boolean => metricUnit(metric) !== "percent" && metricUnit(metric) !== "ratio";

/** A percent amount is a share of the person's net sales (sales.net) or of their base pay. */
export const percentBase = (metric: RuleMetric): "sales" | "base" => (metric === "sales.net" ? "sales" : "base");

/** The builder's form: the API's rule with numbers the inputs can hold. */
export interface RuleDraft {
  name: string;
  kind: Rule["kind"];
  metric: RuleMetric;
  mode: RuleMode;
  op: Rule["op"];
  threshold: number | null;
  free_units: number | null;
  tiers: Array<{ from: number | null; amount: Money | null }>;
  amount_type: Rule["amount_type"];
  amount: Money | null;
  /** The percent as typed ("1", "2.5"), when amount_type is percent. */
  percent: number | null;
  cap: Money | null;
  min_tasks: number | null;
  positions: number[];
  evaluate: Rule["evaluate"];
  auto_approve: boolean;
  is_active: boolean;
}

export function emptyRule(kind: Rule["kind"] = "fine"): RuleDraft {
  return {
    name: "",
    kind,
    metric: kind === "fine" ? "attendance.late_arrivals" : "tasks.on_time_percent",
    mode: kind === "fine" ? "per_unit" : "once",
    op: kind === "fine" ? "gt" : "gte",
    threshold: kind === "fine" ? 0 : 95,
    free_units: kind === "fine" ? 2 : 0,
    tiers: [],
    amount_type: "fixed",
    amount: null,
    percent: null,
    cap: null,
    min_tasks: 10,
    positions: [],
    evaluate: "monthly",
    auto_approve: false,
    is_active: false,
  };
}

const numberOrNull = (value: string | null | undefined): number | null => {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

export function ruleToDraft(rule: Rule): RuleDraft {
  return {
    name: rule.name,
    kind: rule.kind,
    metric: rule.metric,
    mode: rule.mode,
    op: rule.op,
    threshold: numberOrNull(rule.threshold),
    free_units: rule.free_units,
    tiers: rule.tiers.map((tier) => ({ from: numberOrNull(tier.from), amount: tier.amount })),
    amount_type: rule.amount_type,
    amount: rule.amount_type === "fixed" ? rule.amount : null,
    percent: rule.amount_type === "percent" ? numberOrNull(rule.amount) : null,
    cap: rule.cap,
    min_tasks: rule.min_tasks,
    positions: rule.positions.map((position) => position.id),
    evaluate: rule.evaluate,
    auto_approve: rule.auto_approve,
    is_active: rule.is_active,
  };
}

const decimalText = (value: number): string => dec(value).toString();

/**
 * The request body for a draft: only the fields its mode uses (a tiered rule sends tiers and no
 * threshold or amount; "once" sends no free units), the percent as the amount when the rule pays
 * a share, positions as ids.
 */
export function ruleInput(draft: RuleDraft): RuleInput {
  const tiered = draft.mode === "tiered";
  const percent = draft.amount_type === "percent";
  const tiers: RuleTier[] = tiered
    ? draft.tiers
        .filter((tier) => tier.from !== null && hasAmount(tier.amount))
        .map((tier) => ({ from: decimalText(tier.from!), amount: tier.amount! }))
        .sort((a, b) => compare(a.from, b.from))
    : [];
  return {
    name: draft.name.trim(),
    kind: draft.kind,
    metric: draft.metric,
    mode: draft.mode,
    op: draft.op,
    threshold: tiered || draft.threshold === null ? null : decimalText(draft.threshold),
    free_units: draft.mode === "per_unit" ? Math.max(0, draft.free_units ?? 0) : 0,
    tiers,
    amount_type: tiered ? "fixed" : draft.amount_type,
    amount: tiered ? null : percent ? (draft.percent === null ? null : decimalText(draft.percent)) : draft.amount,
    cap: hasAmount(draft.cap) && !dec(draft.cap).isZero() ? draft.cap : null,
    min_tasks: usesMinTasks(draft.metric) ? Math.max(0, draft.min_tasks ?? 0) : 0,
    positions: [...draft.positions],
    evaluate: draft.evaluate,
    auto_approve: draft.auto_approve,
    is_active: draft.is_active,
  };
}

export type RuleProblem = "name" | "threshold" | "amount" | "percent" | "tiers";

/** What the form still needs before it can be saved or previewed. */
export function ruleProblems(draft: RuleDraft): RuleProblem[] {
  const problems: RuleProblem[] = [];
  if (!draft.name.trim()) problems.push("name");
  if (draft.mode === "tiered") {
    const complete = draft.tiers.filter((tier) => tier.from !== null && hasAmount(tier.amount) && dec(tier.amount!).greaterThan(0));
    if (!complete.length || complete.length !== draft.tiers.length) problems.push("tiers");
  } else {
    if (draft.threshold === null && draft.mode === "once") problems.push("threshold");
    if (draft.amount_type === "percent") {
      if (draft.percent === null || draft.percent <= 0 || draft.percent > 100) problems.push("percent");
    } else if (!hasAmount(draft.amount) || !dec(draft.amount).greaterThan(0)) {
      problems.push("amount");
    }
  }
  return problems;
}

/** The dry-run request for a month: the draft as it would be saved, and the period. */
export function previewBody(draft: RuleDraft, period: string): Record<string, unknown> {
  return { ...ruleInput(draft), period };
}

/**
 * When the metric changes, keep the form sensible: no "per unit" of a percentage or a ratio, a
 * percentage threshold within 0–100, and a sales rule that pays a share of the sales.
 */
export function adaptToMetric(draft: RuleDraft, metric: RuleMetric): RuleDraft {
  const next: RuleDraft = { ...draft, metric };
  if (!allowsPerUnit(metric) && next.mode === "per_unit") next.mode = "once";
  if (metricUnit(metric) === "percent" && next.threshold !== null && next.threshold > 100) next.threshold = 100;
  if (metric === "sales.net" && draft.metric !== "sales.net") {
    next.amount_type = "percent";
    next.mode = "once";
    next.op = "gte";
  }
  return next;
}

// ─── Pay setups ─────────────────────────────────────────────────────────────

const byNewest = (a: Compensation, b: Compensation) => (a.effective_from < b.effective_from ? 1 : a.effective_from > b.effective_from ? -1 : b.id - a.id);

export interface PayHistory {
  /** The setup in force on `today`. */
  current: Compensation | null;
  /** Every row, newest first. */
  history: Compensation[];
  /** The next one planned (the earliest that starts after today). */
  upcoming: Compensation | null;
}

/** A person's rows, newest first; the current one is the latest that has started by `today`. */
export function payHistory(rows: readonly Compensation[], today: string): PayHistory {
  const history = [...rows].sort(byNewest);
  const current = history.find((row) => row.effective_from <= today) ?? null;
  const upcoming = history.filter((row) => row.effective_from > today).at(-1) ?? null;
  return { current, history, upcoming };
}

/** Pay setups page filters, on the server's rows (today's setup and the next one). */
export function payRowMatches(row: PayRow, filter: { missing: boolean; type: PayType | "all" }): boolean {
  if (filter.missing && row.current) return false;
  if (filter.type !== "all" && row.current?.pay_type !== filter.type) return false;
  return true;
}

export type ChangePlan = { mode: "create" } | { mode: "update"; id: number } | { mode: "locked"; row: Compensation };

/**
 * What "Change pay" from `effective_from` does: a new row, or an edit of the row starting that
 * very day while no finalized run used it; a locked row on that day can't change (pick a later day).
 */
export function changePlan(history: readonly Compensation[], effectiveFrom: string): ChangePlan {
  const same = history.find((row) => row.effective_from === effectiveFrom);
  if (!same) return { mode: "create" };
  if (same.locked) return { mode: "locked", row: same };
  return { mode: "update", id: same.id };
}

/** The day "Change pay" suggests: the 1st of next month (pay usually changes with the month). */
export const suggestedEffectiveFrom = (today: string): string => shiftPeriod(today, 1);

// ─── Settings ───────────────────────────────────────────────────────────────

/** The settings panel's form: numbers the inputs hold, "HH:MM" times. */
export interface SettingsForm {
  pay_day: number | null;
  advance_day: number | null;
  advance_cap_percent: number | null;
  deductions_cap_percent: number | null;
  rounding_step: string;
  overtime_multiplier: number | null;
  holiday_work_multiplier: number | null;
  night_multiplier: number | null;
  night_starts_at: string | null;
  night_ends_at: string | null;
  daily_hours: number | null;
  amounts_are_net: boolean;
  taxes_enabled: boolean;
  income_tax_percent: number | null;
  social_tax_percent: number | null;
  inps_percent: number | null;
  auto_prepare: boolean;
}

const DECIMAL_SETTINGS = ["deductions_cap_percent", "overtime_multiplier", "holiday_work_multiplier", "night_multiplier", "daily_hours", "income_tax_percent", "social_tax_percent", "inps_percent"] as const;
const hhmm = (value: string | null | undefined): string | null => (value ? value.slice(0, 5) : null);

export function settingsForm(settings: PayrollSettings): SettingsForm {
  const decimals = Object.fromEntries(DECIMAL_SETTINGS.map((key) => [key, numberOrNull(settings[key])])) as Record<(typeof DECIMAL_SETTINGS)[number], number | null>;
  return {
    pay_day: settings.pay_day,
    advance_day: settings.advance_day,
    advance_cap_percent: settings.advance_cap_percent,
    rounding_step: dec(settings.rounding_step).toFixed(2),
    night_starts_at: hhmm(settings.night_starts_at),
    night_ends_at: hhmm(settings.night_ends_at),
    amounts_are_net: settings.amounts_are_net,
    taxes_enabled: settings.taxes_enabled,
    auto_prepare: settings.auto_prepare,
    ...decimals,
  };
}

/** Only what changed, in the API's shapes: decimals as strings, times as "HH:MM". */
export function settingsChanges(base: PayrollSettings, form: SettingsForm): Partial<PayrollSettings> {
  const before = settingsForm(base);
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(form) as Array<keyof SettingsForm>) {
    const next = form[key];
    const previous = before[key];
    if ((DECIMAL_SETTINGS as readonly string[]).includes(key)) {
      if (next === null) continue;
      if (previous === null || !dec(next as number).eq(dec(previous as number))) out[key] = dec(next as number).toFixed(2);
    } else if (next !== previous) {
      if (next === null && key !== "advance_day") continue;
      out[key] = next;
    }
  }
  return out as Partial<PayrollSettings>;
}

// ─── Advances ───────────────────────────────────────────────────────────────

export type AdvanceTab = "requests" | "to_pay" | "repaying" | "closed";

export const ADVANCE_TAB_STATUSES: Record<AdvanceTab, AdvanceStatus[]> = {
  requests: ["requested"],
  to_pay: ["approved"],
  repaying: ["paid"],
  closed: ["repaid", "rejected", "cancelled"],
};

/** Share repaid, 0–100, from the server's amounts (null when they are hidden). */
export function repaidShare(advance: Pick<Advance, "amount" | "repaid">): number | null {
  if (!hasAmount(advance.amount) || !hasAmount(advance.repaid)) return null;
  const whole = dec(advance.amount);
  if (whole.isZero()) return null;
  return Math.min(100, Math.max(0, dec(advance.repaid).dividedBy(whole).times(100).toDecimalPlaces(0).toNumber()));
}
