/**
 * A page's period in the URL (plan §6.5: range lives in the URL): `?preset=month&compare=prev`, or
 * `?preset=custom&from=2026-10-01&to=2026-10-20`. The default is left out of the URL. Presets are
 * re-resolved for today, so a bookmarked "this month" opens on the current month.
 *
 *   const period = useRangeState({ preset: "month", compare: "prev" });
 *   <DateRangePicker v-model="period" />   …   listSummary(cid, rangeParams(period.value))
 */
import { computed, type WritableComputedRef } from "vue";
import { useRoute, useRouter } from "vue-router";

import { customValue, rangeValue, resolveRange, type DateRangeValue } from "@/lib/dateRange";
import { DATE_PRESETS, isDay, type CompareMode, type DatePreset } from "@/lib/dates";
import { patchQuery, type RawQueryValue } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

export interface RangeStateDefault {
  preset: DatePreset;
  compare?: CompareMode;
}

const COMPARE: readonly CompareMode[] = ["none", "prev", "year"];

function first(raw: RawQueryValue): string | undefined {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value ?? undefined;
}

/** Reads a range from query values; anything invalid falls back to the default. */
export function parseRangeQuery(
  query: Record<string, RawQueryValue>,
  fallback: RangeStateDefault,
  tz: string,
  prefix = "",
  now: Date | number = new Date(),
): DateRangeValue {
  const preset = first(query[`${prefix}preset`]);
  const compareText = first(query[`${prefix}compare`]);
  const compare = (COMPARE as readonly string[]).includes(compareText ?? "") ? (compareText as CompareMode) : (fallback.compare ?? "none");
  if (preset === "custom") {
    const from = first(query[`${prefix}from`]);
    const to = first(query[`${prefix}to`]);
    if (from && to && isDay(from) && isDay(to)) return customValue(from <= to ? { from, to } : { from: to, to: from }, compare);
  } else if (preset && (DATE_PRESETS as readonly string[]).includes(preset)) {
    return rangeValue(preset as DatePreset, tz, compare, now);
  }
  return resolveRange(rangeValue(fallback.preset, tz, compare, now), tz, now);
}

/** The query patch for a value: default parts are removed. */
export function rangeQueryPatch(value: DateRangeValue, fallback: RangeStateDefault, prefix = ""): Record<string, string | undefined> {
  const custom = value.preset === "custom";
  return {
    [`${prefix}preset`]: value.preset === fallback.preset ? undefined : value.preset,
    [`${prefix}from`]: custom ? value.range.from : undefined,
    [`${prefix}to`]: custom ? value.range.to : undefined,
    [`${prefix}compare`]: value.compare === (fallback.compare ?? "none") ? undefined : value.compare,
  };
}

export function useRangeState(fallback: RangeStateDefault, options: { prefix?: string } = {}): WritableComputedRef<DateRangeValue> {
  const route = useRoute();
  const router = useRouter();
  const company = useCompanyStore();
  const prefix = options.prefix ?? "";
  return computed({
    get: () => parseRangeQuery(route.query, fallback, company.timezone, prefix),
    set: (value) => patchQuery(router, rangeQueryPatch(value, fallback, prefix)),
  });
}
