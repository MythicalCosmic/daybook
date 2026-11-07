/**
 * Shapes of the finance owner endpoints (plan §4.7), written by hand from
 * `apps/finance/owner_serializers.py` and `owner_api.py`. Money is a decimal string, days are
 * company-local "YYYY-MM-DD", instants ISO 8601.
 */
import type { Currency, Money, Page, Range } from "@/api/types";

export type AccountKind = "cash" | "bank" | "card" | "wallet" | "clearing" | "safe" | "employee" | "owner";
export type CategoryKind = "income" | "expense";
export type TransactionKind = "income" | "expense" | "transfer" | "debt_open" | "debt_payment" | "write_off" | "fx" | "owner" | "opening";
export type TransactionStatus = "pending" | "posted" | "rejected" | "void";
export type RecordKind = "income" | "expense" | "owner" | "opening";
export type DebtDirection = "receivable" | "payable";
export type DebtKind = "trade" | "bill" | "loan" | "advance" | "salary" | "reimbursement" | "tax" | "other";
export type DebtStatus = "open" | "paid" | "written_off" | "cancelled";
export type CounterpartyKind = "customer" | "supplier" | "both" | "state" | "other";
export type AgingBucket = "current" | "d1_30" | "d31_60" | "d61_90" | "d90";

export interface Ref {
  id: number;
  name: string;
}

export interface BranchRef extends Ref {
  code: string;
}

export interface AccountRef extends Ref {
  kind: AccountKind;
  currency: Currency;
  branch_id?: number | null;
}

export interface CategoryRef extends Ref {
  kind: CategoryKind;
  color: string;
  parent_name: string | null;
}

export interface SourceRef {
  type: string;
  label: string;
  id: number;
  url: string;
}

export interface RateInfo {
  rate: string | null;
  stale: boolean;
  source: string;
  date?: string;
}

// Accounts -------------------------------------------------------------------------------------

export interface Account {
  id: number;
  name: string;
  kind: AccountKind;
  kind_label: string;
  currency: Currency;
  branch: BranchRef | null;
  holder: Ref | null;
  operators: Ref[];
  bank_name: string;
  number_last4: string;
  balance: Money;
  base_balance: Money | null;
  allow_negative: boolean;
  is_active: boolean;
  order: number;
  color: string;
  spark: Money[];
  last_activity: string | null;
  can_record: boolean;
}

export interface CurrencyTotal {
  currency: Currency;
  amount: Money;
  base: Money | null;
}

export interface AccountsResponse {
  accounts: Account[];
  totals: { base: Money; complete: boolean; by_currency: CurrencyTotal[] };
  rate: RateInfo;
}

export interface AccountInput {
  name: string;
  kind: AccountKind;
  currency: Currency;
  branch?: number | null;
  holder?: number | null;
  operators?: number[];
  bank_name?: string;
  number_last4?: string;
  allow_negative?: boolean;
  color?: string;
  order?: number;
  opening_balance?: Money | null;
  opening_on?: string | null;
}

export interface StatementLine extends Transaction {
  running_balance: Money;
}

export interface Statement {
  account: Account;
  from: string;
  to: string;
  /** Today in the company's calendar. */
  today: string;
  opening: Money;
  closing: Money;
  money_in: Money;
  money_out: Money;
  lines: StatementLine[];
  pending: Transaction[];
}

// Categories -----------------------------------------------------------------------------------

export interface CategoryNode {
  id: number;
  name: string;
  kind: CategoryKind;
  parent_id: number | null;
  system_code: string;
  is_system: boolean;
  is_sensitive: boolean;
  is_capex: boolean;
  is_active: boolean;
  color: string;
  icon: string;
  order: number;
  entries: number;
  children: CategoryNode[];
}

export interface CategoryInput {
  name: string;
  kind: CategoryKind;
  parent?: number | null;
  color?: string;
  icon?: string;
  is_capex?: boolean;
  is_sensitive?: boolean;
}

