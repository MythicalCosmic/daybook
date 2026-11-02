/**
 * Shapes of the payroll owner endpoints (plan §3.13, §4.11, §14.11), written by hand from
 * `apps/payroll` (package H). Money is a decimal string with two decimals ("5200000.00") next to
 * its `currency`; days are company-local "YYYY-MM-DD", a period is the first day of its month,
 * instants ISO 8601. Amounts are left out of a response for someone without `payroll.view`
 * (the field is absent or null), and the console then says "hidden", never "0".
 */
import type { Currency, Money, PersonRef } from "@/api/types";

export type PayType = "monthly" | "daily" | "hourly" | "per_task";
export type Proration = "attendance" | "calendar" | "none";

export type RunStatus = "draft" | "finalized" | "paid" | "cancelled";
export type RunKind = "regular" | "final";
export type RunAction = "calculate" | "finalize" | "reopen" | "cancel" | "publish" | "mark_paid" | "export";
export type PayslipStatus = "draft" | "published" | "paid";
export type PayoutMethod = "cash" | "card" | "bank";

export type AdjustmentKind = "bonus" | "fine" | "allowance" | "deduction";
export type AdjustmentStatus = "proposed" | "approved" | "rejected" | "void";
export type AdjustmentSource = "manual" | "rule" | "task" | "attendance" | "discipline";

export type AdvanceStatus = "requested" | "approved" | "rejected" | "paid" | "repaid" | "cancelled";

export type RuleKind = "bonus" | "fine";
export type RuleMode = "once" | "per_unit" | "tiered";
export type RuleOp = "gte" | "gt" | "lte" | "lt";
export type RuleAmountType = "fixed" | "percent";
export type RuleEvaluate = "daily" | "monthly";
export type RuleMetric =
  | "tasks.on_time_percent"
  | "tasks.done"
  | "tasks.late"
  | "tasks.missed"
  | "tasks.reminders_per_task"
  | "tasks.avg_delay_minutes"
  | "attendance.late_arrivals"
  | "attendance.late_minutes"
  | "attendance.absences"
  | "attendance.early_leaves"
  | "attendance.hours"
  | "sales.net";

export type PayslipLineKind =
  | "base"
  | "proration"
  | "overtime"
  | "holiday_work"
  | "night_work"
  | "piece"
  | "task_reward"
  | "bonus"
  | "allowance"
  | "reimbursement"
  | "fine"
  | "deduction"
  | "advance"
  | "loan"
  | "income_tax"
  | "inps"
  | "leave_compensation"
  | "leave_payout"
  | "rounding"
  | "manual";

/**
 * A person as payroll names them: their membership. The pay setups list adds the position, the
 * home branch and the membership status; payslips add the branch.
 */
export interface Member extends PersonRef {
  position?: string | null;
  home_branch?: string | null;
  branch?: string | null;
  status?: string;
}

export interface Ref {
  id: number;
  name: string;
}

// Settings ------------------------------------------------------------------------------------

export interface PayrollSettings {
  currency: Currency;
  pay_day: number;
  advance_day: number | null;
  advance_cap_percent: number;
  amounts_are_net: boolean;
  taxes_enabled: boolean;
  income_tax_percent: string;
  social_tax_percent: string;
  inps_percent: string;
  deductions_cap_percent: string;
  rounding_step: Money;
  overtime_multiplier: string;
  holiday_work_multiplier: string;
  night_multiplier: string;
  /** "22:00:00" */
  night_starts_at: string;
  night_ends_at: string;
  daily_hours: string;
  auto_prepare: boolean;
  leave_payout_months?: number;
}

// Pay setups ----------------------------------------------------------------------------------

export interface Compensation {
  id: number;
  member: Member;
  effective_from: string;
  pay_type: PayType;
  amount?: Money | null;
  currency: Currency;
  proration: Proration;
  pays_task_rates: boolean;
  overtime_eligible: boolean;
  note: string;
  /** Who set it (a name). */
  created_by: string | null;
  created_at: string;
  /** Used by a finalized run: read-only, a change is a new row. */
  locked: boolean;
  /** Why it is locked, in the viewer's language. */
  locked_reason?: string | null;
}

export interface CompensationInput {
  membership: number;
  effective_from: string;
  pay_type: PayType;
  amount: Money;
  currency: Currency;
  proration: Proration;
  pays_task_rates: boolean;
  overtime_eligible: boolean;
  note: string;
}

/** One person on the pay setups page (`compensations/people/`): today's setup and the next one planned. */
export interface PayRow {
  member: Member;
  current: Compensation | null;
  next: Compensation | null;
}

// Adjustments ---------------------------------------------------------------------------------

