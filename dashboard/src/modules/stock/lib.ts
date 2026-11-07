/**
 * Pure helpers of the stock pages: quantities in packs and parts ("3 packs 1 blister"), the tones
 * of statuses, expiry and warnings, and small conversions. No component state here, so the tests
 * call them directly.
 */
import type { StatusTone } from "@/components/StatusPill.vue";

import type { BatchStatus, ControlClass, CountStatus, ReceiptStatus, ReceiptWarning, Storage, TransferStatus, WriteOffStatus } from "./types";

type Translate = (key: string, named?: Record<string, unknown>, plural?: number) => string;

/** A decimal string or number as a number (0 for empty). */
export function num(value: string | number | null | undefined): number {
  if (value === null || value === undefined || value === "") return 0;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

/** A quantity of parts without trailing zeros ("6", "2.5"). */
export function qtyText(value: string | number | null | undefined): string {
  const parsed = num(value);
  return Number.isInteger(parsed) ? String(parsed) : String(Number(parsed.toFixed(3)));
}

/**
 * `quantity` parts as people count them: whole packs and the parts left over ("3 packs 1
 * blister"), or just packs when a pack is one part. A negative quantity (a shortfall) keeps its
 * minus sign in front.
 */
export function packsAndParts(quantity: string | number | null | undefined, unitsPerPack: number, partLabel: string, t: Translate): string {
  const total = num(quantity);
  const sign = total < 0 ? "−" : "";
  const absolute = Math.abs(total);
  const per = Math.max(1, unitsPerPack || 1);
  if (per === 1) return sign + t("stock.qty.packs", { n: qtyText(absolute) }, absolute);
  const packs = Math.floor(absolute / per + 1e-9);
  const rest = Number((absolute - packs * per).toFixed(3));
  const parts = (n: number) => (partLabel ? `${qtyText(n)} ${partLabel}` : t("stock.qty.parts", { n: qtyText(n) }, n));
  if (packs === 0) return sign + parts(rest);
  if (rest === 0) return sign + t("stock.qty.packs", { n: packs }, packs);
  return `${sign}${t("stock.qty.packs", { n: packs }, packs)} ${parts(rest)}`;
}

/** Days from `today` to `day` (both YYYY-MM-DD), negative when past. */
export function daysUntil(day: string, today: string): number {
  const a = Date.UTC(Number(day.slice(0, 4)), Number(day.slice(5, 7)) - 1, Number(day.slice(8, 10)));
  const b = Date.UTC(Number(today.slice(0, 4)), Number(today.slice(5, 7)) - 1, Number(today.slice(8, 10)));
  return Math.round((a - b) / 86_400_000);
}

/** How urgent an expiry date looks: expired danger, within 30 days warning, within 90 info. */
export function expiryTone(day: string | null, today: string): StatusTone {
  if (!day) return "neutral";
  const left = daysUntil(day, today);
  if (left < 0) return "danger";
  if (left <= 30) return "warning";
  if (left <= 90) return "info";
  return "neutral";
}

export const BATCH_TONES: Record<BatchStatus, StatusTone> = { sellable: "success", quarantine: "warning", recalled: "danger" };
export const RECEIPT_TONES: Record<ReceiptStatus, StatusTone> = { draft: "neutral", submitted: "warning", posted: "success", void: "neutral" };
export const TRANSFER_TONES: Record<TransferStatus, StatusTone> = { draft: "neutral", sent: "info", received: "success", disputed: "danger", void: "neutral" };
export const WRITEOFF_TONES: Record<WriteOffStatus, StatusTone> = { proposed: "warning", approved: "info", destroyed: "success", void: "neutral" };
export const COUNT_TONES: Record<CountStatus, StatusTone> = { open: "info", submitted: "warning", applied: "success" };

/** Warnings that block posting (the branch isn't licensed) or need a careful look. */
export const WARNING_TONES: Record<ReceiptWarning, StatusTone> = {
  short_shelf_life: "warning",
  cost_jump: "warning",
  recalled_series: "danger",
  over_price_cap: "warning",
  registration_expired: "danger",
  rx_flag_mismatch: "warning",
  not_official_dealer: "warning",
  over_month_need: "warning",
  not_licensed_branch: "danger",
};

export function isControlled(control: ControlClass): boolean {
  return control !== "none";
}

/** Cold chain: kept in a fridge or a freezer. */
export function isCold(storage: Storage): boolean {
  return storage === "cold" || storage === "frozen";
}

/** The first day of the month before `today` (the month a controlled register closes). */
export function previousMonth(today: string): string {
  const year = Number(today.slice(0, 4));
  const month = Number(today.slice(5, 7));
  const date = new Date(Date.UTC(year, month - 2, 1));
  return date.toISOString().slice(0, 7);
}

/** "2026-11" for a YYYY-MM-DD day. */
export function monthOf(day: string): string {
  return day.slice(0, 7);
}

/** Parts from packs and loose parts typed in a form. */
export function partsOf(packs: number | null, loose: number | null, unitsPerPack: number): number {
  return (packs ?? 0) * Math.max(1, unitsPerPack || 1) + (loose ?? 0);
}
