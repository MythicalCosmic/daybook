/**
 * Filter definitions and values for FilterBar, and their round trip through the URL (plan §6.5:
 * filters live in the URL). Query keys are the API's own parameter names, so the same object
 * serves the address bar and the request: `?status=open&status=late&assignee=12&due_from=2026-10-01`.
 */
import type { Component } from "vue";
import { computed, toValue, type MaybeRefOrGetter } from "vue";
import { useRoute, useRouter, type LocationQuery } from "vue-router";

import type { Range } from "@/api/types";
import { patchQuery, type SerializedValue } from "@/lib/useRouteState";

import type { OptionSource, SelectOption } from "./options";

export type FilterType = "select" | "multi" | "boolean" | "date-range" | "text" | "number-range";

export interface FilterDef {
  /** Query key (select, multi, boolean, text). Ranges use `params`. */
  key: string;
  /** Already translated. */
  label: string;
  type: FilterType;
  icon?: Component;
  options?: SelectOption<string>[];
  source?: OptionSource<string>;
  /** Query keys of a range; default `${key}_from` and `${key}_to` (use ["from", "to"] for the page period). */
  params?: [string, string];
  /** Always shown as a chip, even when empty. */
  pinned?: boolean;
  placeholder?: string;
  /** Labels for boolean values, default Yes / No. */
  trueLabel?: string;
  falseLabel?: string;
}

export interface RangeValue {
  from: string | null;
  to: string | null;
}

export type FilterValue = string | string[] | boolean | RangeValue | null;
export type FilterValues = Record<string, FilterValue>;

export function rangeKeys(def: FilterDef): [string, string] {
  return def.params ?? [`${def.key}_from`, `${def.key}_to`];
}

export function isEmptyValue(value: FilterValue | undefined): boolean {
  if (value === null || value === undefined || value === "") return true;
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === "object") return !value.from && !value.to;
  return false;
}

function firstOf(raw: LocationQuery[string]): string | undefined {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value ?? undefined;
}

function listOf(raw: LocationQuery[string]): string[] {
  if (raw === undefined || raw === null) return [];
  return (Array.isArray(raw) ? raw : [raw]).flatMap((v) => (v ?? "").split(",")).filter(Boolean);
}

/** Reads filter values from a route query. */
export function fromQuery(defs: readonly FilterDef[], query: LocationQuery): FilterValues {
  const values: FilterValues = {};
  for (const def of defs) {
    switch (def.type) {
      case "multi":
        values[def.key] = listOf(query[def.key]);
        break;
      case "boolean": {
        const text = firstOf(query[def.key]);
        values[def.key] = text === "true" || text === "1" ? true : text === "false" || text === "0" ? false : null;
        break;
      }
      case "date-range":
      case "number-range": {
        const [fromKey, toKey] = rangeKeys(def);
        const from = firstOf(query[fromKey]) ?? null;
        const to = firstOf(query[toKey]) ?? null;
        values[def.key] = from || to ? { from, to } : null;
        break;
      }
      default:
        values[def.key] = firstOf(query[def.key]) ?? null;
    }
  }
  return values;
}

/** Query entries for filter values; empty filters remove their keys. */
export function toQuery(defs: readonly FilterDef[], values: FilterValues): Record<string, SerializedValue> {
  const out: Record<string, SerializedValue> = {};
  for (const def of defs) {
    const value = values[def.key] ?? null;
    if (def.type === "date-range" || def.type === "number-range") {
      const [fromKey, toKey] = rangeKeys(def);
      const range = value && typeof value === "object" && !Array.isArray(value) ? value : null;
      out[fromKey] = range?.from || undefined;
      out[toKey] = range?.to || undefined;
      continue;
    }
    if (isEmptyValue(value)) out[def.key] = undefined;
    else if (Array.isArray(value)) out[def.key] = [...value];
    else if (typeof value === "boolean") out[def.key] = value ? "true" : "false";
    else out[def.key] = String(value);
  }
  return out;
}

/** The same as `toQuery` without the removed keys: ready for `http.get(path, params)`. */
export function toParams(defs: readonly FilterDef[], values: FilterValues): Record<string, string | string[]> {
  const params: Record<string, string | string[]> = {};
  for (const [key, value] of Object.entries(toQuery(defs, values))) if (value !== undefined) params[key] = value;
  return params;
}

export function activeCount(defs: readonly FilterDef[], values: FilterValues): number {
  return defs.filter((def) => !isEmptyValue(values[def.key])).length;
}

export interface SummaryContext {
  yes: string;
  no: string;
  day: (day: string) => string;
  range: (range: Range) => string;
  number: (value: string) => string;
  more: (n: number) => string;
}

/** What a chip says about its value: "Open, Late", "Open +2", "1–20 Oct", "Yes", "≥ 100 000". */
export function summarize(def: FilterDef, value: FilterValue, ctx: SummaryContext, maxItems = 2): string {
  if (isEmptyValue(value)) return "";
  const label = (v: string) => def.options?.find((option) => option.value === v)?.label ?? v;
  if (Array.isArray(value)) {
    const shown = value.slice(0, maxItems).map(label).join(", ");
    return value.length > maxItems ? `${shown} ${ctx.more(value.length - maxItems)}` : shown;
  }
  if (typeof value === "boolean") return value ? (def.trueLabel ?? ctx.yes) : (def.falseLabel ?? ctx.no);
  if (value && typeof value === "object") {
    const { from, to } = value;
    if (def.type === "date-range") {
      if (from && to) return ctx.range({ from, to });
      return from ? `≥ ${ctx.day(from)}` : `≤ ${ctx.day(to!)}`;
    }
    if (from && to) return `${ctx.number(from)} – ${ctx.number(to)}`;
    return from ? `≥ ${ctx.number(from)}` : `≤ ${ctx.number(to!)}`;
  }
  return def.type === "select" ? label(String(value)) : String(value);
}

/**
 * Filter values bound to the URL: `const filters = useUrlFilters(defs)`; `filters.values` is a
 * writable computed for FilterBar's v-model, `filters.params` goes to the API, `filters.clear()`
 * removes them all in one navigation.
 */
export function useUrlFilters(defs: MaybeRefOrGetter<readonly FilterDef[]>) {
  const route = useRoute();
  const router = useRouter();
  const values = computed<FilterValues>({
    get: () => fromQuery(toValue(defs), route.query),
    set: (next) => patchQuery(router, toQuery(toValue(defs), next)),
  });
  return {
    values,
    params: computed(() => toParams(toValue(defs), values.value)),
    active: computed(() => activeCount(toValue(defs), values.value)),
    clear: () => patchQuery(router, toQuery(toValue(defs), {})),
  };
}