// Counterparties ---------------------------------------------------------------------------------

export interface Counterparty {
  id: number;
  name: string;
  kind: CounterpartyKind;
  kind_label: string;
  phone: string;
  tin: string;
  contact_person: string;
  telegram_username: string;
  address: string;
  bank_details: string;
  notes: string;
  default_category: CategoryRef | null;
  credit_limit: Money | null;
  credit_blocked: boolean;
  birthday: string | null;
  tags: string[];
  is_active: boolean;
  owes_us: Money;
  we_owe: Money;
  overdue: Money;
  last_activity: string | null;
  created_at: string;
}

export interface CounterpartyInput {
  name?: string;
  kind?: CounterpartyKind;
  phone?: string;
  tin?: string;
  contact_person?: string;
  telegram_username?: string;
  address?: string;
  bank_details?: string;
  notes?: string;
  default_category?: number | null;
  credit_limit?: Money | null;
  credit_blocked?: boolean;
  birthday?: string | null;
  tags?: string[];
  is_active?: boolean;
}

export interface CounterpartyDetail {
  counterparty: Counterparty;
  totals: { income: Money; expense: Money; money_in: Money; money_out: Money };
  debts: Debt[];
  transactions: Transaction[];
}

// Transactions ---------------------------------------------------------------------------------

export interface Receipt {
  id: number;
  url: string;
  thumb_url: string | null;
  content_type: string;
  size: number;
  is_image: boolean;
  created_at: string;
}

export interface Transaction {
  id: number;
  kind: TransactionKind;
  kind_label: string;
  status: TransactionStatus;
  status_label: string;
  occurred_on: string;
  account: AccountRef | null;
  amount: Money;
  currency: Currency;
  rate: string;
  rate_stale: boolean;
  base_amount: Money;
  category: CategoryRef | null;
  counterparty: Ref | null;
  membership: Ref | null;
  branch: BranchRef | null;
  project: Ref | null;
  debt_id: number | null;
  transfer_id: number | null;
  is_contra: boolean;
  description: string;
  source: SourceRef | null;
  created_by: string | null;
  created_at: string;
  approved_by: string | null;
  approved_at: string | null;
  voided_by: string | null;
  voided_at: string | null;
  void_reason: string;
  receipts: Receipt[];
  masked: boolean;
  is_manual: boolean;
  can_edit: boolean;
  can_void: boolean;
  /** A waiting entry recorded here that the viewer may approve or reject (not their own). */
  can_approve: boolean;
}

export interface TransactionSummary {
  money_in: Money;
  money_out: Money;
  net: Money;
  currency: Currency;
}

export type TransactionPage = Page<Transaction> & { summary: TransactionSummary };

export interface TransactionInput {
  kind: RecordKind;
  direction?: "in" | "out";
  amount: Money;
  occurred_on: string;
  account: number;
  category?: number | null;
  counterparty?: number | null;
  member?: number | null;
  branch?: number | null;
  project?: number | null;
  description?: string;
  receipt_ids?: number[];
}

export interface TransactionPatch {
  description?: string;
  category?: number | null;
  counterparty?: number | null;
  member?: number | null;
  branch?: number | null;
  project?: number | null;
  occurred_on?: string;
  amount?: Money;
  account?: number;
}

export interface BulkResult {
  id: number;
  ok: boolean;
  error?: string;
}

// Transfers -------------------------------------------------------------------------------------

export interface Transfer {
  id: number;
  occurred_on: string;
  from_account: AccountRef;
  to_account: AccountRef;
  amount_out: Money;
  amount_in: Money;
  exchange_rate: string | null;
  fee: Money;
  description: string;
  status: "posted" | "void";
  source: SourceRef | null;
  created_by: string | null;
  created_at: string;
  voided_at: string | null;
  void_reason: string;
}

