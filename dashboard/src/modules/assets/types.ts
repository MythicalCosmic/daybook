/** Shapes of the fixed assets API (`/api/v1/owner/companies/:id/assets/…`). Money is a string. */
import type { Money } from "@/api/types";

export interface Ref {
  id: number;
  name: string;
}

export type AssetStatus = "in_use" | "in_storage" | "repair" | "suspended" | "disposed";
export type AssetCondition = "new" | "good" | "worn" | "damaged";
export type CategoryKind = "fixed" | "intangible" | "low_value";
export type Method = "straight_line" | "declining" | "sum_of_years" | "units" | "none";
export type StartRule = "next_month" | "daily";
export type Disposal = "sold" | "written_off" | "lost" | "donated";
export type UpkeepKind = "service" | "verification" | "warranty" | "insurance";
export type MonthState = "opening" | "booked" | "posted" | "planned";
export type EventKind =
  | "created"
  | "in_service"
  | "moved"
  | "issued"
  | "returned"
  | "repair"
  | "service"
  | "verification"
  | "addition"
  | "impairment"
  | "estimate"
  | "suspended"
  | "resumed"
  | "usage"
  | "problem"
  | "counted"
  | "disposed"
  | "note";

export interface TaxGroup {
  code: string;
  rate: string;
  label: string;
}

export interface AssetSettings {
  start_rule: StartRule;
  number_prefix: string;
  next_number: number;
  capitalization_threshold: Money | null;
  replacement_inflation: string;
  tax_book: boolean;
  remind_days: number;
  tax_groups: TaxGroup[];
  locked_rule: boolean;
}

export interface Category {
  id: number;
  name: string;
  kind: CategoryKind;
  life_months: number | null;
  method: Method;
  salvage_percent: string;
  tax_group: string;
  tax_rate: string | null;
  service_months: number | null;
  verify_months: number | null;
  icon: string;
  order: number;
  is_active: boolean;
  system_code: string;
  assets: number;
}

export interface Due {
  what: UpkeepKind;
  day: string;
}

export interface AssetRow {
  id: number;
  number: string;
  name: string;
  model: string;
  category: Ref;
  category_kind: CategoryKind;
  icon: string;
  branch: Ref | null;
  status: AssetStatus;
  condition: AssetCondition;
  cost: Money;
  accumulated: Money;
  book_value: Money;
  monthly: Money;
  in_service_on: string | null;
  custodian: Ref | null;
  next_due: Due | null;
  photo_url: string | null;
}

export interface Summary {
  count: number;
  cost: Money;
  accumulated: Money;
  book: Money;
  this_month: Money;
  this_year: Money;
  fully_depreciated: number;
  upkeep_due: number;
  low_value: number;
}

export interface Values {
  cost: Money;
  added: Money;
  written_down: Money;
  accumulated: Money;
  book: Money;
  salvage_value: Money;
  monthly_now: Money;
  months_used: number;
  months_left: number | null;
  end_month: string | null;
  fully_depreciated: boolean;
}

export interface ScheduleMonth {
  month: string;
  opening: Money;
  amount: Money;
  closing: Money;
  accumulated: Money;
  state: MonthState;
  notes: string[];
  transaction_id: number | null;
}

export interface TaxBook {
  rate: string;
  group: string;
  monthly: Money;
  accumulated: Money;
  book: Money;
  end_month: string | null;
  difference: Money;
}

export interface AssetEvent {
  id: number;
  kind: EventKind;
  on: string;
  amount: Money | null;
  units: string | null;
  from_branch: Ref | null;
  to_branch: Ref | null;
  person: Ref | null;
  note: string;
  details: Record<string, unknown>;
  by: string | null;
  created_at: string;
}

export interface Assignment {
  id: number;
  person: Ref;
  issued_on: string;
  condition_out: string;
  note_out: string;
  acknowledged_at: string | null;
  returned_on: string | null;
  condition_in: string;
  note_in: string;
}

export interface AssetFile {
  id: number;
  kind: "photo" | "document";
  label: string;
  url: string;
  created_at: string;
}

export interface PurchaseRef {
  id: number;
  occurred_on: string;
  amount: Money;
  currency: string;
  description: string;
  account: string | null;
  capitalized: boolean;
}

