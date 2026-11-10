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

import type {
  Career,
  ChangeCounts,
  ChangeInput,
  ChangeParams,
  CurrentJob,
  DisciplinaryRecord,
  JobChange,
  LeaveAgreeInput,
  LeaveStartInput,
  LeaveUpdateInput,
  Leaving,
  LeavingCounts,
  LeavingParams,
  LeavingRow,
  RecordInput,
  RecordParams,
  SuspendInput,
  Suspension,
} from "./types";

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

  // Leaving
  leavings: (cid: number, params: LeavingParams, signal?: AbortSignal) => http.get<Page<LeavingRow>>(path(cid, "terminations/"), params as Query, { signal }),
  leavingCounts: (cid: number, signal?: AbortSignal) => http.get<LeavingCounts>(path(cid, "terminations/counts/"), undefined, { signal }),
  leaving: (cid: number, id: number, signal?: AbortSignal) => http.get<Leaving>(path(cid, `terminations/${id}/`), undefined, { signal }),
  startLeaving: (cid: number, input: LeaveStartInput) => http.post<Leaving>(path(cid, "terminations/"), input),
  updateLeaving: (cid: number, id: number, input: LeaveUpdateInput) => http.patch<Leaving>(path(cid, `terminations/${id}/`), input),
  /** Agree the last day (the one asked for unless another is given), or move an agreed one. */
  agreeLeaving: (cid: number, id: number, input: LeaveAgreeInput) => http.post<Leaving>(path(cid, `terminations/${id}/agree/`), input),
  declineLeaving: (cid: number, id: number, reason: string) => http.post<Leaving>(path(cid, `terminations/${id}/decline/`), { reason }),
  withdrawLeaving: (cid: number, id: number, reason: string) => http.post<Leaving>(path(cid, `terminations/${id}/withdraw/`), { reason }),
  /** "Try again" after the evening job couldn't complete it. */
  retryLeaving: (cid: number, id: number) => http.post<Leaving>(path(cid, `terminations/${id}/retry/`)),
  addHandoverItem: (cid: number, id: number, input: { title: string; kind?: "keys" | "documents" | "other" }) => http.post<Leaving>(path(cid, `terminations/${id}/handover/`), input),
  setHandoverItem: (cid: number, id: number, itemId: number, input: { done?: boolean; note?: string }) => http.patch<Leaving>(path(cid, `terminations/${id}/handover/${itemId}/`), input),
  removeHandoverItem: (cid: number, id: number, itemId: number) => http.delete<Leaving>(path(cid, `terminations/${id}/handover/${itemId}/`)),

  // Job changes
  changes: (cid: number, params: ChangeParams, signal?: AbortSignal) => http.get<Page<JobChange>>(path(cid, "job-changes/"), params as Query, { signal }),
  changeCounts: (cid: number, signal?: AbortSignal) => http.get<ChangeCounts>(path(cid, "job-changes/counts/"), undefined, { signal }),
  change: (cid: number, id: number, signal?: AbortSignal) => http.get<JobChange>(path(cid, `job-changes/${id}/`), undefined, { signal }),
  currentJob: (cid: number, memberId: number, signal?: AbortSignal) => http.get<CurrentJob>(path(cid, "job-changes/current/"), { member: memberId }, { signal }),
  proposeChange: (cid: number, input: ChangeInput) => http.post<JobChange>(path(cid, "job-changes/"), input),
  approveChange: (cid: number, id: number) => http.post<JobChange>(path(cid, `job-changes/${id}/approve/`)),
  rejectChange: (cid: number, id: number, reason: string) => http.post<JobChange>(path(cid, `job-changes/${id}/reject/`), { reason }),
  cancelChange: (cid: number, id: number, reason = "") => http.post<JobChange>(path(cid, `job-changes/${id}/cancel/`), { reason }),
  retryChange: (cid: number, id: number) => http.post<JobChange>(path(cid, `job-changes/${id}/retry/`)),
  career: (cid: number, memberId: number, signal?: AbortSignal) => http.get<Career>(path(cid, `people/${memberId}/career/`), undefined, { signal }),
};

// ─── Keys and queries ──────────────────────────────────────────────────────

export const lifecycleKeys = {
  all: (cid: number) => moduleKey(cid, MODULE),
  records: (cid: number, params: RecordParams) => qk(cid, MODULE, "records", { ...params }),
  record: (cid: number, id: number) => qk(cid, MODULE, "record", { id }),
  suspensions: (cid: number) => qk(cid, MODULE, "suspensions"),
  leavings: (cid: number, params: LeavingParams) => qk(cid, MODULE, "leavings", { ...params }),
  leavingCounts: (cid: number) => qk(cid, MODULE, "leaving-counts"),
  leaving: (cid: number, id: number) => qk(cid, MODULE, "leaving", { id }),
  changes: (cid: number, params: ChangeParams) => qk(cid, MODULE, "changes", { ...params }),
  changeCounts: (cid: number) => qk(cid, MODULE, "change-counts"),
  change: (cid: number, id: number) => qk(cid, MODULE, "change", { id }),
  currentJob: (cid: number, memberId: number) => qk(cid, MODULE, "current-job", { memberId }),
  career: (cid: number, memberId: number) => qk(cid, MODULE, "career", { memberId }),
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

export function useLeavings(params: MaybeRefOrGetter<LeavingParams>, enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => lifecycleKeys.leavings(cid.value, toValue(params))),
    queryFn: ({ signal }) => lifecycleApi.leavings(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useLeavingCounts(enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => lifecycleKeys.leavingCounts(cid.value)),
    queryFn: ({ signal }) => lifecycleApi.leavingCounts(cid.value, signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    staleTime: 15_000,
  });
}

export function useLeaving(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => lifecycleKeys.leaving(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => lifecycleApi.leaving(cid.value, toValue(id)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id)),
    staleTime: 15_000,
  });
}

export function useChanges(params: MaybeRefOrGetter<ChangeParams>, enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => lifecycleKeys.changes(cid.value, toValue(params))),
    queryFn: ({ signal }) => lifecycleApi.changes(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useChangeCounts(enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => lifecycleKeys.changeCounts(cid.value)),
    queryFn: ({ signal }) => lifecycleApi.changeCounts(cid.value, signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    staleTime: 15_000,
  });
}

export function useChange(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => lifecycleKeys.change(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => lifecycleApi.change(cid.value, toValue(id)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id)),
    staleTime: 15_000,
  });
}

export function useCurrentJob(memberId: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => lifecycleKeys.currentJob(cid.value, toValue(memberId) ?? 0)),
    queryFn: ({ signal }) => lifecycleApi.currentJob(cid.value, toValue(memberId)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(memberId)),
    staleTime: 10_000,
  });
}

export function useCareer(memberId: MaybeRefOrGetter<number>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => lifecycleKeys.career(cid.value, toValue(memberId))),
    queryFn: ({ signal }) => lifecycleApi.career(cid.value, toValue(memberId), signal),
    enabled: computed(() => cid.value > 0 && toValue(memberId) > 0),
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