export interface TransferInput {
  from_account: number;
  to_account: number;
  amount_out: Money;
  amount_in?: Money | null;
  rate?: string | null;
  fee?: Money;
  occurred_on: string;
  description?: string;
}

// Debts -----------------------------------------------------------------------------------------

export interface DebtParty {
  type: "counterparty" | "member";
  id: number;
  name: string;
}

export interface Debt {
  id: number;
  direction: DebtDirection;
  direction_label: string;
  kind: DebtKind;
  kind_label: string;
  status: DebtStatus;
  party: DebtParty | null;
  currency: Currency;
  amount: Money;
  paid: Money;
  outstanding: Money;
  base_outstanding: Money;
  issued_on: string;
  due_on: string | null;
  days_overdue: number;
  description: string;
  branch: BranchRef | null;
  responsible: Ref | null;
  is_opening: boolean;
  is_locked: boolean;
  source: SourceRef | null;
  masked: boolean;
  created_at: string;
}

export interface Installment {
  id: number;
  due_on: string;
  amount: Money;
  paid: Money;
  status: "paid" | "partial" | "due" | "overdue";
}

export interface DebtDetail {
  debt: Debt;
  installments: Installment[];
  payments: Transaction[];
  can_pay: boolean;
  can_write_off: boolean;
  /** Not booked by another module, not reserved, and the viewer has finance.manage. */
  can_cancel: boolean;
}

export interface DebtSideTotals {
  total: Money;
  overdue: Money;
  count: number;
  overdue_count: number;
}

export type AgingTotals = Record<AgingBucket | "total", Money>;

export interface DebtSummary {
  receivable: DebtSideTotals;
  payable: DebtSideTotals;
  aging: Record<DebtDirection, AgingTotals>;
  currency: Currency;
}

export interface DebtInput {
  direction: DebtDirection;
  kind: Exclude<DebtKind, "salary" | "reimbursement">;
  mode: "account" | "category" | "opening";
  amount: Money;
  currency: Currency;
  issued_on: string;
  due_on?: string | null;
  counterparty?: number | null;
  member?: number | null;
  account?: number | null;
  category?: number | null;
  branch?: number | null;
  responsible?: number | null;
  description?: string;
}

export interface PaymentInput {
  account: number;
  amount: Money;
  debt_amount?: Money | null;
  paid_on: string;
}

// Overview and options -----------------------------------------------------------------------------

export interface CashPosition {
  on: string;
  currency: Currency;
  total: Money;
  complete: boolean;
  by_currency: CurrencyTotal[];
  accounts: Array<{ id: number; name: string; kind: AccountKind; currency: Currency; branch_id: number | null; balance: Money; base: Money | null }>;
  rate: RateInfo;
}

export interface Overview {
  currency: Currency;
  today: string;
  cash: CashPosition;
  month: {
    from: string;
    to: string;
    income: Money;
    expense: Money;
    profit: Money;
    previous: { from: string; to: string; income: Money; expense: Money; profit: Money };
  };
  receivable: DebtSideTotals;
  payable: DebtSideTotals;
  due_soon: Debt[];
  pending: { count: number; total: Money };
  top_expenses: Array<{ id: number; name: string; color: string; amount: Money }>;
  negative_accounts: CashPosition["accounts"];
  rate: RateInfo;
  has_ledger: boolean;
  locked_until: string | null;
}

export interface Options {
  base_currency: Currency;
  accounts: AccountRef[];
  transfer_targets: AccountRef[];
  members: Array<Ref & { position: string }>;
  branches: BranchRef[];
  projects: Ref[];
  receipt_required_over: Money | null;
  locked_until: string | null;
  today: string;
  rate: RateInfo;
}

// Reports ----------------------------------------------------------------------------------------

export interface PnlNode {
  id: number;
  name: string;
  color: string;
  system_code: string;
  is_sensitive: boolean;
  amounts: Money[];
  total: Money;
  own: Money[];
  own_total: Money;
  previous: Money | null;
  children: PnlNode[];
}