export interface AssetDetail {
  asset: AssetRow;
  serial: string;
  notes: string;
  purchased_on: string | null;
  price: Money | null;
  price_currency: string;
  price_rate: string;
  life_months: number | null;
  method: Method;
  declining_factor: string;
  total_units: string | null;
  unit: string;
  opening_accumulated: Money | null;
  books_depreciation: boolean;
  booked: boolean;
  supplier: Ref | null;
  supplier_name: string;
  purchase: PurchaseRef | null;
  responsible: Ref | null;
  warranty_until: string | null;
  insurance_until: string | null;
  service_months: number | null;
  next_service_on: string | null;
  verify_months: number | null;
  next_verification_on: string | null;
  disposed_on: string | null;
  disposal: Disposal | "";
  disposal_amount: Money | null;
  disposal_reason: string;
  qr_link: string;
  values: Values;
  schedule: ScheduleMonth[];
  tax: TaxBook | null;
  events: AssetEvent[];
  assignments: Assignment[];
  files: AssetFile[];
}

/** What the form sends (ids for the related things; null clears). */
export interface AssetInput {
  category?: number;
  name?: string;
  number?: string;
  model?: string;
  serial?: string;
  notes?: string;
  condition?: AssetCondition;
  status?: "in_use" | "in_storage" | "repair";
  branch?: number | null;
  purchased_on?: string | null;
  in_service_on?: string | null;
  cost?: Money | null;
  price?: Money | null;
  price_currency?: "UZS" | "USD";
  price_rate?: string | null;
  salvage_value?: Money | null;
  life_months?: number | null;
  method?: Method;
  declining_factor?: string;
  total_units?: string | null;
  unit?: string;
  opening_accumulated?: Money | null;
  books_depreciation?: boolean;
  supplier_name?: string;
  purchase_transaction?: number | null;
  custodian?: number | null;
  responsible?: number | null;
  warranty_until?: string | null;
  insurance_until?: string | null;
  service_months?: number | null;
  next_service_on?: string | null;
  verify_months?: number | null;
  next_verification_on?: string | null;
}

export type ActionKind =
  | "in-service"
  | "status"
  | "move"
  | "issue"
  | "return"
  | "service"
  | "verification"
  | "repair"
  | "addition"
  | "write-down"
  | "estimate"
  | "suspend"
  | "resume"
  | "usage"
  | "dispose";

export interface ReportGroup {
  id: number | null;
  name: string;
  amounts: Money[];
  total: Money;
  assets: number;
}

export interface DepreciationReport {
  year: number;
  group: "category" | "branch";
  months: string[];
  posted_through: string;
  groups: ReportGroup[];
  totals: Money[];
  total: Money;
  tax: Money[] | null;
  tax_total: Money | null;
}

export interface MovementLine {
  id?: number;
  name?: string;
  open_cost: Money;
  open_depreciation: Money;
  open_book: Money;
  in_cost: Money;
  out_cost: Money;
  out_depreciation: Money;
  depreciation: Money;
  written_down: Money;
  close_cost: Money;
  close_depreciation: Money;
  close_book: Money;
}

export interface Movement {
  start: string;
  end: string;
  lines: MovementLine[];
  total: MovementLine;
}

export interface PlanAsset {
  asset: AssetRow;
  end_month?: string;
  estimate?: Money;
  repairs?: Money;
  replacement?: Money;
  share?: Money;
}

export interface Planning {
  replacements: PlanAsset[];
  quarters: { quarter: string; count: number; amount: Money }[];
  replacement_total: Money;
  repairs: PlanAsset[];
  idle: AssetRow[];
  idle_value: Money;
  free: AssetRow[];
  upkeep: { asset: AssetRow; what: UpkeepKind; day: string; overdue: boolean }[];
  unconfirmed: { asset: Ref; person: Ref; issued_on: string }[];
  inflation: string;
}

export interface Custody {
  person: Ref;
  value: Money;
  unconfirmed: number;
  assets: AssetRow[];
}

export interface Purchase {
  id: number;
  occurred_on: string;
  amount: Money;
  currency: string;
  base_amount: Money;
  category: string | null;
  counterparty: Ref | null;
  branch: Ref | null;
  account: string | null;
  description: string;
}

export type CountResult = "pending" | "found" | "damaged" | "missing";

export interface CountLine {
  id: number;
  asset: Ref;
  number: string;
  result: CountResult;
  note: string;
  checked_by: Ref | null;
  checked_at: string | null;
}

export interface AssetCount {
  id: number;
  branch: Ref | null;
  status: "open" | "closed";
  started_on: string;
  closed_at: string | null;
  note: string;
  totals: Record<CountResult, number>;
  lines?: CountLine[];
}
