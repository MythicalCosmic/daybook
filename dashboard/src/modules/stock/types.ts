/**
 * Shapes of the stock endpoints (backend/apps/inventory/serializers.py), written by hand next to
 * the API functions. Money and quantities arrive as strings; quantities are parts (the smallest
 * piece the pharmacy sells: a blister, an ampoule), `units_per_pack` of them make a pack.
 *
 * Cost fields (a batch's cost, a receipt's total, values at cost) are absent for people without
 * finance.view: they are optional here and the pages show them only when present.
 */
import type { Money } from "@/api/types";

export type Qty = string;

export interface Ref {
  id: number;
  name: string;
}

export interface BranchRef {
  id: number;
  name: string;
  code: string;
}

export interface PersonRef {
  id: number;
  name: string;
  photo_url: string | null;
}

export interface FileLink {
  url: string;
  name: string;
  expires_in: number;
}

// Settings --------------------------------------------------------------------------------------

export type RxKind = "regular" | "benefit" | "narcotic" | "psychotropic" | "listed";

export interface StockSettings {
  expiry_steps: number[];
  min_shelf_days: number;
  fefo_strict: boolean;
  allow_negative: boolean;
  default_markup_percent: string;
  rx_max_markup_percent: string;
  social_max_markup_percent: string;
  cap_enforced: boolean;
  price_rounding: Money;
  price_jump_percent: string;
  writeoff_approval: boolean;
  show_other_branches: boolean;
  camera_scanning: boolean;
  rx_log: boolean;
  count_tolerance: Money;
  destroy_within_days: number;
  destroy_commission_min: number;
  rx_keep_months: Record<RxKind, number>;
  rx_destroy_commission_min: number;
  narcotic_rx_valid_days: number;
  psychotropic_rx_valid_months: number;
  psychotropic_stock_months: number;
  controlled_close_day: number;
  controlled_report_days: number;
}

export interface Summary {
  products: number;
  low: number;
  negative: number;
  expiring_30d: number;
  expiring_30d_retail: Money;
  expiring_30d_value?: Money;
  expired: number;
  expired_value?: Money;
  stock_value?: Money;
  stock_retail_value: Money;
  receipts_to_post: number;
  drafts: number;
  writeoffs_to_approve: number;
  transfers_disputed: number;
  transfers_incoming: number;
  recalls_open: number;
  mandatory_missing: number;
  controlled_branches: number;
  estimate: boolean;
}

// The catalogue --------------------------------------------------------------------------------

export const PRODUCT_KINDS = ["medicine", "device", "supplement", "cosmetic", "other", "service"] as const;
export type ProductKind = (typeof PRODUCT_KINDS)[number];

export const DOSAGE_FORMS = [
  "tablet",
  "capsule",
  "syrup",
  "suspension",
  "solution",
  "injection",
  "powder",
  "ointment",
  "cream",
  "gel",
  "eye_drops",
  "ear_drops",
  "nasal",
  "spray",
  "suppository",
  "patch",
  "other",
] as const;
export type DosageForm = (typeof DOSAGE_FORMS)[number];

export const CONTROL_CLASSES = ["none", "narcotic", "psychotropic", "precursor", "strong"] as const;
export type ControlClass = (typeof CONTROL_CLASSES)[number];

export const STORAGES = ["room", "cool", "cold", "frozen"] as const;
export type Storage = (typeof STORAGES)[number];

export interface Product {
  id: number;
  name: string;
  trade_name: string;
  inn: string;
  kind: ProductKind;
  dosage_form: DosageForm | "";
  strength: string;
  units_per_pack: number;
  part_label: string;
  manufacturer: Ref | null;
  category: Ref | null;
  rx_required: boolean;
  e_rx_group: boolean;
  control_class: ControlClass;
  restricted_channel: boolean;
  storage: Storage;
  light_sensitive: boolean;
  barcode: string;
  sku: string;
  mxik_code: string;
  package_code: string;
  registration_number: string;
  registration_until: string | null;
  marking_required: boolean;
  vat_percent: string | null;
  socially_significant: boolean;
  mandatory_list: boolean;
  reference_price: Money | null;
  reference_price_on: string | null;
  sale_price: Money;
  part_price: Money | null;
  effective_part_price: Money;
  cost_price?: Money | null;
  track_stock: boolean;
  is_active: boolean;
  quantity: Qty | null;
  nearest_expiry: string | null;
}

