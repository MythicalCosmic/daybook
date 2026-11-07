/**
 * Pure helpers of the stock screens: packs and parts ("3 qadoq 1 blister"), expiry groups,
 * dates as packs print them, barcodes, and which task is the monthly expiry shelf check.
 */
import type { Task } from "../../api/types";
import type { Analog, ControlClass, StockSettings, StorageKind } from "./api";
import type { StockT } from "./text";

/** "7.000" → 7; nothing → 0. */
export function num(value: string | number | null | undefined): number {
  if (value === null || value === undefined || value === "") return 0;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

/** A quantity without trailing zeros: 7, 2.5. */
export function plain(value: number): string {
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(3)));
}

/** Parts as whole packs and the parts left over (a pack of one part is all packs). */
export function splitParts(quantity: string | number | null | undefined, unitsPerPack: number): { packs: number; parts: number; negative: boolean } {
  const total = num(quantity);
  const per = Math.max(1, Math.floor(unitsPerPack || 1));
  const absolute = Math.abs(total);
  if (per === 1) return { packs: absolute, parts: 0, negative: total < 0 };
  const packs = Math.floor(absolute / per + 1e-9);
  return { packs, parts: Number((absolute - packs * per).toFixed(3)), negative: total < 0 };
}

export function partsOf(packs: number, parts: number, unitsPerPack: number): number {
  return packs * Math.max(1, Math.floor(unitsPerPack || 1)) + parts;
}

/**
 * Parts as people count them at the counter: "3 qadoq 1 blister", "2 packs", "1 blister". The
 * part's own name comes from the catalogue ("blister", "ampula"); without one it is "part".
 */
export function qtyText(quantity: string | number | null | undefined, unitsPerPack: number, partLabel: string, t: StockT): string {
  const { packs, parts, negative } = splitParts(quantity, unitsPerPack);
  const packText = (count: number) => t("qty.packs", { count });
  const partText = (count: number) => (partLabel.trim() ? `${plain(count)} ${partLabel.trim()}` : t("qty.parts", { count }));
  const sign = negative ? "−" : "";
  if (packs === 0 && parts === 0) return packText(0);
  if (packs === 0) return sign + partText(parts);
  if (parts === 0) return sign + packText(packs);
  return `${sign}${packText(packs)} ${partText(parts)}`;
}

/** The company's expiry steps, nearest first ([30, 60, 90]); the defaults until the app gets them. */
export function expirySteps(settings: Pick<StockSettings, "expiry_steps"> | undefined): number[] {
  const steps = (settings?.expiry_steps ?? []).filter((step) => Number.isInteger(step) && step > 0 && step <= 365);
  const unique = [...new Set(steps.length ? steps : [90, 60, 30])];
  return unique.sort((a, b) => a - b);
}

export type ExpiryGroup = "expired" | `${number}`;

/** "expired", or the first step a batch falls within ("30" for 0–30 days left), or null beyond the last. */
export function expiryGroup(daysLeft: number, steps: readonly number[]): ExpiryGroup | null {
  if (daysLeft < 0) return "expired";
  for (const step of steps) if (daysLeft <= step) return `${step}`;
  return null;
}

/** "2026-12-31" → "31.12.2026", as the pack prints it. */
export function packDate(day: string | null | undefined): string {
  if (!day || !/^\d{4}-\d{2}-\d{2}/.test(day)) return "";
  return `${day.slice(8, 10)}.${day.slice(5, 7)}.${day.slice(0, 4)}`;
}

/** The last day of a month: an expiry printed "12.2026" may be sold through 31.12.2026. */
export function lastDayOfMonth(year: number, month: number): string {
  const day = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** A pack's main barcode (EAN-13) with a correct check digit. */
export function isEan13(code: string): boolean {
  if (!/^\d{13}$/.test(code)) return false;
  const digits = [...code].map(Number);
  const sum = digits.slice(0, 12).reduce((total, digit, index) => total + digit * (index % 2 ? 3 : 1), 0);
  return (10 - (sum % 10)) % 10 === digits[12];
}

/** What a scanner or a typed barcode looks like: EAN-8, UPC-A, EAN-13 or a GTIN-14. */
export function looksLikeBarcode(text: string): boolean {
  return /^(\d{8}|\d{12,14})$/.test(text.trim());
}

/** Kept in a fridge or a freezer. */
export function isCold(storage: StorageKind): boolean {
  return storage === "cold" || storage === "frozen";
}

export function isControlled(control: ControlClass): boolean {
  return control !== "none";
}

/** Analogs I have come first, then by name: the list is a catalogue fact, never advice. */
export function sortAnalogs(rows: readonly Analog[]): Analog[] {
  return [...rows].sort((a, b) => Number(num(b.quantity) > 0) - Number(num(a.quantity) > 0) || a.name.localeCompare(b.name));
}

/**
 * The monthly "Expiry shelf check: <pharmacy>" task the stock module gives each pharmacy
 * (apps/inventory/scan.py `shelf_checks`), in the company's language: the system gives it, so no
 * one created it. Matched by its title until the task carries a link of its own.
 */
export const SHELF_CHECK_TITLES = ["Expiry shelf check", "Yaroqlilik muddatini tekshirish", "Проверка сроков годности"] as const;

export function isShelfCheckTask(task: Pick<Task, "title" | "created_by">): boolean {
  if (task.created_by) return false;
  const title = task.title.trim().toLocaleLowerCase();
  return SHELF_CHECK_TITLES.some((prefix) => title.startsWith(prefix.toLocaleLowerCase()));
}

/** A typed customer phone kept for the call-back: digits and a leading +, at most 16 characters. */
export function cleanPhone(raw: string): string {
  const trimmed = raw.trim();
  const digits = trimmed.replace(/\D/g, "");
  return (trimmed.startsWith("+") ? `+${digits}` : digits).slice(0, 16);
}

/** A decimal string the API takes for a count of packs or parts ("3", "2.5"). */
export function decimalText(value: number): string {
  return plain(Math.max(0, value));
}