export interface PnlSection {
  nodes: PnlNode[];
  amounts: Money[];
  total: Money;
  previous: Money | null;
}

export interface Pnl {
  range: Range;
  compare: Range | null;
  currency: Currency;
  group: "month" | "quarter";
  periods: Array<{ key: string; from: string; to: string }>;
  income: PnlSection;
  expense: PnlSection;
  profit: { amounts: Money[]; total: Money; previous: Money | null };
  margin: { amounts: Array<string | null>; total: string | null; previous: string | null };
}

export type CashFlowSectionKey = "operating" | "investing" | "financing" | "owner" | "transfers" | "opening" | "revaluation";

export interface CashFlow {
  range: Range;
  compare: Range | null;
  currency: Currency;
  group: "day" | "week" | "month";
  totals: { income: Money; expense: Money; net: Money };
  previous: { income: Money; expense: Money; net: Money } | null;
  series: Array<{ date: string; income: Money; expense: Money; net: Money }>;
  breakdown: Array<{ key: CashFlowSectionKey; label: string; income: Money; expense: Money; net: Money }>;
  start_cash: Money;
  end_cash: Money;
}

export interface Balances extends CashPosition {
  accounts: Array<CashPosition["accounts"][number] & { kind_label: string; branch: BranchRef | null; is_active: boolean }>;
  receivable: { total: Money; count: number };
  payable: { total: Money; count: number };
  net: Money;
}

export interface AgingParty {
  type: "counterparty" | "member" | "hidden";
  id: number | null;
  name: string;
  current: Money;
  d1_30: Money;
  d31_60: Money;
  d61_90: Money;
  d90: Money;
  total: Money;
  count: number;
  oldest_due: string | null;
}

export interface Aging {
  direction: DebtDirection;
  currency: Currency;
  totals: AgingTotals;
  parties: AgingParty[];
  today: string;
}

export interface CategoryTrend {
  category: { id: number; name: string; kind: CategoryKind };
  currency: Currency;
  series: Array<{ date: string; amount: Money }>;
  average: Money;
  total: Money;
  /** The same days of last month (1 … today's day), what this month so far is compared with. */
  previous_same_days?: { from: string; to: string; amount: Money };
}

// Rates and settings -----------------------------------------------------------------------------

export interface RateRow {
  id: string;
  date: string;
  currency: Currency;
  rate: string;
  source: "cbu" | "manual" | "company";
  set_by: string | null;
  editable: boolean;
}

export interface Rates {
  currency: Currency;
  base_currency: Currency;
  foreign_currency: Currency;
  current: RateInfo & { last_fetched_at: string | null; last_official_date: string | null };
  rate_source: "cbu" | "manual";
  rows: RateRow[];
}

export interface FinanceSettings {
  locked_until: string | null;
  rate_source: "cbu" | "manual";
  approval_threshold: Money | null;
  receipt_required_over: Money | null;
  large_expense_alert: Money | null;
  reimburse_via: "payroll" | "cash";
  base_currency: Currency;
  can_reopen: boolean;
  /** Which tax the company pays (package I). */
  tax_regime: TaxRegime;
  vat_percent: string;
  /** The turnover-tax threshold in base calculation values (BHM). */
  turnover_threshold: number;
  /** One base calculation value in the base currency. */
  base_value: Money;
  /** Read-only: the owner confirmed the regime (the Get started step is done). */
  tax_regime_set: boolean;
  /** Read-only: the payroll module is on, so claims can be paid back with the payroll. */
  payroll_on: boolean;
}

// Money planning (package I): budgets, recurring rules, the tax calendar, upcoming payments, the
// cash forecast, distributor payables and expense claims, written from the v6-i API contract.

export type TaxRegime = "turnover" | "vat" | "vat_simplified";

/** A category as the planning endpoints send it: the parent's id instead of its name. */
export interface PlanCategoryRef extends Ref {
  kind: CategoryKind;
  color: string;
  parent_id: number | null;
}

