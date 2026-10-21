import type { Card, Health } from "./api";

/** "1:05" for 65 minutes. */
export function hhmm(minutes: number): string {
  const total = Math.max(0, Math.round(minutes));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** Elapsed time of a running timer, "0:42" or "1:05:09" past an hour with seconds. */
export function elapsed(startedAt: string, now: number): string {
  const seconds = Math.max(0, Math.floor((now - new Date(startedAt).getTime()) / 1000));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}

/** The CSS class giving a project's colour (palette key "chart-3") to `--prj`. */
export function colorClass(color: string | null | undefined): string {
  return /^chart-[1-8]$/.test(color ?? "") ? `prj-${color}` : "prj-chart-1";
}

export function healthTone(health: Health | null): "accent" | "sage" | "neutral" {
  if (health === "on_track") return "sage";
  if (health === "at_risk" || health === "off_track") return "accent";
  return "neutral";
}

/** A position between the cards a card is dropped between (floats, like the dashboard). */
export function positionBetween(before: Card | undefined, after: Card | undefined): number {
  if (!before && !after) return 1024;
  if (!before) return after!.position - 1024;
  if (!after) return before.position + 1024;
  return (before.position + after.position) / 2;
}

/** Where a card lands at the end of a list. */
export function endOf(cards: readonly Card[], listId: number): number {
  const positions = cards.filter((card) => card.list_id === listId).map((card) => card.position);
  return positions.length ? Math.max(...positions) + 1024 : 1024;
}
