/**
 * Reading values as the server reads them (`apps/tasks/readings.py`): "5,2", "5.2", "+5,2 °C" and
 * "−3" (a minus sign) are numbers; anything outside −50 … 100 is a typo. Shown back in the
 * person's style: a decimal comma in Uzbek and Russian, a point in English.
 */
import type { Lang } from "../../i18n";
import type { ReadingSpec, ReadingTaken } from "./api";

export const LOWEST = -50;
export const HIGHEST = 100;

const NUMBER = /^[+-]?(\d+(\.\d*)?|\.\d+)$/;
// What people type after the number: "5,2 °C", "5.2C", "58 %" (Cyrillic с as well).
const UNIT_TAIL = /(°\s*[cс]?|[cс]|%)$/i;

/** The number in what someone typed, or null when it isn't one. */
export function parseValue(raw: string): number | null {
  let text = raw.trim().replace(/−/g, "-").replace(/[\s ]/g, "");
  text = text.replace(UNIT_TAIL, "").replace(",", ".");
  if (!NUMBER.test(text)) return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

export function isPlausible(value: number): boolean {
  return value >= LOWEST && value <= HIGHEST;
}

const bound = (value: string | null): number | null => (value === null || value === "" ? null : Number(value));

export function inRange(value: number, spec: Pick<ReadingSpec, "min" | "max">): boolean {
  const low = bound(spec.min);
  const high = bound(spec.max);
  return (low === null || value >= low) && (high === null || value <= high);
}

/** "5,2" in Uzbek and Russian, "5.2" in English; no trailing zeros ("8", not "8.00"). */
export function formatNumber(value: number | string, lang: Lang): string {
  const number = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(number)) return String(value);
  const text = String(Number(number.toFixed(2))).replace("-", "−");
  return lang === "en" ? text : text.replace(".", ",");
}

/** "2–8 °C", "≤ 60 %", "≥ 15 °C", or "" without a range. */
export function rangeText(spec: Pick<ReadingSpec, "min" | "max" | "unit">, lang: Lang): string {
  const low = bound(spec.min);
  const high = bound(spec.max);
  let text: string;
  if (low !== null && high !== null) text = `${formatNumber(low, lang)}–${formatNumber(high, lang)}`;
  else if (high !== null) text = `≤ ${formatNumber(high, lang)}`;
  else if (low !== null) text = `≥ ${formatNumber(low, lang)}`;
  else return "";
  return `${text} ${spec.unit}`.trim();
}

export function valueText(value: number | string, unit: string, lang: Lang): string {
  return `${formatNumber(value, lang)} ${unit}`.trim();
}

/** What a typed value is: empty, not a number, implausible, or in or out of its range. */
export type Entry =
  | { state: "empty" }
  | { state: "invalid" }
  | { state: "implausible"; value: number }
  | { state: "in" | "out"; value: number };

export function entryOf(raw: string, spec: ReadingSpec): Entry {
  if (!raw.trim()) return { state: "empty" };
  const value = parseValue(raw);
  if (value === null) return { state: "invalid" };
  if (!isPlausible(value)) return { state: "implausible", value };
  return { state: inRange(value, spec) ? "in" : "out", value };
}

/** The latest value of each key (a recheck wins over the first measurement). */
export function latestByKey(taken: readonly ReadingTaken[]): Map<string, ReadingTaken> {
  const latest = new Map<string, ReadingTaken>();
  for (const reading of [...taken].sort((a, b) => a.recorded_at.localeCompare(b.recorded_at) || a.id - b.id)) {
    latest.set(reading.key, reading);
  }
  return latest;
}

/** Keys whose latest value is still out of range: what a recheck is for. */
export function stillOut(taken: readonly ReadingTaken[]): string[] {
  return [...latestByKey(taken).values()].filter((reading) => !reading.in_range).map((reading) => reading.key);
}
