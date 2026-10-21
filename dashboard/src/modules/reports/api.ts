/**
 * Team reports (plan §4.5): team KPIs over a range with a comparison and a grouping, and routine
 * compliance. The period goes as a preset when it is one (so "this month" compares with the same
 * days of last month, as the server's calendar rules say), otherwise as from/to.
 */
import { keepPreviousData, useQuery } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath } from "@/api/http";
import { qk } from "@/api/keys";
import type { DateRangeValue } from "@/lib/dateRange";
import { useCompanyStore } from "@/stores/company";

import type { GroupBy, RoutineReport, TeamReport } from "./types";

export const MODULE = "reports";

type Params = Record<string, string | string[] | undefined>;

/** API params for a period: `{preset, compare}` or `{from, to, compare}`. */
export function periodParams(value: DateRangeValue): Params {
  const params: Params = value.preset === "custom" ? { from: value.range.from, to: value.range.to } : { preset: value.preset };
  if (value.compare !== "none") params.compare = value.compare;
  return params;
}

export const reportsApi = {
  team: (cid: number, params: Params, signal?: AbortSignal) => http.get<TeamReport>(ownerPath(cid, "reports/team/"), params, { signal }),
  routines: (cid: number, params: Params, signal?: AbortSignal) => http.get<RoutineReport>(ownerPath(cid, "reports/routines/"), params, { signal }),
};

function useCompanyId() {
  const company = useCompanyStore();
  return computed(() => company.currentId ?? 0);
}

export function useTeamReport(period: MaybeRefOrGetter<DateRangeValue>, groupBy: MaybeRefOrGetter<GroupBy>, branches: MaybeRefOrGetter<string[]> = []) {
  const cid = useCompanyId();
  const params = computed<Params>(() => ({ ...periodParams(toValue(period)), group_by: toValue(groupBy), branch: toValue(branches).length ? toValue(branches) : undefined }));
  return useQuery({
    queryKey: computed(() => qk(cid.value, MODULE, "team", params.value)),
    queryFn: ({ signal }) => reportsApi.team(cid.value, params.value, signal),
    enabled: computed(() => cid.value > 0),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

export function useRoutineReport(period: MaybeRefOrGetter<DateRangeValue>, branches: MaybeRefOrGetter<string[]> = []) {
  const cid = useCompanyId();
  const params = computed<Params>(() => ({ ...periodParams(toValue(period)), branch: toValue(branches).length ? toValue(branches) : undefined }));
  return useQuery({
    queryKey: computed(() => qk(cid.value, MODULE, "routines", params.value)),
    queryFn: ({ signal }) => reportsApi.routines(cid.value, params.value, signal),
    enabled: computed(() => cid.value > 0),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}