/** What the product form sends (ids for the manufacturer and category). */
export type ProductInput = Partial<Omit<Product, "id" | "manufacturer" | "category" | "effective_part_price" | "cost_price" | "quantity" | "nearest_expiry">> & {
  manufacturer?: number | null;
  category?: number | null;
};

export interface ProductPage {
  count: number;
  results: Product[];
}

export interface BranchQuantity {
  branch_id: number;
  branch: string;
  quantity: Qty;
  shortfall: Qty;
  min_qty: Qty | null;
  max_qty: Qty | null;
}

export interface Analog {
  id: number;
  name: string;
  trade_name: string;
  inn: string;
  dosage_form: string;
  strength: string;
  manufacturer: string;
  units_per_pack: number;
  part_label: string;
  rx_required: boolean;
  sale_price: Money;
  quantity: Qty;
}

/** A branch of the company, for picking where a transfer goes (`in_scope`: one of mine). */
export interface StockBranch {
  id: number;
  name: string;
  code: string;
  kind: string;
  controlled_licence: boolean;
  social_pharmacy: boolean;
  in_scope: boolean;
}

export type CodeKind = "barcode" | "supplier" | "pos";

export interface ProductCode {
  id: number;
  kind: CodeKind;
  code: string;
  supplier: Ref | null;
}

export interface ProductDetail {
  product: Product;
  branches: BranchQuantity[];
  codes: ProductCode[];
  analogs: Analog[];
  price_cap: Money | null;
}

export interface ImportRow {
  row: number;
  action: "create" | "update" | "skip";
  name: string;
  product_id: number | null;
  errors: string[];
}

export interface ImportResult {
  dry_run: boolean;
  columns: string[];
  mapping: Record<string, string>;
  created: number;
  updated: number;
  skipped: number;
  rows: ImportRow[];
}

/** A distributor's invoice spreadsheet read into a receipt's lines (a dry run first). */
export type LineImportAction = "add" | "unmatched" | "skip";

export interface LineImportRow {
  row: number;
  action: LineImportAction;
  name: string;
  product_id: number | null;
  errors: string[];
}

export interface LineImportResult {
  dry_run: boolean;
  columns: string[];
  mapping: Record<string, string>;
  added: number;
  unmatched: number;
  skipped: number;
  rows: LineImportRow[];
}

/** The regulator's rejected-series list read into recalls (a dry run first). */
export type RecallImportAction = "register" | "known" | "not_carried" | "skip";

export interface RecallImportResult {
  dry_run: boolean;
  columns: string[];
  mapping: Record<string, string>;
  registered: number;
  found: number;
  not_carried: number;
  rows: Array<{ row: number; name: string; series: string; product_id: number | null; found: number; action: RecallImportAction }>;
}

export interface Category {
  id: number;
  name: string;
  parent: number | null;
  order: number;
  products: number;
}

export interface Manufacturer {
  id: number;
  name: string;
  country: string;
}

export type OrderChannel = "telegram" | "email" | "phone" | "portal" | "other";

export interface Supplier {
  id: number;
  name: string;
  phone: string;
  tin: string;
  payment_terms_days: number | null;
  official_dealer: boolean;
  delivery_days: number;
  min_order: Money | null;
  order_channel: OrderChannel;
  telegram_username: string;
  notes: string;
  receipts: number;
}

// Stock ---------------------------------------------------------------------------------------

export type BatchStatus = "sellable" | "quarantine" | "recalled";

