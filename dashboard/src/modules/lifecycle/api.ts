/**
 * The lifecycle endpoints (plan §13.4, prefix `lifecycle/`) as typed functions, and the vue-query
 * helpers. Keys start with `[companyId, "lifecycle"]`, so the `lifecycle` pulse version refreshes
 * everything here; a suspension also refreshes the people pages (the person's status changes).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath, type Query } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import type { Money, Page } from "@/api/types";
import { useCompanyId } from "@/stores/company";

import type { DisciplinaryRecord, RecordInput, RecordParams, SuspendInput, Suspension } from "./types";

export const MODULE = "lifecycle";

const path = (cid: number, rest: string) => ownerPath(cid, `lifecycle/${rest}`);

/** JSON, or a form when the evidence file goes with it. */
function recordBody(input: RecordInput): FormData | Omit<RecordInput, "evidence"> {
  const { evidence, ...rest } = input;
  if (!evidence) return rest;
  const form = new FormData();
  for (const [key, value] of Object.entries(rest)) if (value !== undefined && value !== null) form.append(key, String(value));
  form.append("evidence", evidence);
  return form;
}

export const lifecycleApi = {
  records: (cid: number, params: RecordParams, signal?: AbortSignal) => http.get<Page<DisciplinaryRecord>>(path(cid, "discipline/"), params as Query, { signal }),
  record: (cid: number, id: number, signal?: AbortSignal) => http.get<DisciplinaryRecord>(path(cid, `discipline/${id}/`), undefined, { signal }),
  createRecord: (cid: number, input: RecordInput) => {
    const body = recordBody(input);
    return body instanceof FormData ? http.form<DisciplinaryRecord>(path(cid, "discipline/"), body) : http.post<DisciplinaryRecord>(path(cid, "discipline/"), body);
  },
  withdrawRecord: (cid: number, id: number, reason: string) => http.post<DisciplinaryRecord>(path(cid, `discipline/${id}/withdraw/`), { reason }),
  /** Propose a fine for a record that has none yet (payroll approves it). */
  proposeFine: (cid: number, id: number, amount: Money) => http.post<DisciplinaryRecord>(path(cid, `discipline/${id}/fine/`), { amount }),

  /** Who is suspended now (not paginated: a handful at most). */
  suspensions: (cid: number, signal?: AbortSignal) => http.get<Suspension[]>(path(cid, "suspensions/"), undefined, { signal }),
  suspend: (cid: number, input: SuspendInput) => http.post<Suspension>(path(cid, "suspensions/"), input),
  /** Reinstate someone suspended (by their member id). */
  reinstate: (cid: number, memberId: number) => http.post<void>(path(cid, `suspensions/${memberId}/reinstate/`)),
};

// ─── Keys and queries ──────────────────────────────────────────────────────

export const lifecycleKeys = {
  all: (cid: number) => moduleKey(cid, MODULE),
  records: (cid: number, params: RecordParams) => qk(cid, MODULE, "records", { ...params }),
  record: (cid: number, id: number) => qk(cid, MODULE, "record", { id }),
  suspensions: (cid: number) => qk(cid, MODULE, "suspensions"),
};

export function useRecords(params: MaybeRefOrGetter<RecordParams>, enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => lifecycleKeys.records(cid.value, toValue(params))),
    queryFn: ({ signal }) => lifecycleApi.records(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useRecord(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => lifecycleKeys.record(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => lifecycleApi.record(cid.value, toValue(id)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id)),
    staleTime: 15_000,
  });
}

export function useSuspensions(enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => lifecycleKeys.suspensions(cid.value)),
    queryFn: ({ signal }) => lifecycleApi.suspensions(cid.value, signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    staleTime: 15_000,
  });
}

// ─── Mutations ─────────────────────────────────────────────────────────────

/** Lifecycle, the people pages (status, Person 360), payroll (a proposed fine) and the shell's pulse. */
export function useRefresh() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return () => {
    void client.invalidateQueries({ queryKey: lifecycleKeys.all(cid.value) });
    void client.invalidateQueries({ queryKey: [cid.value, "people"] });
    void client.invalidateQueries({ queryKey: [cid.value, "payroll"] });
    void client.invalidateQueries({ queryKey: [cid.value, "shell"] });
  };
}

export function useLifecycleMutation<I, O>(run: (cid: number, input: I) => Promise<O>) {
  const cid = useCompanyId();
  const refresh = useRefresh();
  return useMutation({ mutationFn: (input: I) => run(cid.value, input), onSettled: refresh });
}
