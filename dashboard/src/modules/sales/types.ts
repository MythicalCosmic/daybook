/**
 * Shapes of the sales endpoints (plan §4.8, `apps.sales.owner_api` and `apps.sales.serializers`),
 * written by hand from the serializers like every module's types.ts: money is a decimal string,
 * days are company-local "YYYY-MM-DD", moments ISO 8601.
 */
import type { BranchRef, Currency, Money, PersonRef, Range } from "@/api/types";

export type ShiftStatus = "open" | "closed" | "verified" | "disputed";
export type MethodKind = "cash" | "card" | "qr" | "transfer" | "credit" | "installment" | "other";
export type MovementKind = "payout" | "deposit" | "handover" | "to_safe" | "from_safe" | "to_bank";
export type MovementStatus = "pending" | "declined" | "done" | "void";
export type SalesMode = "shift_totals" | "receipts" | "invoices";
export type GroupBy = "day" | "week" | "month" | "branch" | "cashier" | "method" | "hour" | "weekday_hour";

export interface Ref {
  id: number;
  name: string;
}

/** `GET/PATCH sales/settings/` */
export interface SalesSettings {
  business_day_ends_at: string;
  cash_tolerance: Money;
  blind_cash_count: boolean;
  require_z_photo: boolean;
  require_terminal_photo: boolean;
  mode: SalesMode;
  handover_confirm_hours: number;
  big_payout_alert: Money | null;
  late_open_minutes: number;
  close_alert_minutes: number;
}

/** `sales/payment-methods/` */
export interface PaymentMethod {
  id: number;
  name: string;
  kind: MethodKind;
  account: Ref | null;
  fee_percent: string;
  is_active: boolean;
  order: number;
  is_default: boolean;
}

export interface PaymentMethodInput {
  name?: string;
  kind?: MethodKind;
  account_id?: number | null;
  fee_percent?: string;
  is_active?: boolean;
}

/** `sales/registers/` */
export interface Register {
  id: number;
  name: string;
  branch: BranchRef;
  fiscal_serial: string;
  is_active: boolean;
  order: number;
  cash_account: Ref;
  cash_now: Money;
  open_shift: { id: number; code: string; cashier: PersonRef; since: string } | null;
}

export interface RegisterInput {
  name?: string;
  branch_id?: number;
  fiscal_serial?: string;
  is_active?: boolean;
}

/** A row of `GET sales/shifts/`. */
export interface ShiftRow {
  id: number;
  code: string;
  number: number;
  branch: BranchRef;
  register: Ref;
  cashier: PersonRef;
  business_day: string;
  status: ShiftStatus;
  opened_at: string;
  closed_at: string | null;
  opening_float: Money;
  net: Money;
  receipts: number;
  expected_cash: Money | null;
  /** The count that decides the difference: a manager's recount, else the cashier's. */
  counted_cash: Money | null;
  difference: Money | null;
  forced: boolean;
  ai_mismatch: boolean;
  verified_by: PersonRef | null;
  verified_at: string | null;
  has_photos: boolean;
}

export interface ShiftPayment {
  method: { id: number; name: string; kind: MethodKind };
  sales: Money;
  refunds: Money;
  net: Money;
  receipts: number;
  fee: Money;
}

export interface Movement {
  id: number;
  kind: MovementKind;
  status: MovementStatus;
  amount: Money;
  currency: Currency;
  branch: BranchRef;
  register: Ref;
  shift: { id: number; code: string } | null;
  receiver: PersonRef | null;
  to_account: Ref | null;
  category: Ref | null;
  reason: string;
  photo: string | null;
  created_by: PersonRef;
  created_at: string;
  confirmed_at: string | null;
  confirmed_by: PersonRef | null;
  declined_at: string | null;
  decline_reason: string;
  voided_at: string | null;
  void_reason: string;
}

export interface TimelineEntry {
  at: string;
  kind: string;
  actor: PersonRef | null;
  amount?: Money | null;
  status?: MovementStatus;
  receiver?: PersonRef | null;
  text?: string;
}

