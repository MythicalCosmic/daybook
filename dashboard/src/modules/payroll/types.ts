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
  /** The metric value from which this tier applies. */
  from: string;
  amount: Money;
}

export interface Rule {
  id: number;
  name: string;
  kind: RuleKind;
  metric: RuleMetric;
  mode: RuleMode;
  op: RuleOp;
  threshold: string | null;
  free_units: number;
  tiers: RuleTier[];
  amount_type: RuleAmountType;
  amount: Money | null;
  cap: Money | null;
  min_tasks: number;
  positions: Ref[];
  evaluate: RuleEvaluate;
  auto_approve: boolean;
  is_active: boolean;
  currency: Currency;
}

export interface RuleInput {
  name: string;
  kind: RuleKind;
  metric: RuleMetric;
  mode: RuleMode;
  op: RuleOp;
  threshold: string | null;
  free_units: number;
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

export interface RulePreviewRow {
  member: Member;
  /** The metric's value for the month ("92.5", "3"). */
  value: string | null;
  amount: Money;
  /** "3 late arrivals, 2 free" */
  detail?: string;
}

export interface RulePreview {
  period: string;
  currency: Currency;
  rows: RulePreviewRow[];
  total: Money;
  /** People the rule looked at (rows are the ones who get something). */
  checked?: number;
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

export interface CurrencyTotals {
  currency: Currency;
  gross: Money;
  deductions: Money;
  net: Money;
  people: number;
}

export interface RunTotals {
  people: number;
  /** One row per currency people are paid in (so‘m first). */
  currencies: CurrencyTotals[];
  paid_people?: number;
}

export interface RunWarning {
  code: string;
  /** The server's sentence, already in the viewer's language. */
  message: string;
  member?: PersonRef | null;
  count?: number;
}

export interface Run {
  id: number;
  period: string;
  kind: RunKind;
  status: RunStatus;
  /** The one person of a final run. */
  member: Member | null;
  usd_rate: string | null;
  calculated_at: string | null;
  finalized_at: string | null;
  finalized_by: PersonRef | null;
  paid_at: string | null;
  published_at?: string | null;
  notes: string;
  warnings: RunWarning[];
  totals: RunTotals | null;
  /** What the viewer may do now, when the server says (else derived from the status and permissions). */
  actions?: RunAction[];
}

export interface PayslipLine {
  id: number;
  kind: PayslipLineKind;
  label: string;
  params: Record<string, unknown>;
  quantity: string | null;
  rate: Money | null;
  /** Signed: earnings positive, deductions negative. */
  amount: Money;
  adjustment: number | null;
  advance: number | null;
  order: number;
}

export interface Payslip {
  id: number;
  run: number;
  period: string;
  member: Member;
  currency: Currency;
  pay_type: PayType;
  base_pay?: Money | null;
  scheduled_days: string | null;
  paid_days: string | null;
  absent_days?: string | null;
  worked_minutes?: number | null;
  overtime_minutes?: number | null;
  /** Sums by line group, for the table. */
  bonuses?: Money | null;
  fines?: Money | null;
  advances?: Money | null;
  gross?: Money | null;
  deductions?: Money | null;
  net?: Money | null;
  /** Change of net against the person's previous payslip, percent; null without one. */
  change_percent?: number | null;
  status: PayslipStatus;
  published_at: string | null;
  viewed_at: string | null;
  paid_at: string | null;
  payout_method: PayoutMethod | "";
  received_at: string | null;
  run_status?: RunStatus;
  lines?: PayslipLine[];
}

export interface ManualLineInput {
  label: string;
  amount: Money;
}

export interface MarkPaidInput {
  payslip_ids: number[];
  method: PayoutMethod;
  account: number;
}

export interface PdfLink {
  url: string;
  file_name?: string;
}

// Overview ------------------------------------------------------------------------------------

export interface PayrollOverview {
  currency: Currency;
  /** This month so far and to the end at today's pay: the next payroll. */
  projected: { period: string; net: Money; gross?: Money; people: number } | null;
  months: Array<{ period: string; net: Money; gross?: Money; people: number }>;
  bonuses?: Money;
  fines?: Money;
  headcount?: number;
  next_pay_day?: string | null;
}

/** An account money may be paid from, with its currency (finance options). */
export interface PayAccount {
  id: number;
  name: string;
  kind: string;
  currency: Currency;
}