export interface Adjustment {
  id: number;
  member: Member;
  period: string;
  kind: AdjustmentKind;
  amount?: Money | null;
  currency: Currency;
  reason: string;
  source: AdjustmentSource;
  rule: Ref | null;
  task: Ref | null;
  status: AdjustmentStatus;
  /** Names. */
  proposed_by: string | null;
  decided_by: string | null;
  decided_at: string | null;
  decision_note?: string;
  disputed_at: string | null;
  dispute_text: string;
  dispute_answer: string;
  dispute_answered_at?: string | null;
  /** Disputed and not answered yet. */
  dispute_open?: boolean;
  /** A finalized payslip took it: read-only from then on. */
  locked?: boolean;
  payslip: number | null;
  created_at: string;
}

export interface AdjustmentInput {
  membership: number;
  period: string;
  kind: AdjustmentKind;
  amount: Money;
  reason: string;
  /** Approve at once (payroll.manage). */
  approve?: boolean;
}

export type Decision = "approve" | "reject";

export interface BulkDecideInput {
  ids: number[];
  approve: boolean;
  reason?: string;
}

/** One row of the bulk decision's answer. */
export interface BulkDecideRow {
  id: number;
  ok: boolean;
  status?: string;
  error?: string;
}

// Rules ---------------------------------------------------------------------------------------

export interface RuleTier {
  /** The metric value this tier starts at, read with the rule's condition (≥ 95, ≤ 2). */
  threshold: string;
  amount: Money;
}

