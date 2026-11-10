/**
 * Equipment's plain logic, tested on its own: the filters on the people list, the stock by
 * category, an item's confirmation state, what the return dialog may offer (write-off, a
 * deduction), the forms' checks and their payloads, and the category icons.
 */
import { AirVent, AppWindow, Armchair, Box, Building2, Car, Cctv, IdCard, KeyRound, KeySquare, Monitor, Package, PaintRoller, Refrigerator, ScanBarcode, Shirt, Smartphone, Tablet, Thermometer } from "@lucide/vue";
import type { Component } from "vue";

import type { Money } from "@/api/types";
import type { StatusTone } from "@/components/StatusPill.vue";
import { moneySign } from "@/lib/money";

import type { AddItemsInput, Condition, EquipmentCan, EquipmentCategory, HeldItem, Holder, IssueInput, Outcome, PersonFlag, ReturnInput, StockItem } from "./types";

const ICONS: Record<string, Component> = {
  shirt: Shirt,
  "id-card": IdCard,
  "key-round": KeyRound,
  "key-square": KeySquare,
  smartphone: Smartphone,
  tablet: Tablet,
  "scan-barcode": ScanBarcode,
  monitor: Monitor,
  package: Package,
  // The register's own categories (apps.assets defaults), for what was handed out of them.
  car: Car,
  refrigerator: Refrigerator,
  "air-vent": AirVent,
  armchair: Armchair,
  thermometer: Thermometer,
  cctv: Cctv,
  "paint-roller": PaintRoller,
  "building-2": Building2,
  "app-window": AppWindow,
};

/** A category's icon (a lucide name from the API), a box when unknown. */
export const categoryIcon = (name: string | null | undefined): Component => (name && ICONS[name]) || Box;

export const CONDITION_TONES: Record<Condition, StatusTone> = { new: "success", good: "neutral", worn: "warning", damaged: "danger" };
export const OUTCOME_TONES: Record<Outcome, StatusTone> = { held: "primary", returned: "success", lost: "danger", written_off: "neutral" };

// ─── The people list ─────────────────────────────────────────────────────

export interface PeopleFilters {
  q: string;
  category: number | null;
  flags: PersonFlag[];
}

