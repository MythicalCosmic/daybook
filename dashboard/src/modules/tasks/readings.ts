/**
 * Storage readings as the task drawer and the Overview card show them (PLAN-OWNER §14.10): an
 * allowed range ("2–8 °C", "≤ 60 %"), a value with its unit in the reader's style ("5,2 °C" in
 * Uzbek and Russian), and a task's values grouped by what was measured.
 */
import type { ReadingSpec, ReadingTaken } from "./types";

/** `useFormat().number`: decimal strings in, "5,2" / "5.2" out, trailing zeros dropped. */
export type NumberFormat = (value: string | number | null | undefined, decimals?: number) => string;

const has = (value: string | null | undefined): value is string => value !== null && value !== undefined && value !== "";

/** "2–8 °C", "≤ 60 %", "≥ 15 °C"; "" when there is no bound. */
export function rangeText(min: string | null | undefined, max: string | null | undefined, unit: string, number: NumberFormat): string {
  let text: string;
  if (has(min) && has(max)) text = `${number(min, 2)}–${number(max, 2)}`;
  else if (has(max)) text = `≤ ${number(max, 2)}`;
  else if (has(min)) text = `≥ ${number(min, 2)}`;
  else return "";
  return unit ? `${text} ${unit}` : text;
}

/** "5,2 °C". */
export function valueText(value: string, unit: string, number: NumberFormat): string {
  const text = number(value, 2);
  return unit ? `${text} ${unit}` : text;
}

export interface ReadingGroup {
  key: string;
  label: string;
  unit: string;
  min: string | null;
  max: string | null;
  critical: boolean;
  /** Oldest first: the first measurement, then any rechecks. */
  values: ReadingTaken[];
  /** The latest value is out of range (no recheck brought it back yet). */
  open: boolean;
}

const time = (reading: ReadingTaken) => new Date(reading.recorded_at).getTime();

/**
 * A task's readings by what was measured: its specs in their order (then any key only the values
 * know), each with its values oldest first.
 */
export function readingGroups(specs: readonly ReadingSpec[] = [], taken: readonly ReadingTaken[] = []): ReadingGroup[] {
  const groups = new Map<string, ReadingGroup>();
  for (const spec of specs) groups.set(spec.key, { ...spec, values: [], open: false });
  for (const reading of [...taken].sort((a, b) => time(a) - time(b) || a.id - b.id)) {
    let group = groups.get(reading.key);
    if (!group) {
      group = { key: reading.key, label: reading.label, unit: reading.unit, min: reading.min, max: reading.max, critical: false, values: [], open: false };
      groups.set(reading.key, group);
    }
    group.values.push(reading);
  }
  for (const group of groups.values()) group.open = group.values.length > 0 && !group.values[group.values.length - 1]!.in_range;
  return [...groups.values()];
}
