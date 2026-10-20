/**
 * The time-off endpoints (plan §4.6) as typed functions, and the vue-query helpers. Keys start
 * with `[companyId, "timeoff"]`, so the `timeoff.*` pulse keys refresh everything here.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import type { Page } from "@/api/types";
import { useCompanyStore } from "@/stores/company";

import type { CalendarMonth, Holiday, RecordInput, TimeOffParams, TimeOffRow, TimeOffStats } from "./types";

export const MODULE = "timeoff";

// ─── Endpoints ──────────────────────────────────────────────────────────────

export const listTimeOff = (cid: number, params: TimeOffParams, signal?: AbortSignal) =>
  http.get<Page<TimeOffRow>>(ownerPath(cid, "time-off/"), { ...params }, { signal });

export const getTimeOff = (cid: number, id: number, signal?: AbortSignal) => http.get<TimeOffRow>(ownerPath(cid, `time-off/${id}/`), undefined, { signal });

export const decideTimeOff = (cid: number, id: number, approve: boolean) => http.post<TimeOffRow>(ownerPath(cid, `time-off/${id}/${approve ? "approve" : "reject"}/`));

export function recordTimeOff(cid: number, input: RecordInput): Promise<TimeOffRow> {
  if (input.attachment) {
    const form = new FormData();
    form.append("member_id", String(input.member_id));
    form.append("first_day", input.first_day);
    form.append("last_day", input.last_day);
    form.append("reason", input.reason);
    form.append("attachment", input.attachment);
    return http.form<TimeOffRow>(ownerPath(cid, "time-off/record/"), form);
  }
  const { attachment: _skip, ...body } = input;
  return http.post<TimeOffRow>(ownerPath(cid, "time-off/record/"), body);
}

export const revokeTimeOff = (cid: number, id: number, body: { reason: string; from_day: string | null }) =>
  http.post<TimeOffRow>(ownerPath(cid, `time-off/${id}/revoke/`), body);

export const getCalendar = (cid: number, params: { month: string; branch?: number[]; position?: number[]; everyone?: boolean }, signal?: AbortSignal) =>
  http.get<CalendarMonth>(ownerPath(cid, "time-off/calendar/"), { month: params.month, branch: params.branch, position: params.position, everyone: params.everyone ? "true" : undefined }, { signal });

export const getStats = (cid: number, signal?: AbortSignal) => http.get<TimeOffStats>(ownerPath(cid, "time-off/stats/"), undefined, { signal });

export const listHolidays = (cid: number, year: number | null, signal?: AbortSignal) =>
  http.get<Holiday[]>(ownerPath(cid, "holidays/"), { year: year ?? undefined }, { signal });

export const createHoliday = (cid: number, body: { date: string; name: string }) => http.post<Holiday>(ownerPath(cid, "holidays/"), body);

export const updateHoliday = (cid: number, id: number, body: { date?: string; name?: string }) => http.patch<Holiday>(ownerPath(cid, `holidays/${id}/`), body);

export const deleteHoliday = (cid: number, id: number) => http.delete<void>(ownerPath(cid, `holidays/${id}/`));

export const addPublicHolidays = (cid: number, year: number) => http.post<Holiday[]>(ownerPath(cid, "holidays/public/"), { year });

// ─── Keys and queries ──────────────────────────────────────────────────────

export const timeOffKeys = {
  all: (cid: number) => moduleKey(cid, MODULE),
  list: (cid: number, params: TimeOffParams) => qk(cid, MODULE, "list", { ...params }),
  one: (cid: number, id: number) => qk(cid, MODULE, "one", { id }),
  calendar: (cid: number, params: Record<string, unknown>) => qk(cid, MODULE, "calendar", params),
  stats: (cid: number) => qk(cid, MODULE, "stats"),
  holidays: (cid: number, year: number | null) => qk(cid, MODULE, "holidays", { year }),
};

export function useCompanyId() {
  const company = useCompanyStore();
  return computed(() => company.currentId ?? 0);
}

export function useTimeOffList(params: MaybeRefOrGetter<TimeOffParams>, enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => timeOffKeys.list(cid.value, toValue(params))),
    queryFn: ({ signal }) => listTimeOff(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useTimeOff(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => timeOffKeys.one(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => getTimeOff(cid.value, toValue(id)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id)),
    staleTime: 15_000,
  });
}

export function useCalendar(params: MaybeRefOrGetter<{ month: string; branch?: number[]; position?: number[]; everyone?: boolean }>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => timeOffKeys.calendar(cid.value, { ...toValue(params) })),
    queryFn: ({ signal }) => getCalendar(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useStats() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => timeOffKeys.stats(cid.value)),
    queryFn: ({ signal }) => getStats(cid.value, signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 15_000,
  });
}

export function useHolidays(year: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => timeOffKeys.holidays(cid.value, toValue(year))),
    queryFn: ({ signal }) => listHolidays(cid.value, toValue(year), signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 60_000,
  });
}

// ─── Mutations ─────────────────────────────────────────────────────────────

export function useRefreshTimeOff() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return () => {
    void client.invalidateQueries({ queryKey: timeOffKeys.all(cid.value) });
    void client.invalidateQueries({ queryKey: [cid.value, "people"] });
    void client.invalidateQueries({ queryKey: [cid.value, "shell"] });
    void client.invalidateQueries({ queryKey: [cid.value, "inbox"] });
  };
}

/** Approve or reject: a pending request leaves every cached waiting list at once. */
export function useDecide() {
  const client = useQueryClient();
  const cid = useCompanyId();
  const refresh = useRefreshTimeOff();
  return useMutation({
    mutationFn: ({ id, approve }: { id: number; approve: boolean }) => decideTimeOff(cid.value, id, approve),
    onMutate: async ({ id, approve }) => {
      const prefix = [cid.value, MODULE, "list"];
      await client.cancelQueries({ queryKey: prefix });
      const snapshot = client.getQueriesData<Page<TimeOffRow>>({ queryKey: prefix });
      for (const [key, data] of snapshot) {
        if (!data) continue;
        client.setQueryData<Page<TimeOffRow>>(key, {
          ...data,
          results: data.results.map((row) => (row.id === id ? { ...row, status: approve ? "approved" : "rejected", can_decide: false } : row)),
        });
      }
      return { snapshot };
    },
    onError: (_e, _v, context) => {
      for (const [key, data] of context?.snapshot ?? []) client.setQueryData(key, data);
    },
    onSuccess: (row) => client.setQueryData(timeOffKeys.one(cid.value, row.id), row),
    onSettled: refresh,
  });
}

