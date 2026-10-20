import type { Score } from "../api/types";

export type Tone = "good" | "fair" | "poor" | "none";

/** How an on-time rate reads at a glance: 90% and up is good, under 70% needs a word. */
export function tone({ on_time_percent: percent }: Pick<Score, "on_time_percent">): Tone {
  if (percent == null) return "none";
  if (percent >= 90) return "good";
  if (percent >= 70) return "fair";
  return "poor";
}

/** "Ali Valiyev" → "AV", for the avatar circles. */
export function nameInitials(name: string): string {
  const [first = "", last = ""] = name.trim().split(/\s+/);
  return `${first.charAt(0)}${last.charAt(0)}`.toUpperCase() || "?";
}