export interface Level {
  id: number;
  branch: BranchRef;
  product: Ref;
  inn: string;
  rx_required: boolean;
  control_class: ControlClass;
  storage: Storage;
  mandatory_list: boolean;
  units_per_pack: number;
  part_label: string;
  quantity: Qty;
  sellable: Qty;
  shortfall: Qty;
  min_qty: Qty | null;
  max_qty: Qty | null;
  low: boolean;
  nearest_expiry: string | null;
  sale_price: Money;
  value?: Money;
}

export interface Batch {
  id: number;
  batch_id: number;
  branch: BranchRef;
  product: Ref;
  series: string;
  expires_on: string;
  made_on: string | null;
  days_left: number;
  expired: boolean;
  status: BatchStatus;
  supplier: Ref | null;
  quantity: Qty;
  retail_price: Money;
  part_price: Money;
  price_cap: Money | null;
  unit_cost?: Money;
  value?: Money;
  retail_value: Money;
  receipt_id: number | null;
}

export interface ExpiryRow {
  id: number;
  batch_id: number;
  branch_id: number;
  branch: string;
  product_id: number;
  product: string;
  series: string;
  expires_on: string;
  days_left: number;
  expired: boolean;
  status: BatchStatus;
  quantity: Qty;
  units_per_pack: number;
  value?: Money;
  retail_value: Money;
}

export type BucketKey = "expired" | "d30" | "d60" | "d90";

export interface ExpiryBucket {
  key: BucketKey;
  days: number;
  count: number;
  value?: Money;
  retail_value: Money;
  rows: ExpiryRow[];
}

export interface ExpiryBoard {
  as_of: string;
  within: number;
  buckets: ExpiryBucket[];
}

export type MovementKind = "opening" | "receipt" | "sale" | "refund" | "writeoff" | "transfer_out" | "transfer_in" | "count_adjustment" | "quarantine" | "release";

export interface Movement {
  id: number;
  at: string;
  branch: BranchRef;
  product: Ref;
  series: string | null;
  kind: MovementKind;
  quantity: Qty;
  unit_cost?: Money | null;
  document_type: string;
  document_id: number | null;
  reason: string;
  by: PersonRef | null;
}

// Receipts ---------------------------------------------------------------------------------------

export type ReceiptStatus = "draft" | "submitted" | "posted" | "void";

export const RECEIPT_WARNINGS = [
  "short_shelf_life",
  "cost_jump",
  "recalled_series",
  "over_price_cap",
  "registration_expired",
  "rx_flag_mismatch",
  "not_official_dealer",
  "over_month_need",
  "not_licensed_branch",
] as const;
export type ReceiptWarning = (typeof RECEIPT_WARNINGS)[number];

export interface ReceiptLine {
  id: number;
  product: Ref;
  units_per_pack: number;
  rx_required: boolean;
  control_class: ControlClass;
  series: string;
  expires_on: string;
  made_on: string | null;
  packs: Qty;
  quantity: Qty;
  vat_percent: string | null;
  retail_price: Money | null;
  price_cap: Money | null;
  supplier_rx: boolean | null;
  warnings: ReceiptWarning[];
  unit_cost?: Money;
  total?: Money;
  batch_id: number | null;
}

export interface ReceiptLineInput {
  product: number;
  series: string;
  expires_on: string;
  made_on?: string | null;
  packs: string;
  unit_cost: Money;
  vat_percent?: string | null;
  retail_price?: Money | null;
  supplier_rx?: boolean | null;
}

export interface Receipt {
  id: number;
  number: string;
  status: ReceiptStatus;
  branch: BranchRef;
  supplier: Ref;
  supplier_invoice_number: string;
  supplier_invoice_date: string;
  currency: string;
  due_on: string | null;
  note: string;
  e_invoice_ref: string;
  lines_count: number;
  warnings: string[];
  received_by: PersonRef | null;
  posted_by: PersonRef | null;
  submitted_at: string | null;
  posted_at: string | null;
  created_at: string;
  file_url: string | null;
  total?: Money;
  vat_total?: Money;
  debt_id?: number | null;
  debt_status?: string | null;
  debt_paid?: Money | null;
  void_reason: string;
}

