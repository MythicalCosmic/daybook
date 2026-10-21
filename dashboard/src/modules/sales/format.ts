/**
 * Small display rules the sales pages share: tones for shift and movement states, icons for
 * payment-method and movement kinds, and the difference tone against the cash tolerance.
 * Money stays a decimal string; comparisons go through `@/lib/decimal`.
 */
import {
  ArrowDownToLine,
  ArrowLeftRight,
  ArrowUpFromLine,
  Banknote,
  CreditCard,
  HandCoins,
  Landmark,
  PiggyBank,
  QrCode,
  Receipt,
  Repeat,
  Vault,
  Wallet,
} from "@lucide/vue";
import type { Component } from "vue";

import type { Money } from "@/api/types";
import type { StatusTone } from "@/components/StatusPill.vue";
import { compare, dec } from "@/lib/decimal";

import type { MethodKind, MovementKind, MovementStatus, ShiftStatus } from "./types";

export const SHIFT_TONES: Record<ShiftStatus, StatusTone> = {
  open: "info",
  closed: "warning",
  verified: "success",
  disputed: "danger",
};

export const MOVEMENT_TONES: Record<MovementStatus, StatusTone> = {
  pending: "warning",
  declined: "danger",
  done: "success",
  void: "neutral",
};

export const METHOD_ICONS: Record<MethodKind, Component> = {
  cash: Banknote,
  card: CreditCard,
  qr: QrCode,
  transfer: Landmark,
  credit: HandCoins,
  installment: Repeat,
  other: Wallet,
};

export const MOVEMENT_ICONS: Record<MovementKind, Component> = {
  payout: Receipt,
  deposit: ArrowDownToLine,
  handover: HandCoins,
  to_safe: Vault,
  from_safe: PiggyBank,
  to_bank: Landmark,
};

export const MOVEMENT_KINDS: MovementKind[] = ["payout", "handover", "to_safe", "from_safe", "to_bank", "deposit"];

/** Cash coming into the till (+) or leaving it (−). */
export function movementSign(kind: MovementKind): 1 | -1 {
  return kind === "deposit" || kind === "from_safe" ? 1 : -1;
}

export const TRANSFER_ICON = ArrowLeftRight;
export const OUT_ICON = ArrowUpFromLine;

/** How a cash difference reads: none, within tolerance, short or over. */
export type DifferenceLevel = "none" | "ok" | "short" | "over" | "unknown";

export function differenceLevel(difference: Money | null | undefined, tolerance: Money | null | undefined): DifferenceLevel {
  if (difference === null || difference === undefined) return "unknown";
  const value = dec(difference);
  if (value.isZero()) return "none";
  if (tolerance !== null && tolerance !== undefined && compare(value.abs().toFixed(2), tolerance) <= 0) return "ok";
  return value.isNegative() ? "short" : "over";
}

export const DIFFERENCE_TONES: Record<DifferenceLevel, StatusTone> = {
  none: "success",
  ok: "success",
  short: "danger",
  over: "warning",
  unknown: "neutral",
};

/** Text color class for a difference cell. */
export function differenceClass(level: DifferenceLevel): string {
  return { none: "text-success", ok: "text-muted", short: "text-danger", over: "text-warning", unknown: "text-subtle" }[level];
}

/** Banknote rows of a count, largest first: [["200000", 3], …]. */
export function countRows(count: Record<string, number> | null | undefined): Array<[string, number]> {
  return Object.entries(count ?? {})
    .filter(([, pieces]) => pieces > 0)
    .sort((a, b) => Number(b[0]) - Number(a[0]));
}