/** Rules are in the company's payroll currency; `amount`, `cap` and `tiers` are absent with amounts hidden. */
export interface Rule {
  id: number;
  name: string;
  kind: RuleKind;
  metric: RuleMetric;
  mode: RuleMode;
  op: RuleOp;
  threshold: string | null;
  /** Per unit: this many units a month are free ("2.00"). */
  free_units: string;
  tiers?: RuleTier[];
  amount_type: RuleAmountType;
  /** The amount, or with a percent rule the percent ("1.00" = 1 %). */
  amount?: Money | null;
  cap?: Money | null;
  min_tasks: number;
  positions: Ref[];
  evaluate: RuleEvaluate;
  auto_approve: boolean;
  is_active: boolean;
  /** One of the shipped examples (they arrive switched off). */
  example?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface RuleInput {
  name: string;
  kind: RuleKind;
  metric: RuleMetric;
  mode: RuleMode;
  op: RuleOp;
  threshold: string | null;
  free_units: string;
  tiers: RuleTier[];
  amount_type: RuleAmountType;
  amount: Money | null;
  cap: Money | null;
  min_tasks: number;
  positions: number[];
  evaluate: RuleEvaluate;
  auto_approve: boolean;
  is_active: boolean;
}

/** One person the rule applies to, whether it gives them something or not. */
export interface RulePreviewRow {
  member: Member;
  /** The metric's value for the month ("92.5", "3"); null when there was nothing to measure. */
  value: string | null;
  /** What the rule gives; null: nothing. Absent with amounts hidden. */
  amount?: Money | null;
  /** Per unit: the units counted after the free ones. */
  units: string | null;
  /** Tiered: the threshold of the tier reached. */
  tier: string | null;
}

/** A dry run of a saved rule for a month (`rules/{id}/preview/`): nothing is written. */
export interface RulePreview {
  period: string;
  /** The last day counted: today while the month is still running. */
  to: string;
  currency: Currency;
  /** Absent with amounts hidden. */
  total?: Money;
  rows: RulePreviewRow[];
}

// Advances ------------------------------------------------------------------------------------

export interface AdvanceRepayment {
  id: number;
  amount?: Money | null;
  paid_on: string;
  note: string;
  payslip: number | null;
  /** Taken from a payslip, or paid back in money. */
  how: "payslip" | "money";
}

export interface Advance {
  id: number;
  member: Member;
  amount?: Money | null;
  currency: Currency;
  installments: number;
  first_period: string;
  reason: string;
  status: AdvanceStatus;
  /** Names. */
  requested_by: string | null;
  decided_by: string | null;
  decided_at: string | null;
  decision_note?: string;
  paid_at: string | null;
  paid_by: string | null;
  payout_method: PayoutMethod | "";
  repaid?: Money | null;
  /** What is still owed. */
  left?: Money | null;
  repayments?: AdvanceRepayment[];
  debt?: number | null;
  created_at: string;
}

export interface AdvanceInput {
  membership: number;
  amount: Money;
  installments: number;
  first_period: string;
  reason: string;
}

export interface PayInput {
  method: PayoutMethod;
  account: number;
  paid_on?: string;
}

/** Money paid back outside payroll: into an account, through finance. */
export interface RepayInput {
  amount: Money;
  account: number;
  paid_on: string;
  note: string;
}

// Runs and payslips ---------------------------------------------------------------------------

/**
 * A run's totals, in the company's currency, over the payslips the viewer sees (bonuses, fines,
 * advances and reimbursements are left out for someone limited to some branches).
 */
export interface RunTotals {
  currency?: Currency;
  people: number;
  gross?: Money;
  deductions?: Money;
  net?: Money;
  bonuses?: Money;
  fines?: Money;
  advances?: Money;
  reimbursements?: Money;
  taxes?: Record<string, Money>;
  /** Payslips paid, and published (sent). */
  paid?: number;
  published?: number;
}

export interface RunWarning {
  code: string;
  /** "warning", or "info" for something worth knowing that doesn't block. */
  level?: string;
  /** The server's sentence, already in the viewer's language. */
  text: string;
  member?: PersonRef | null;
  count?: number;
}

export interface Run {
  id: number;
  period: string;
  /** The month in the viewer's language, from the server. */
  month?: string;
  kind: RunKind;
  status: RunStatus;
  /** The one person of a final run. */
  member: Member | null;
  usd_rate: string | null;
  calculated_at: string | null;
  finalized_at: string | null;
  /** A name. */
  finalized_by: string | null;
  paid_at: string | null;
  notes: string;
  warnings: RunWarning[];
  totals: RunTotals | null;
  created_at?: string;
  /** What the viewer may do now (the server says; the Excel export is ours to offer). */
  actions?: RunAction[];
}

export interface PayslipLine {
  id: number;
  kind: PayslipLineKind;
  /** Readable, with how it was worked out ("Base pay: 24 of 26 days"). */
  label: string;
  params: Record<string, unknown>;
  quantity: string | null;
  rate: Money | null;
  /** Signed: earnings positive, deductions negative. */
  amount: Money;
  adjustment: number | null;
  advance: number | null;
  /** Added by hand on a draft. */
  manual?: boolean;
  order?: number;
}

export interface Payslip {
  id: number;
  /** In a run's table; the detail has it too. */
  run?: number;
  period: string;
  member: Member;
  currency: Currency;
  pay_type: PayType;
  base_pay?: Money | null;
  /** Sums by line kind, signed as on the payslip (fines and advances negative). */
  bonuses?: Money | null;
  fines?: Money | null;
  advances?: Money | null;
  reimbursements?: Money | null;
  gross?: Money | null;
  deductions?: Money | null;
  net?: Money | null;
  status: PayslipStatus;
  published_at: string | null;
  viewed_at: string | null;
  paid_at: string | null;
  payout_method: PayoutMethod | "";
  received_at: string | null;
  // The detail only:
  run_status?: RunStatus;
  month?: string;
  scheduled_days?: string | null;
  paid_days?: string | null;
  paid_leave_days?: string | null;
  unpaid_leave_days?: string | null;
  absent_days?: string | null;
  worked_minutes?: number | null;
  overtime_minutes?: number | null;
  night_minutes?: number | null;
  late_arrivals?: number | null;
  lines?: PayslipLine[];
}

/** A hand-made line; existing ones keep their id. */
export interface ManualLineInput {
  id?: number;
  label: string;
  amount: Money;
}

export interface MarkPaidInput {
  payslip_ids: number[];
  method: PayoutMethod;
  account: number;
  paid_on?: string;
}

/** A short-lived signed link to a file (the payslip PDF). */
export interface PdfLink {
  url: string;
  name?: string;
  expires_in?: number;
}

// Overview ------------------------------------------------------------------------------------

/** A month's regular run in the overview (cancelled runs left out). */
export interface OverviewMonth {
  period: string;
  label: string;
  status: RunStatus;
  people: number;
  gross: Money;
  net: Money;
  bonuses: Money;
  fines: Money;
  advances: Money;
}

/** The latest closed month's gross by position or by branch (key "none": without one). */
export interface OverviewGroup {
  key: string;
  label: string;
  people: number;
  gross: Money;
}

/** `payroll/overview/` (payroll.view): what pay costs, month by month, and what waits. */
export interface PayrollOverview {
  currency: Currency;
  /** Oldest first. */
  months: OverviewMonth[];
  latest: { period: string; label: string } | null;
  by_position: OverviewGroup[];
  by_branch: OverviewGroup[];
  /** This month: the finalized run's sums ("run") or worked out with today's data ("estimate"). */
  projected: { period: string; label: string; source: "run" | "estimate"; people: number; gross: Money; net: Money };
  /** People with a pay setup in force today. */
  headcount: number;
  pending: { adjustments: number; disputes: number; advances: number };
}

/** An account money may be paid from, with its currency (finance options). */
export interface PayAccount {
  id: number;
  name: string;
  kind: string;
  currency: Currency;
}
