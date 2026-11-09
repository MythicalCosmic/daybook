/**
 * Pure helpers of the Reports page: the downloaded file's name, tones for rates, the two ends of
 * the punctuality ranking and client-side sorting (every row of a report is on the page).
 */
import type { RankingRow, TrendDay } from "./types";

/**
 * The file name a download response carries (`filename*=UTF-8''…` first, then `filename="…"`), or
 * `fallback`. Path separators never survive: the name is only ever a name.
 */
export function reportFileName(header: string | null | undefined, fallback: string): string {
  if (!header) return fallback;
  const encoded = /filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/.exec(header);
  let name: string | null = null;
  if (encoded) {
    try {
      name = decodeURIComponent(encoded[1]!.trim().replace(/^"|"$/g, ""));
    } catch {
      name = null;
    }
  }
  if (!name) {
    const plain = /filename\s*=\s*("([^"]*)"|[^;]+)/.exec(header);
    name = plain ? (plain[2] ?? plain[1] ?? "").trim() : null;
  }
  const clean = (name ?? "").replace(/[\\/]+/g, "-").trim();
  return clean || fallback;
}

export type RateTone = "success" | "warning" | "danger" | "neutral";

/** 90 % and up reads well, 75 % and up needs a look, below that needs attention. */
export function rateTone(value: number | null | undefined): RateTone {
  if (value === null || value === undefined) return "neutral";
  if (value >= 90) return "success";
  if (value >= 75) return "warning";
  return "danger";
}

export const TONE_TEXT: Record<RateTone, string> = {
  neutral: "text-muted",
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
};

/**
 * The ranking's two ends. Needs attention: the least punctual of those late at least once, worst
 * first. Most punctual: the top of the ranking without them. Nobody is in both, so a small team's
 * late people show once, on the right side.
 */
export function rankingEnds(rows: readonly RankingRow[], size = 5): { best: RankingRow[]; worst: RankingRow[] } {
  const worst = rows
    .filter((row) => row.late_count > 0)
    .slice(-size)
    .reverse();
  const flagged = new Set(worst.map((row) => row.employee.id));
  const best = rows.filter((row) => !flagged.has(row.employee.id)).slice(0, size);
  return { best, worst };
}

/** People who came on time that day: everyone who came, less those who were late. */
export function onTime(day: TrendDay): number {
  return Math.max(0, day.present - day.late);
}

/**
 * Rows sorted by a DRF-style ordering ("-days_absent"); `valueOf` gives a row's value for a field
 * (names compare as lower-case text, missing numbers sort last whichever the direction).
 */
export function sortRows<Row>(rows: readonly Row[], ordering: string, valueOf: (row: Row, field: string) => string | number | null): Row[] {
  const field = ordering.replace(/^-/, "");
  const direction = ordering.startsWith("-") ? -1 : 1;
  return [...rows].sort((a, b) => {
    const left = valueOf(a, field);
    const right = valueOf(b, field);
    if (left === null && right === null) return 0;
    if (left === null) return 1;
    if (right === null) return -1;
    if (typeof left === "string" || typeof right === "string") return String(left).localeCompare(String(right)) * direction;
    return (left - right) * direction;
  });
}
