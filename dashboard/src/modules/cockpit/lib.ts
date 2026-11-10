/** The cockpit's small rules, apart from the components so they are tested on their own. */
import type { StatusTone } from "@/components/StatusPill.vue";
import { changePercent, compare, dec } from "@/lib/decimal";

import type { BranchState, CockpitBranch, CockpitCash, CockpitDecisions, InsightSeverity, PeriodFigures, PeriodKey } from "./api";

/** Branches by profit in the period, the biggest earner first; ties keep their order. */
export function rankBranches(branches: readonly CockpitBranch[], period: PeriodKey): CockpitBranch[] {
  return [...branches].sort((a, b) => compare(b[period].profit, a[period].profit));
}

export const STATE_TONE: Record<BranchState, StatusTone> = { green: "success", amber: "warning", red: "danger" };
export const SEVERITY_TONE: Record<InsightSeverity, StatusTone> = { critical: "danger", warning: "warning", info: "info" };

/**
 * Profit's change against the period it is compared with, in percent; null when there was no
 * profit to compare with, or it turned into a loss (a "−392 %" says nothing the red figure doesn't).
 */
export function profitChange(figures: PeriodFigures): number | null {
  const before = figures.previous?.profit;
  if (before === undefined || before === null || compare(before, 0) <= 0 || compare(figures.profit, 0) < 0) return null;
  return changePercent(figures.profit, before);
}

/** The margin's change in percentage points ("−7,8 pp"), or null. */
export function marginPoints(figures: PeriodFigures): number | null {
  const now = figures.margin;
  const before = figures.previous?.margin;
  if (now === null || before === null || before === undefined) return null;
  return Math.round((Number(now) - Number(before)) * 10) / 10;
}

/** The biggest costs of a period, the rest summed as "other" when there are more than `limit`. */
export function topCosts(figures: PeriodFigures, limit = 3): Array<{ key: string; name: string; amount: string; share: number }> {
  const costs = figures.costs.filter((cost) => compare(cost.amount, 0) > 0);
  const total = costs.reduce((sum, cost) => sum.plus(dec(cost.amount)), dec(0));
  const share = (amount: string) => (total.isZero() ? 0 : dec(amount).div(total).times(100).toNumber());
  const shown = costs.slice(0, limit).map((cost) => ({ key: cost.key, name: cost.name, amount: cost.amount, share: share(cost.amount) }));
  if (costs.length > limit) {
    const rest = costs.slice(limit).reduce((sum, cost) => sum.plus(dec(cost.amount)), dec(0));
    shown.push({ key: "_other", name: "", amount: rest.toFixed(2), share: share(rest.toFixed(2)) });
  }
  return shown;
}

/** Which sentence describes the low point: short of money, under the buffer, or fine. */
export function lowKind(cash: CockpitCash): "short" | "under" | "fine" {
  if (compare(cash.low.short_by, 0) > 0) return "short";
  if (compare(cash.low.under_buffer_by, 0) > 0) return "under";
  return "fine";
}

/** The decision groups with something waiting, biggest count first, each with its sources' keys. */
export function decisionGroups(decisions: CockpitDecisions): Array<{ group: string; count: number; sources: string[] }> {
  const groups = new Map<string, { group: string; count: number; sources: string[] }>();
  for (const source of decisions.sources) {
    if (source.count <= 0) continue;
    const entry = groups.get(source.group) ?? { group: source.group, count: 0, sources: [] };
    entry.count += source.count;
    entry.sources.push(source.key);
    groups.set(source.group, entry);
  }
  return [...groups.values()].sort((a, b) => b.count - a.count);
}

/** The month of a "2026-10" key as a day the date formatter takes. */
export function monthDay(key: string): string {
  return `${key.slice(0, 7)}-01`;
}

/** A queue item's link inside the company, from the relative or absolute path its app gave. */
export { companyUrl } from "@/lib/links";