export function useRecord() {
  const cid = useCompanyId();
  const refresh = useRefreshTimeOff();
  return useMutation({ mutationFn: (input: RecordInput) => recordTimeOff(cid.value, input), onSettled: refresh });
}

export function useRevoke() {
  const client = useQueryClient();
  const cid = useCompanyId();
  const refresh = useRefreshTimeOff();
  return useMutation({
    mutationFn: ({ id, reason, from_day }: { id: number; reason: string; from_day: string | null }) => revokeTimeOff(cid.value, id, { reason, from_day }),
    onSuccess: (row) => client.setQueryData(timeOffKeys.one(cid.value, row.id), row),
    onSettled: refresh,
  });
}

export function useHolidayMutations() {
  const cid = useCompanyId();
  const refresh = useRefreshTimeOff();
  return {
    create: useMutation({ mutationFn: (body: { date: string; name: string }) => createHoliday(cid.value, body), onSettled: refresh }),
    update: useMutation({ mutationFn: ({ id, body }: { id: number; body: { date?: string; name?: string } }) => updateHoliday(cid.value, id, body), onSettled: refresh }),
    remove: useMutation({ mutationFn: (id: number) => deleteHoliday(cid.value, id), onSettled: refresh }),
    addPublic: useMutation({ mutationFn: (year: number) => addPublicHolidays(cid.value, year), onSettled: refresh }),
  };
}
