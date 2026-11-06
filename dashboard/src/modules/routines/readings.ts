/**
 * Storage readings (PLAN-OWNER §14.10) as the Routines pages read them: a value with its unit in
 * the reader's language ("5,2 °C" in uz and ru), a spec's allowed range ("2–8 °C", "≤ 60 %"),
 * whether a run's values are still out of range after its rechecks, and the presets the specs
 * editor offers (the company's Settings → Routines ranges).
 */
import type { ReadingSpec, ReadingTaken, RoutinesSettings } from "./types";

/** "5.20" → "5.2" ("5,2" outside English); "" for none. */
export function readingNumber(value: string | number | null | undefined, lang: string): string {
  if (value === null || value === undefined || value === "") return "";
  const number = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(number)) return String(value);
  const text = String(Math.round(number * 100) / 100);
  return lang === "en" ? text : text.replace(".", ",");
}

export function valueText(value: string | number | null | undefined, unit: string, lang: string): string {
  return [readingNumber(value, lang), unit].filter(Boolean).join(" ");
}

/** "2–8 °C", "≤ 60 %", "≥ 15 °C", or "" without bounds. */
export function rangeText(min: string | null | undefined, max: string | null | undefined, unit: string, lang: string): string {
  const low = readingNumber(min, lang);
  const high = readingNumber(max, lang);
  const range = low && high ? `${low}–${high}` : high ? `≤ ${high}` : low ? `≥ ${low}` : "";
  return range ? [range, unit].filter(Boolean).join(" ") : "";
}

export function specRange(spec: Pick<ReadingSpec, "min" | "max" | "unit">, lang: string): string {
  return rangeText(spec.min, spec.max, spec.unit, lang);
}

/** The latest value of each key (a recheck wins over the first measurement). */
export function latestByKey(rows: readonly ReadingTaken[]): Map<string, ReadingTaken> {
  const sorted = [...rows].sort((a, b) => a.recorded_at.localeCompare(b.recorded_at) || a.id - b.id);
  return new Map(sorted.map((row) => [row.key, row]));
}

/** First measurements out of range. */
export function excursions(rows: readonly ReadingTaken[]): ReadingTaken[] {
  return rows.filter((row) => !row.in_range && !row.is_recheck);
}

/** A value is still out of range: the latest of some key is. */
export function stillOut(rows: readonly ReadingTaken[]): boolean {
  return [...latestByKey(rows).values()].some((row) => !row.in_range);
}

/** Back in range after a recheck: the time of the recheck that brought the last key back. */
export function backInRangeAt(rows: readonly ReadingTaken[]): string | null {
  if (!excursions(rows).length || stillOut(rows)) return null;
  const rechecks = rows.filter((row) => row.is_recheck && row.in_range).map((row) => row.recorded_at);
  return rechecks.length ? rechecks.sort().at(-1)! : null;
}

export type SpecDraft = { key?: string; label: string; unit: string; min: number | null; max: number | null; critical: boolean };

export const MAX_SPECS = 3;

/** The quick-add rows of the specs editor, from Settings → Routines. Labels come from the caller. */
export function presetSpecs(settings: RoutinesSettings | undefined, labels: { fridge: string; room: string; humidity: string }): Record<"fridge" | "room" | "humidity", SpecDraft> {
  const number = (value: string | undefined, fallback: number) => (value === undefined || value === "" ? fallback : Number(value));
  return {
    fridge: { label: labels.fridge, unit: "°C", min: number(settings?.storage_fridge_min, 2), max: number(settings?.storage_fridge_max, 8), critical: true },
    room: { label: labels.room, unit: "°C", min: number(settings?.storage_room_min, 15), max: number(settings?.storage_room_max, 25), critical: false },
    humidity: { label: labels.humidity, unit: "%", min: null, max: number(settings?.storage_humidity_max, 60), critical: false },
  };
}

/** A spec as the editor holds it (numbers) from the API's (decimal strings). */
export function toDraft(spec: ReadingSpec): SpecDraft {
  return { key: spec.key, label: spec.label, unit: spec.unit, min: spec.min === null ? null : Number(spec.min), max: spec.max === null ? null : Number(spec.max), critical: spec.critical };
}

/** The editor's specs as the API takes them; `problem` names the first row that isn't ready. */
export function fromDrafts(drafts: readonly SpecDraft[]): { specs: Array<Omit<ReadingSpec, "key"> & { key?: string }>; problem: "label" | "range" | null } {
  for (const draft of drafts) {
    if (!draft.label.trim()) return { specs: [], problem: "label" };
    if (draft.min !== null && draft.max !== null && draft.min > draft.max) return { specs: [], problem: "range" };
  }
  return {
    specs: drafts.map((draft) => ({
      ...(draft.key ? { key: draft.key } : {}),
      label: draft.label.trim(),
      unit: draft.unit.trim(),
      min: draft.min === null ? null : String(draft.min),
      max: draft.max === null ? null : String(draft.max),
      critical: draft.critical,
    })),
    problem: null,
  };
}