export interface PersonRef extends Ref {
  photo_url: string | null;
}

/** The turnover-tax tile: income this calendar year against the threshold. */
export interface TaxSummary {
  regime: TaxRegime;
  vat_percent: string;
  year: number;
  currency: Currency;
  turnover: Money;
  /** `threshold_values` × `base_value`. */
  threshold: Money;
  threshold_values: number;
  base_value: Money;
  /** turnover / threshold with 2 decimals ("0.37"); null when the threshold is 0. */
  share: string | null;
  over: boolean;
}

// Recurring rules and the tax calendar ------------------------------------------------------------

export type RecurringMode = "bill" | "auto";
export type RecurringFrequency = "weekly" | "monthly" | "quarterly" | "yearly";
export type HolidayRule = "before" | "after" | "keep";

export interface RecurringRule {
  id: number;
  name: string;
  kind: CategoryKind;
  /** "bill": a reminder that stays open until paid or skipped; "auto": posted on its due day. */
  mode: RecurringMode;
  frequency: RecurringFrequency;
  interval: number;
  /** Weekly: 1–7 (Monday–Sunday); otherwise the day of the month, 1–31 (31 = the last day). */
  day: number;
  on_holiday: HolidayRule;
  category: PlanCategoryRef;
  counterparty: Ref | null;
  account: AccountRef | null;
  branch: Ref | null;
  amount: Money;
  currency: Currency;
  amount_varies: boolean;
  starts_on: string;
  ends_on: string | null;
  /** The open occurrence, after the holiday move; null when the rule has finished. */
  next_due_on: string | null;
  /** A bill whose open occurrence is before today. */
  overdue: boolean;
  remind_days_before: number;
  payer: PersonRef | null;
  /** The payer also gets a task for each bill, closed when it is paid or skipped. */
  create_task?: boolean;
  template_key: string;
  is_tax: boolean;
  is_active: boolean;
  last_done_on: string | null;
  /** The next three due dates, after holiday moves. */
  upcoming: string[];
  created_at: string;
}

export interface RecurringInput {
  name: string;
  kind: CategoryKind;
  mode: RecurringMode;
  frequency: RecurringFrequency;
  interval?: number;
  day: number;
  on_holiday?: HolidayRule;
  category: number;
  counterparty?: number | null;
  /** Required for an auto rule. */
  account?: number | null;
  branch?: number | null;
  amount: Money;
  amount_varies?: boolean;
  starts_on: string;
  ends_on?: string | null;
  remind_days_before?: number;
  /** A membership id. */
  payer?: number | null;
  create_task?: boolean;
  is_active?: boolean;
}

export interface RecurringPayInput {
  account: number;
  amount: Money;
  paid_on?: string;
  /** The due day the dialog showed (`next_due_on`): once it is paid, a second request is refused. */
  occurrence?: string;
}

/** What paying a bill or running an auto rule now answers. */
export interface RecurringDone {
  rule: RecurringRule;
  transaction_id: number;
}

export interface TaxTemplateItem {
  template_key: string;
  name: string;
  frequency: RecurringFrequency;
  day: number;
  category_code: string;
  applied: boolean;
  rule_id: number | null;
}

export interface TaxTemplateSet {
  key: TaxRegime;
  label: string;
  /** The company's own regime. */
  current: boolean;
  note: string;
  items: TaxTemplateItem[];
}

// Upcoming payments and the forecast ---------------------------------------------------------------

export type UpcomingKind = "bill" | "auto" | "tax" | "payable" | "receivable" | "payroll";

export interface UpcomingItem {
  /** "rule:12:2026-12-01" or "debt:44". */
  key: string;
  kind: UpcomingKind;
  title: string;
  subtitle: string;
  date: string;
  /** Null when nobody knows yet (a tax whose amount varies). */
  amount: Money | null;
  currency: Currency;
  direction: "in" | "out";
  overdue: boolean;
  estimate: boolean;
  rule_id: number | null;
  debt_id: number | null;
  url: string;
}

