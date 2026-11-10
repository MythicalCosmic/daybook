/**
 * Equipment's shapes (`lifecycle/equipment/…`, backend/apps/lifecycle/equipment), hand-written until
 * the lead regenerates the schema types. Money is a string ("380000.00"), null when the viewer may
 * not see what things cost (assets.manage or finance.view; a deduction's amount: payroll.view).
 */
import type { Money } from "@/api/types";

export type CategoryKind = "fixed" | "intangible" | "low_value";
export type Condition = "new" | "good" | "worn" | "damaged";
export const CONDITIONS = ["new", "good", "worn", "damaged"] as const;

export interface CategoryRef {
  id: number;
  name: string;
  /** A lucide icon name. */
  icon: string;
  kind: CategoryKind;
}

export interface BranchRef {
  id: number;
  name: string;
  code: string;
}

export interface Deduction {
  id: number;
  /** Only with payroll.view. */
  amount: Money | null;
  currency: string;
  status: "proposed" | "approved" | "rejected" | "void";
}

/** Something a person holds: the hand-out and its asset. */
export interface HeldItem {
  assignment_id: number;
  asset_id: number;
  number: string;
  name: string;
  model: string;
  serial: string;
  /** A size, for a uniform. */
  notes: string;
  category: CategoryRef;
  branch: BranchRef | null;
  issued_on: string;
  condition_out: Condition;
  note_out: string;
  acknowledged_at: string | null;
  /** The photo taken when it was given, else one of the asset. */
  photo_url: string | null;
  value: Money | null;
  deduction: Deduction | null;
  /** A device needs assets.manage to be written off. */
  may_write_off: boolean;
}

export interface EquipmentPerson {
  id: number;
  name: string;
  photo_url: string | null;
  position: string | null;
  home_branch: BranchRef | null;
  status: "approved" | "suspended" | "left" | "blocked";
}

export interface Holder {
  person: EquipmentPerson;
  leaving: { id: number; status: "requested" | "agreed"; day: string | null } | null;
  left_on: string | null;
  items: HeldItem[];
  value: Money | null;
  unconfirmed: number;
  /** Items still held by someone who has left. */
  overdue: number;
  /** Leaves within two weeks, holding items. */
  leaving_soon: boolean;
}

export interface EquipmentTotals {
  people: number;
  items: number;
  unconfirmed: number;
  to_return: number;
  value: Money | null;
  in_stock: number;
}

export interface EquipmentCan {
  /** Sees what things cost. */
  values: boolean;
  /** Adds and writes off devices (assets.manage). */
  devices: boolean;
  /** Payroll is on: deductions can be proposed. */
  deduct: boolean;
  /** Sees a deduction's amount. */
  pay: boolean;
  /** Opens the asset register. */
  register: boolean;
}

export interface EquipmentPeople {
  today: string;
  people: Holder[];
  totals: EquipmentTotals;
  can: EquipmentCan;
}

export interface StockItem {
  id: number;
  number: string;
  name: string;
  model: string;
  serial: string;
  notes: string;
  category: CategoryRef;
  branch: BranchRef | null;
  status: "in_use" | "in_storage" | "repair" | "suspended";
  condition: Condition;
  value: Money | null;
  holder: { id: number; name: string; photo_url: string | null } | null;
  issued_on: string | null;
  acknowledged_at: string | null;
  photo_url: string | null;
}

export interface EquipmentCategory extends CategoryRef {
  stock: number;
  out: number;
  may_add: boolean;
}

export interface Suggestion {
  key: string;
  name: string;
  kind: CategoryKind;
  icon: string;
}

export interface EquipmentCategories {
  categories: EquipmentCategory[];
  suggestions: Suggestion[];
}

export type Outcome = "held" | "returned" | "lost" | "written_off";

export interface HistoryItem extends HeldItem {
  returned_on: string | null;
  condition_in: Condition | "";
  note_in: string;
  photo_in_url: string | null;
  outcome: Outcome;
}

export interface EquipmentPersonPage {
  today: string;
  holder: Holder;
  history: HistoryItem[];
  can: EquipmentCan;
}

// ─── Writes ──────────────────────────────────────────────────────────────

export interface IssueInput {
  person_id: number;
  asset_ids: number[];
  on?: string | null;
  condition?: Condition | "";
  note?: string;
  photo?: File | null;
}

export interface ReturnInput {
  outcome: "returned" | "lost";
  on?: string | null;
  condition?: Condition | "";
  note?: string;
  photo?: File | null;
  write_off?: boolean;
  deduction?: Money | null;
  reason?: string;
}

export interface DeductionInput {
  amount: Money;
  reason?: string;
}

export interface AddItemsInput {
  category_id: number;
  name: string;
  quantity: number;
  branch_id?: number | null;
  note?: string;
  cost?: Money | null;
  serial?: string;
  model?: string;
}

export interface CategoryInput {
  suggestion?: string;
  name?: string;
  kind?: "low_value" | "fixed";
  icon?: string;
}

export type EquipmentTab = "people" | "items";
export const EQUIPMENT_TABS = ["people", "items"] as const;
export type PersonFlag = "unconfirmed" | "leaving" | "left" | "empty";
