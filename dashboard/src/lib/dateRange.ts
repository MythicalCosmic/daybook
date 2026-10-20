/**
 * The value of DateRangePicker and of every page's range filter: a preset (or "custom"), the days it
 * covers in the company's timezone, and a comparison mode. Presets are relative ("this month"), so
 * `resolveRange` recomputes their days for today; a custom range stays as picked.
 */
import type { Range } from "@/api/types";
import { compareRange, presetRange, type CompareMode, type DatePreset } from "@/lib/dates";

export type RangePreset = DatePreset | "custom";

export interface DateRangeValue {
  preset: RangePreset;
  range: Range;
  compare: CompareMode;
}

export function rangeValue(preset: DatePreset, tz: string, compare: CompareMode = "none", now: Date | number = new Date()): DateRangeValue {
  return { preset, range: presetRange(preset, tz, now), compare };
}

export function customValue(range: Range, compare: CompareMode = "none"): DateRangeValue {
  return { preset: "custom", range: { ...range }, compare };
}

/** The same value with a preset's days brought up to date (a link saved last month opens on this month). */
export function resolveRange(value: DateRangeValue, tz: string, now: Date | number = new Date()): DateRangeValue {
  if (value.preset === "custom") return value;
  return { ...value, range: presetRange(value.preset, tz, now) };
}

/** The comparison period of a value, or null when comparison is off. */
export function compareOf(value: DateRangeValue): Range | null {
  return compareRange(value.range, value.compare, value.preset === "custom" ? undefined : value.preset);
}

/**
 * Query parameters for an analytics endpoint (plan §4: `?from&to&compare`): the days, and the
 * comparison mode (`prev` or `year`) when it is on. The server derives the compare days itself
 * with the same rule as `compareOf`.
 */
export function rangeParams(value: DateRangeValue): Record<string, string> {
  const params: Record<string, string> = { from: value.range.from, to: value.range.to };
  if (value.compare !== "none") params.compare = value.compare;
  return params;
}

export function sameValue(a: DateRangeValue, b: DateRangeValue): boolean {
  return a.preset === b.preset && a.compare === b.compare && a.range.from === b.range.from && a.range.to === b.range.to;
}