export interface Upcoming {
  today: string;
  days: number;
  currency: Currency;
  /** By date, the overdue ones first. */
  items: UpcomingItem[];
  /** In the base currency. */
  totals: { out: Money; in: Money; overdue_out: Money; overdue_in: Money };
}

export interface ForecastPoint {
  date: string;
  balance: Money;
  in: Money;
  out: Money;
}

export interface Forecast {
  today: string;
  days: number;
  currency: Currency;
  /** Cash now, in the base currency. */
  start: Money;
  /** One per day from today to today + days. */
  points: ForecastPoint[];
  low: { date: string; balance: Money };
  /** The first day the balance goes below zero. */
  below_zero_on: string | null;
  end: Money;
  /** The run-rate of normal sales and expenses the curve assumes. */
  basis: { daily_in: Money; daily_out: Money; days_observed: number };
  events: Array<{ date: string; title: string; amount: Money; direction: "in" | "out" }>;
}

// Budgets -------------------------------------------------------------------------------------------

/** "warning" from 80 % of the budget, "over" from 100 %. */
export type BudgetStatus = "none" | "ok" | "warning" | "over";

export interface BudgetRow {
  category: PlanCategoryRef;
  budget: Money | null;
  actual: Money;
  /** actual / budget ("0.82"); null without a budget. */
  share: string | null;
  status: BudgetStatus;
}

export interface BudgetMonth {
  /** "2026-11". */
  month: string;
  currency: Currency;
  days_left: number;
  days_in_month: number;
  /** Every active expense category, top level and children, budgeted or not. */
  rows: BudgetRow[];
  totals: { budget: Money; actual: Money };
}

export interface BudgetInput {
  month: string;
  /** A null amount removes the category's budget. */
  rows: Array<{ category: number; amount: Money | null }>;
}

// Payables ------------------------------------------------------------------------------------------

export type PayableBucket = "overdue" | "week" | "later";

export interface PayableDebt extends Debt {
  bucket: PayableBucket;
  /** A goods-receipt payable: wholesale of marked goods is paid by bank transfer. */
  bank_only: boolean;
}

export interface PayableGroup {
  counterparty: Ref;
  total: Money;
  overdue: Money;
  debts: PayableDebt[];
}

export interface Payables {
  today: string;
  currency: Currency;
  groups: PayableGroup[];
  totals: Record<PayableBucket | "all", Money>;
}

export interface PayablesPayInput {
  account: number;
  paid_on: string;
  debts: Array<{ id: number; amount: Money }>;
}

export interface PayablesPayResult {
  paid: Array<{ debt_id: number; transaction_id: number }>;
  warnings: string[];
}

export interface CreditInput {
  amount: Money;
  reason: string;
  credited_on?: string | null;
}

// Claims --------------------------------------------------------------------------------------------

export type ClaimStatus = "submitted" | "approved" | "rejected" | "paid" | "cancelled";

export interface ClaimReceipt {
  id: number;
  url: string;
  thumb_url: string | null;
  content_type: string;
  is_image: boolean;
}

export interface Claim {
  id: number;
  member: PersonRef;
  amount: Money;
  currency: Currency;
  category: PlanCategoryRef;
  spent_on: string;
  description: string;
  /** "own_money": the person paid and is owed it back; "held_cash": company cash they hold. */
  paid_from: "own_money" | "held_cash";
  status: ClaimStatus;
  status_label: string;
  branch: Ref | null;
  receipts: ClaimReceipt[];
  created_at: string;
  decided_by: PersonRef | null;
  decided_at: string | null;
  reject_reason: string;
  /** Own money only: how it is paid back. */
  reimburse_via: "payroll" | "cash" | null;
  transaction_id: number | null;
  debt_id: number | null;
  can_decide: boolean;
  can_pay: boolean;
  can_cancel: boolean;
}