const fold = (text: string) => text.toLocaleLowerCase().replace(/[‘’'`ʻʼ]/g, "");

/** A person's flags: something not confirmed, leaving soon with things, left still holding things, holding nothing. */
export function flagsOf(row: Holder): PersonFlag[] {
  const flags: PersonFlag[] = [];
  if (row.unconfirmed) flags.push("unconfirmed");
  if (row.leaving_soon) flags.push("leaving");
  if (row.overdue) flags.push("left");
  if (!row.items.length) flags.push("empty");
  return flags;
}

/**
 * The rows the filters keep: the name, job title or an item (its name, number or serial) holds the
 * search; the category, when given, is among what they hold; every flag chosen applies. The order:
 * whoever needs something done first (left with things, leaving, not confirmed), then by name.
 */
export function filterPeople(rows: Holder[], filters: PeopleFilters): Holder[] {
  const needle = fold(filters.q.trim());
  const kept = rows.filter((row) => {
    if (filters.category !== null && !row.items.some((item) => item.category.id === filters.category)) return false;
    const flags = flagsOf(row);
    if (filters.flags.some((flag) => !flags.includes(flag))) return false;
    if (!needle) return true;
    const texts = [row.person.name, row.person.position ?? "", ...row.items.flatMap((item) => [item.name, item.number, item.serial])];
    return texts.some((text) => fold(text).includes(needle));
  });
  const weight = (row: Holder) => (row.overdue ? 0 : row.leaving_soon ? 1 : row.unconfirmed ? 2 : row.items.length ? 3 : 4);
  return kept.sort((a, b) => weight(a) - weight(b) || a.person.name.localeCompare(b.person.name));
}

// ─── Stock ───────────────────────────────────────────────────────────────

export interface StockGroup {
  category: StockItem["category"];
  items: StockItem[];
}

/** In-stock things by category, in the categories' order (a category with nothing in stock shows too). */
export function stockByCategory(items: StockItem[], categories: EquipmentCategory[]): StockGroup[] {
  const groups = new Map<number, StockGroup>();
  for (const category of categories) groups.set(category.id, { category, items: [] });
  for (const item of items) {
    const group = groups.get(item.category.id) ?? { category: item.category, items: [] };
    group.items.push(item);
    groups.set(item.category.id, group);
  }
  return [...groups.values()].filter((group) => group.items.length || categories.some((category) => category.id === group.category.id && category.out === 0 && category.kind === "low_value"));
}

/** The number "Xalat №3" carries, for a natural order (№2 before №10). */
export const itemIndex = (name: string): number => Number(/№\s*(\d+)\s*$/.exec(name)?.[1] ?? 0);

export function naturalOrder(a: { name: string; number: string }, b: { name: string; number: string }): number {
  const base = (name: string) => name.replace(/\s*№\s*\d+\s*$/, "");
  return base(a.name).localeCompare(base(b.name)) || itemIndex(a.name) - itemIndex(b.name) || a.number.localeCompare(b.number);
}

// ─── An item ─────────────────────────────────────────────────────────────

/** Confirmed by the person in the app, or still waiting (a warning after three days). */
export function confirmation(item: Pick<HeldItem, "acknowledged_at" | "issued_on">, today: string): { state: "confirmed" | "waiting" | "late"; tone: StatusTone } {
  if (item.acknowledged_at) return { state: "confirmed", tone: "success" };
  const days = Math.round((Date.parse(today) - Date.parse(item.issued_on)) / 86_400_000);
  return days > 3 ? { state: "late", tone: "warning" } : { state: "waiting", tone: "neutral" };
}

/** What the return dialog can do for this person and item. */
export function returnOptions(holder: Pick<Holder, "person">, item: Pick<HeldItem, "may_write_off" | "deduction">, can: Pick<EquipmentCan, "deduct">) {
  const current = holder.person.status === "approved" || holder.person.status === "suspended";
  const open = item.deduction && (item.deduction.status === "proposed" || item.deduction.status === "approved");
  return {
    writeOff: item.may_write_off,
    /** A deduction: payroll on, the person still works here, none already with payroll. */
    deduct: can.deduct && current && !open,
    deductWhy: !can.deduct ? "payroll" : !current ? "left" : open ? "open" : null,
  } as const;
}

// ─── Forms ───────────────────────────────────────────────────────────────

export interface IssueForm {
  person: number | null;
  items: number[];
  on: string;
  condition: Condition;
  note: string;
  photo: File | null;
}

export type IssueErrors = Partial<Record<"person" | "items" | "on", "required" | "future">>;

export function issueErrors(form: IssueForm, today: string): IssueErrors {
  const errors: IssueErrors = {};
  if (!form.person) errors.person = "required";
  if (!form.items.length) errors.items = "required";
  if (!form.on) errors.on = "required";
  else if (form.on > today) errors.on = "future";
  return errors;
}

export function issuePayload(form: IssueForm): IssueInput {
  const payload: IssueInput = { person_id: form.person!, asset_ids: [...form.items], on: form.on, condition: form.condition };
  if (form.note.trim()) payload.note = form.note.trim();
  if (form.photo) payload.photo = form.photo;
  return payload;
}

export interface ReturnForm {
  outcome: "returned" | "lost";
  on: string;
  condition: Condition;
  note: string;
  photo: File | null;
  writeOff: boolean;
  deduct: boolean;
  amount: Money | null;
  reason: string;
}

export type ReturnErrors = Partial<Record<"on" | "amount", "required" | "future" | "amount">>;

export function returnErrors(form: ReturnForm, today: string): ReturnErrors {
  const errors: ReturnErrors = {};
  if (!form.on) errors.on = "required";
  else if (form.on > today) errors.on = "future";
  if (form.deduct && moneySign(form.amount) !== 1) errors.amount = "amount";
  return errors;
}

/** The body of the return: a lost thing has no condition or photo; write-off only for a damaged one. */
export function returnPayload(form: ReturnForm): ReturnInput {
  const payload: ReturnInput = { outcome: form.outcome, on: form.on };
  if (form.note.trim()) payload.note = form.note.trim();
  if (form.outcome === "returned") {
    payload.condition = form.condition;
    if (form.photo) payload.photo = form.photo;
    if (form.condition === "damaged" && form.writeOff) payload.write_off = true;
  }
  if (form.deduct && moneySign(form.amount) === 1) {
    payload.deduction = form.amount;
    if (form.reason.trim()) payload.reason = form.reason.trim();
  }
  return payload;
}

export interface AddForm {
  category: number | null;
  name: string;
  quantity: number | null;
  branch: number | null;
  note: string;
  cost: Money | null;
  serial: string;
  model: string;
}

export type AddErrors = Partial<Record<"category" | "name" | "quantity" | "cost" | "branch", "required" | "range" | "amount">>;

export function addErrors(form: AddForm, device: boolean, needsBranch: boolean): AddErrors {
  const errors: AddErrors = {};
  if (!form.category) errors.category = "required";
  if (!form.name.trim()) errors.name = "required";
  const quantity = form.quantity ?? 0;
  if (!device && (!Number.isInteger(quantity) || quantity < 1 || quantity > 100)) errors.quantity = "range";
  if (device && moneySign(form.cost) !== 1) errors.cost = "amount";
  if (needsBranch && !form.branch) errors.branch = "required";
  return errors;
}

export function addPayload(form: AddForm, device: boolean): AddItemsInput {
  const payload: AddItemsInput = { category_id: form.category!, name: form.name.trim(), quantity: device ? 1 : (form.quantity ?? 1) };
  if (form.branch) payload.branch_id = form.branch;
  if (form.note.trim()) payload.note = form.note.trim();
  if (form.cost && moneySign(form.cost) === 1) payload.cost = form.cost;
  if (device) {
    if (form.serial.trim()) payload.serial = form.serial.trim();
    if (form.model.trim()) payload.model = form.model.trim();
  }
  return payload;
}

/** What "add 10 lab coats" will make: "Xalat №1 … №10" (more than one), else the name itself. */
export function previewNames(name: string, quantity: number | null, startAt = 1): string[] {
  const clean = name.trim();
  if (!clean) return [];
  if (!quantity || quantity <= 1) return [clean];
  return Array.from({ length: quantity }, (_, index) => `${clean} №${startAt + index}`);
}