export interface ReceiptInput {
  branch: number;
  supplier: number;
  supplier_invoice_number?: string;
  supplier_invoice_date: string;
  due_on?: string | null;
  note?: string;
  lines?: ReceiptLineInput[];
}

export interface ReceiptDetail {
  receipt: Receipt;
  lines: ReceiptLine[];
}

// Transfers ------------------------------------------------------------------------------------

export type TransferStatus = "draft" | "sent" | "received" | "disputed" | "void";
export type Resolution = "shortage" | "found" | "returned";

export interface Transfer {
  id: number;
  number: string;
  status: TransferStatus;
  from_branch: BranchRef;
  to_branch: BranchRef;
  note: string;
  lines_count: number;
  created_at: string;
  sent_at: string | null;
  sent_by: PersonRef | null;
  received_at: string | null;
  received_by: PersonRef | null;
  resolution: Resolution | "";
  resolved_at: string | null;
  void_reason: string;
}

export interface TransferLine {
  id: number;
  product: Ref;
  units_per_pack: number;
  batch_id: number | null;
  series: string | null;
  expires_on: string | null;
  quantity_sent: Qty;
  quantity_received: Qty | null;
}

export interface TransferDetail {
  transfer: Transfer;
  lines: TransferLine[];
}

/** A batch handed to the transfer or write-off form (the expiry board's selection). */
export interface BatchPrefill {
  product: { id: number; name: string };
  unitsPerPack: number;
  partLabel: string;
  batchId: number;
  series: string;
  /** Parts. */
  quantity: number;
}

export interface TransferInput {
  from_branch: number;
  to_branch: number;
  note?: string;
  send?: boolean;
  lines: Array<{ product: number; batch?: number | null; quantity: string }>;
}

// Write-offs -----------------------------------------------------------------------------------

export const WRITEOFF_REASONS = ["expired", "damaged", "recall", "quality", "shortage", "internal_use", "other"] as const;
export type WriteOffReason = (typeof WRITEOFF_REASONS)[number];
export type WriteOffStatus = "proposed" | "approved" | "destroyed" | "void";
export const DESTRUCTION_METHODS = ["crush", "dilute", "incinerate", "disposal", "decontaminate", "other"] as const;
export type DestructionMethod = (typeof DESTRUCTION_METHODS)[number];
export type WriteOffFileKind = "photo" | "video" | "signed_act" | "order" | "other";

export interface CommissionMember {
  name: string;
  organisation?: string;
  role?: string;
}

export interface WriteOff {
  id: number;
  number: string;
  status: WriteOffStatus;
  reason: WriteOffReason;
  branch: BranchRef;
  note: string;
  lines_count: number;
  needs_destruction: boolean;
  proposed_by: PersonRef | null;
  approved_by: PersonRef | null;
  approved_at: string | null;
  created_at: string;
  destroy_by: string | null;
  responsible: string;
  order_number: string;
  commission: CommissionMember[];
  method: DestructionMethod | "";
  place: string;
  destroyed_at: string | null;
  sent_to: string[];
  act_url: string | null;
  recall_id: number | null;
  transfer_id: number | null;
  value?: Money;
  void_reason: string;
}

export interface WriteOffLine {
  id: number;
  batch_id: number;
  product: Ref;
  units_per_pack: number;
  series: string;
  expires_on: string;
  quantity: Qty;
  unit_cost?: Money;
  value?: Money;
}

export interface WriteOffFile {
  id: number;
  kind: WriteOffFileKind;
  url: string;
  at: string;
}

export interface WriteOffDetail {
  writeoff: WriteOff;
  lines: WriteOffLine[];
  files: WriteOffFile[];
  commission_min: number;
}

export interface WriteOffInput {
  branch: number;
  reason: WriteOffReason;
  note?: string;
  recall?: number | null;
  lines: Array<{ batch: number; quantity: string }>;
}

export interface DestroyedInput {
  method: DestructionMethod;
  place: string;
  destroyed_at: string;
  responsible: string;
  order_number: string;
  commission: CommissionMember[];
  sent_to?: string[];
}