export interface LedgerRow {
  id: number;
  key: string;
  kind: string;
  amount: Money;
  account: Ref | null;
  category: Ref | null;
  occurred_on: string;
}

/** `GET sales/shifts/{id}/` */
export interface ShiftDetail extends ShiftRow {
  payments: ShiftPayment[];
  cash_flow: Record<"opening_float" | "cash_sales" | "cash_refunds" | MovementKind | "expected", Money>;
  opening_count: Record<string, number>;
  closing_count: Record<string, number>;
  expected_float: Money | null;
  float_difference: Money | null;
  recount_cash: Money | null;
  cashier_counted: Money | null;
  fiscal_cash_total: Money | null;
  fiscal_card_total: Money | null;
  z_number: string;
  z_photo: string | null;
  terminal_photo: string | null;
  ai_reading: Record<string, string>;
  cashier_note: string;
  note: string;
  closed_by: PersonRef | null;
  movements: Movement[];
  receipts_recorded: number;
  ledger: LedgerRow[];
  actions: { verify: boolean; dispute: boolean; correct: boolean; force_close: boolean };
  tolerance: Money;
  timeline: TimelineEntry[];
}

export interface ShiftFilters {
  branch?: string[];
  cashier?: string;
  status?: string[];
  from?: string;
  to?: string;
  has_difference?: string;
  mismatch?: string;
  q?: string;
}

export interface PaymentLineInput {
  method_id: number;
  sales: Money;
  refunds?: Money;
  receipts?: number;
}

/** Analytics shape (plan §4) of `GET sales/summary/`. */
export interface SummaryTotals {
  net: Money;
  sales: Money;
  refunds: Money;
  receipts: number;
  avg_check: Money;
  cash_share: string;
  shifts: number;
  cash_difference: Money;
}

export interface SummaryPoint {
  date?: string;
  hour?: number;
  weekday?: number;
  net: Money;
  sales?: Money;
  refunds?: Money;
  receipts: number;
  avg_check?: Money;
  previous_net?: Money;
}

export interface BreakdownRow {
  key: string;
  label: string;
  kind?: MethodKind;
  net: Money;
  sales?: Money;
  refunds?: Money;
  receipts?: number;
  avg_check?: Money;
  shifts?: number;
  share: string;
  previous_net: Money | null;
  methods?: Array<{ key: string; label: string; net: Money }>;
}

export interface SalesSummary {
  range: Range;
  compare: Range | null;
  currency: Currency;
  totals: SummaryTotals;
  previous: SummaryTotals | null;
  series: SummaryPoint[];
  breakdown: BreakdownRow[];
  estimated?: boolean;
}

/** One branch of `GET sales/today/`. */
export interface BranchTodaySales {
  id: number;
  name: string;
  code: string;
  status: "open" | "not_opened" | "closed" | "day_off";
  opens_at: string | null;
  closes_at: string | null;
  opened_at: string | null;
  opened_by: PersonRef | null;
  open_tills: Array<{ register: Ref; shift: { id: number; code: string; since: string }; cashier: PersonRef; amount: Money }>;
  tills: number;
  net: Money;
  receipts: number;
  cash_in_branch: Money;
  cash_limit: Money | null;
  target: TargetPace | null;
  alerts: Array<{ kind: "not_opened" | "difference" | "in_transit" | "over_limit"; severity: "critical" | "warning"; amount?: Money; count?: number; shift?: { id: number; code: string } }>;
}

export interface TargetPace {
  amount: Money;
  actual: Money;
  pace: Money;
  projected: Money;
  percent: string;
  days: number;
  elapsed: number;
  per_day_needed: Money | null;
  ahead: boolean;
}

export interface Target extends TargetPace {
  id: number;
  month: string;
  scope: "company" | "branch" | "person";
  branch: Ref | null;
  member: PersonRef | null;
}

