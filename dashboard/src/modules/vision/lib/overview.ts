/**
 * The overview's numbers as the page shows them (docs/KOZ.md §6.1): which hours to draw, the
 * comparison of each headline number, and why a number is missing. Every value may be null: no
 * entrance camera (no visitors), the sales module off (no receipts), more receipts than visitors
 * (no conversion), attendance off (no one checked in).
 */
import type { HourRow, Overview, Severity, Totals } from "../types";

function empty(row: HourRow): boolean {
  return !row.visitors && !row.receipts && !row.queue_max && !row.wait_max_s && !row.staff_avg && !row.staff_checked_in && !row.unattended_minutes;
}

/** The 24 hours without the empty ones before opening and after closing (gaps inside stay). */
export function trimHours(hours: readonly HourRow[]): HourRow[] {
  const sorted = [...hours].sort((a, b) => a.hour - b.hour);
  let first = 0;
  let last = sorted.length - 1;
  while (first <= last && empty(sorted[first]!)) first++;
  while (last >= first && empty(sorted[last]!)) last--;
  return sorted.slice(first, last + 1);
}

/** "18:00". */
export function hourLabel(hour: number): string {
  return `${String(hour).padStart(2, "0")}:00`;
}

/** "18:00–19:00". */
export function hourRange(hour: number): string {
  return `${hourLabel(hour)}–${hourLabel((hour + 1) % 24)}`;
}

/** A change in percent, or null when there is nothing to compare with. */
export function percentChange(now: number | null | undefined, before: number | null | undefined): number | null {
  if (now === null || now === undefined || before === null || before === undefined || before === 0) return null;
  return ((now - before) / before) * 100;
}

/** Conversion as a percentage (64.8), or null. */
export function conversionPercent(conversion: number | null | undefined): number | null {
  if (conversion === null || conversion === undefined || !Number.isFinite(conversion)) return null;
  return conversion * 100;
}

/** The change of conversion in percentage points (+2.1), or null. */
export function conversionPoints(totals: Totals): number | null {
  const now = totals.conversion;
  const before = totals.compare?.conversion;
  if (now === null || before === null || before === undefined) return null;
  return (now - before) * 100;
}

/** People who left without buying on the comparison day, from its visitors and receipts. */
export function comparedLeft(totals: Totals): number | null {
  const compare = totals.compare;
  if (!compare || compare.visitors === null || compare.receipts === null) return null;
  return Math.max(compare.visitors - compare.receipts, 0);
}

export type MissingReason = "no_entrance" | "no_sales" | "undercount" | "no_visitors" | "no_counter";

/** Why a headline number is empty, so the tile can say it instead of a bare dash. */
export function missingReason(field: "visitors" | "receipts" | "conversion" | "left" | "wait", overview: Pick<Overview, "totals" | "setup">): MissingReason | null {
  const { totals, setup } = overview;
  switch (field) {
    case "visitors":
      return totals.visitors === null ? "no_entrance" : null;
    case "receipts":
      return totals.receipts === null ? "no_sales" : null;
    case "conversion":
      if (totals.conversion !== null) return null;
      if (totals.conversion_note === "entrance_undercount") return "undercount";
      if (totals.visitors === null || !setup.entrance) return "no_entrance";
      if (totals.receipts === null) return "no_sales";
      return "no_visitors";
    case "left":
      if (totals.left !== null) return null;
      return totals.visitors === null ? "no_entrance" : "no_sales";
    case "wait":
      return totals.wait_max_s === null && !setup.counter ? "no_counter" : null;
  }
}

/** The busiest hour by visitors (ties: the earlier), or null on a day without any. */
export function peakHour(hours: readonly HourRow[]): HourRow | null {
  let best: HourRow | null = null;
  for (const row of hours) if ((row.visitors ?? 0) > 0 && (!best || (row.visitors ?? 0) > (best.visitors ?? 0))) best = row;
  return best;
}

/** The heat of an hour's longest wait against the queue rule: 0 calm … 4 far past it. */
export function waitHeat(seconds: number | null | undefined, threshold: number): 0 | 1 | 2 | 3 | 4 {
  if (!seconds || seconds <= 0 || !threshold) return 0;
  const ratio = seconds / threshold;
  if (ratio < 0.35) return 0;
  if (ratio < 0.7) return 1;
  if (ratio < 1) return 2;
  if (ratio < 1.6) return 3;
  return 4;
}

/** Insights in the order the page lists them: what hurts first, then good news. */
const SEVERITY_ORDER: Record<Severity, number> = { bad: 0, warn: 1, info: 2, good: 3 };

export function bySeverity<T extends { severity: Severity }>(items: readonly T[]): T[] {
  return items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => (SEVERITY_ORDER[a.item.severity] ?? 9) - (SEVERITY_ORDER[b.item.severity] ?? 9) || a.index - b.index)
    .map(({ item }) => item);
}

/** A day with no boxes at all: the page sells Ko‘z and leads to pairing instead of zeros. */
export function needsSetup(overview: Pick<Overview, "setup"> | null | undefined): boolean {
  return !!overview && overview.setup.agents === 0;
}