// Counts -------------------------------------------------------------------------------------

export type CountKind = "full" | "partial" | "handover";
export type CountStatus = "open" | "submitted" | "applied";

export interface Count {
  id: number;
  kind: CountKind;
  status: CountStatus;
  branch: BranchRef;
  category: Ref | null;
  lines_count: number;
  counted_count: number;
  started_by: PersonRef | null;
  created_at: string;
  submitted_at: string | null;
  applied_at: string | null;
  value_difference?: Money | null;
}

export interface CountLine {
  id: number;
  product: Ref;
  units_per_pack: number;
  part_label: string;
  batch_id: number | null;
  series: string;
  expires_on: string | null;
  counted: Qty | null;
  /** Only once the count is counted, never while it is open. */
  expected?: Qty;
  difference?: Qty | null;
  value_difference?: Money;
}

export interface CountDetail {
  count: Count;
  lines: CountLine[];
}

// Recalls ------------------------------------------------------------------------------------

export interface FoundRow {
  branch_id: number;
  branch: string;
  batch_id: number;
  product_id: number;
  product: string;
  series: string;
  quantity: string;
  task_id: number | null;
  left: Qty;
  units_per_pack: number;
  part_label: string;
}

export interface Recall {
  id: number;
  product: Ref | null;
  inn_or_name: string;
  series: string;
  reason: string;
  source: string;
  received_on: string;
  status: "open" | "closed";
  found: FoundRow[];
  left: Qty;
  file_url: string | null;
  closed_at: string | null;
  created_at: string;
}

export interface RecallInput {
  product?: number | null;
  inn_or_name?: string;
  series: string;
  reason: string;
  source: string;
  received_on: string;
}

// Pricing rules and defektura -------------------------------------------------------------------

export interface PricingRule {
  id: number;
  category: number | null;
  category_name: string | null;
  cost_from: Money | null;
  cost_to: Money | null;
  markup_percent: string;
  order: number;
  is_active: boolean;
}

export type PricingRuleInput = Partial<Omit<PricingRule, "id" | "category_name">>;

export type RequestStatus = "open" | "ordered" | "fulfilled" | "cancelled";

export interface MissingRequest {
  id: number;
  branch_ref: BranchRef;
  product_ref: Ref | null;
  name: string;
  packs: string;
  source: "counter" | "mandatory";
  status: RequestStatus;
  customer_phone: string;
  requested_at: string;
  requested_by: PersonRef | null;
}

export interface MissingRequestInput {
  branch: number;
  product?: number | null;
  name?: string;
  packs?: string;
  customer_phone?: string;
}

// Journals -------------------------------------------------------------------------------------

export interface ControlledRow {
  id: number;
  product_id: number;
  product: string;
  inn: string;
  control_class: ControlClass;
  units_per_pack: number;
  opening: Qty;
  received: Qty;
  issued: Qty;
  written_off: Qty;
  adjusted: Qty;
  closing: Qty;
  unrecorded_issues: number;
  period_id: number | null;
  counted: Qty | null;
  difference: Qty | null;
  closed_at: string | null;
  reported_on: string | null;
}

export interface ControlledRegister {
  branch: BranchRef;
  month: string;
  closed: boolean;
  close_by: string;
  rows: ControlledRow[];
  branches: BranchRef[];
}

export type RxStatus = "dispensed" | "invalid";

export interface RxRecord {
  id: number;
  branch: BranchRef;
  product: Ref;
  series: string | null;
  quantity: Qty;
  prescription_number: string;
  prescribed_on: string | null;
  prescriber: string;
  facility: string;
  rx_kind: RxKind;
  status: RxStatus;
  invalid_reason: string;
  facility_notified_at: string | null;
  e_prescription_id: string;
  keep_until: string;
  recorded_at: string;
  recorded_by: PersonRef | null;
  flags: string[];
}

export interface RxJournal {
  branch: BranchRef;
  month: string;
  rows: RxRecord[];
}