export interface TargetsView {
  month: string;
  today: string;
  targets: Target[];
  series: Array<{ date: string; net: Money; cumulative: Money }>;
}

/** One row of `GET sales/cashiers/`. */
export interface CashierScore {
  member: PersonRef;
  branches: string[];
  shifts: number;
  net: Money;
  avg_per_shift: Money;
  receipts: number;
  avg_check: Money;
  accuracy: string | null;
  shortages: number;
  surpluses: number;
  shortage_total: Money;
  surplus_total: Money;
  difference_total: Money;
  verified: number;
  disputed: number;
  forced: number;
  late_opens: number;
  avg_hours: string;
  last_shift_at: string | null;
}

export interface PendingHandover {
  id: number;
  amount: Money;
  from: PersonRef;
  to: PersonRef;
  branch: Ref;
  register: Ref;
  since: string;
  hours: number;
  reason: string;
  declined_at?: string;
  decline_reason?: string;
}

/** `GET sales/cash/positions/` */
export interface CashPositions {
  currency: Currency;
  totals: Record<"tills" | "safes" | "in_transit" | "declined" | "people" | "to_bank", Money>;
  branches: Array<{
    id: number;
    name: string;
    code: string;
    cash_limit: Money | null;
    tills: Array<{ register: Ref; amount: Money; shift: { id: number; code: string; cashier: PersonRef; since: string } | null }>;
    safe: { account_id: number; name: string; amount: Money } | null;
    total: Money;
  }>;
  in_transit: PendingHandover[];
  declined: PendingHandover[];
  people: Array<{ member: PersonRef; account_id: number; amount: Money }>;
  to_bank: Array<{ id: number; amount: Money; account: Ref | null; at: string; by: PersonRef; branch: Ref }>;
  oldest_pending: PendingHandover | null;
}

export interface MovementInput {
  register_id: number;
  kind: MovementKind;
  amount: Money;
  receiver_id?: number | null;
  to_account_id?: number | null;
  category_id?: number | null;
  reason?: string;
}

/** A single receipt (`sales/entries/`). */
export interface Entry {
  id: number;
  kind: "sale" | "refund";
  number: string;
  total: Money;
  discount: Money;
  branch: BranchRef;
  register: Ref | null;
  shift: { id: number; code: string } | null;
  cashier: PersonRef | null;
  performed_by: PersonRef | null;
  sold_at: string;
  business_day: string;
  source: "app" | "dashboard" | "bot" | "import";
  note: string;
  payments: Array<{ method: { id: number; name: string; kind: MethodKind }; amount: Money }>;
  voided_at: string | null;
  void_reason: string;
}

export interface EntryInput {
  branch_id: number;
  register_id?: number | null;
  kind: "sale" | "refund";
  payments: Array<{ method_id: number; amount: Money }>;
  number?: string;
  note?: string;
}

/** `GET sales/options/`: what filters and forms pick from. */
export interface SalesOptions {
  currency: Currency;
  settings: { mode: SalesMode; blind_cash_count: boolean; cash_tolerance: Money; business_day_ends_at: string };
  today: string;
  branches: BranchRef[];
  registers: Array<{ id: number; name: string; branch_id: number; branch: string; is_active: boolean }>;
  methods: Array<{ id: number; name: string; kind: MethodKind; is_active: boolean }>;
  cashiers: Array<{ id: number; name: string; branch_ids: number[] }>;
  receivers: Array<{ id: number; name: string; branch_ids: number[] }>;
  categories: Array<{ id: number; name: string; code: string; parent_id: number | null }>;
  accounts: Array<{ id: number; name: string; kind: string; branch_id: number | null }>;
}

export interface DailyRow {
  id: number;
  day: string;
  branch: BranchRef;
  sales: Money;
  refunds: Money;
  net: Money;
  receipts: number;
  avg_check: Money;
  by_method: Record<string, { name: string; kind: MethodKind; sales: Money; refunds: Money; net: Money }>;
  shifts: number;
  cash_difference: Money;
}
