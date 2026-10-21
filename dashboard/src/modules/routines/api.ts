/**
 * The routines endpoints (plan §4.5): daily templates and onboarding templates, their "who gets
 * it" preview and compliance. Keys start with `[companyId, "routines"]`; the `tasks.routines`
 * pulse key refreshes them.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import { useCompanyStore } from "@/stores/company";

import type { GivenToday, PlanOptions, Routine, RoutineCompliance, RoutineInput, RoutinePreview } from "./types";

export const MODULE = "routines";
/** The tasks module's cache prefix: routine work given now shows up in its lists too. */
const TASKS = "tasks";

export const routinesApi = {
  list: (cid: number, params: { onboarding?: boolean; q?: string; active?: boolean }, signal?: AbortSignal) =>
    http.get<Routine[]>(ownerPath(cid, "routines/"), { onboarding: params.onboarding ? "true" : undefined, q: params.q || undefined, active: params.active === undefined ? undefined : String(params.active) }, { signal }),
  detail: (cid: number, id: number, signal?: AbortSignal) => http.get<Routine>(ownerPath(cid, `routines/${id}/`), undefined, { signal }),
  create: (cid: number, input: RoutineInput) => http.post<Routine>(ownerPath(cid, "routines/"), input),
  update: (cid: number, id: number, input: RoutineInput) => http.patch<Routine>(ownerPath(cid, `routines/${id}/`), input),
  remove: (cid: number, id: number) => http.delete(ownerPath(cid, `routines/${id}/`)),
  preview: (cid: number, id: number, day: string | null, signal?: AbortSignal) =>
    http.get<RoutinePreview>(ownerPath(cid, `routines/${id}/preview/`), day ? { day } : undefined, { signal }),
  compliance: (cid: number, id: number, range: { from: string; to: string } | null, signal?: AbortSignal) =>
    http.get<RoutineCompliance>(ownerPath(cid, `routines/${id}/compliance/`), range ?? undefined, { signal }),
  options: (cid: number, signal?: AbortSignal) => http.get<PlanOptions>(ownerPath(cid, "tasks/options/"), undefined, { signal }),
  /** "Give today's task now" for a routine made after today's deadline; `dueTime` "HH:MM" today. */
  giveToday: (cid: number, id: number, dueTime: string | null) =>
    http.post<GivenToday>(ownerPath(cid, `routines/${id}/give-today/`), dueTime ? { due_time: dueTime } : {}),
};

export const routineKeys = {
  all: (cid: number) => moduleKey(cid, MODULE),
  list: (cid: number, params: Record<string, unknown>) => qk(cid, MODULE, "list", params),
  detail: (cid: number, id: number) => qk(cid, MODULE, "detail", { id }),
  preview: (cid: number, id: number, day: string | null) => qk(cid, MODULE, "preview", { id, day }),
  compliance: (cid: number, id: number, range: { from: string; to: string } | null) => qk(cid, MODULE, "compliance", { id, ...range }),
  options: (cid: number) => qk(cid, MODULE, "options"),
};

function useCompanyId() {
  const company = useCompanyStore();
  return computed(() => company.currentId ?? 0);
}

export function useRoutines(params: MaybeRefOrGetter<{ onboarding?: boolean; q?: string; active?: boolean }>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => routineKeys.list(cid.value, { ...toValue(params) })),
    queryFn: ({ signal }) => routinesApi.list(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

export function useRoutine(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => routineKeys.detail(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => routinesApi.detail(cid.value, toValue(id)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id)),
    staleTime: 30_000,
  });
}

export function usePreview(id: MaybeRefOrGetter<number | null>, day: MaybeRefOrGetter<string | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => routineKeys.preview(cid.value, toValue(id) ?? 0, toValue(day))),
    queryFn: ({ signal }) => routinesApi.preview(cid.value, toValue(id)!, toValue(day), signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id)),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

export function useCompliance(id: MaybeRefOrGetter<number | null>, range: MaybeRefOrGetter<{ from: string; to: string } | null> = null) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => routineKeys.compliance(cid.value, toValue(id) ?? 0, toValue(range))),
    queryFn: ({ signal }) => routinesApi.compliance(cid.value, toValue(id)!, toValue(range), signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id)),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

export function usePlanOptions() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => routineKeys.options(cid.value)),
    queryFn: ({ signal }) => routinesApi.options(cid.value, signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 5 * 60_000,
  });
}

function useRefresh() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return () => client.invalidateQueries({ queryKey: routineKeys.all(cid.value) });
}

export function useSaveRoutine() {
  const cid = useCompanyId();
  const client = useQueryClient();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ id, input }: { id: number | null; input: RoutineInput }) => (id ? routinesApi.update(cid.value, id, input) : routinesApi.create(cid.value, input)),
    onSuccess: (routine) => client.setQueryData(routineKeys.detail(cid.value, routine.id), routine),
    onSettled: refresh,
  });
}

/** Pause or resume at once in every cached list; back as it was if the server refuses. */
export function useToggleActive() {
  const cid = useCompanyId();
  const client = useQueryClient();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ routine, active }: { routine: Routine; active: boolean }) => routinesApi.update(cid.value, routine.id, { is_active: active }),
    onMutate: async ({ routine, active }) => {
      const prefix = [cid.value, MODULE, "list"] as const;
      await client.cancelQueries({ queryKey: prefix });
      const snapshot = client.getQueriesData<Routine[]>({ queryKey: prefix });
      for (const [key, data] of snapshot) {
        if (data) client.setQueryData(key, data.map((row) => (row.id === routine.id ? { ...row, is_active: active } : row)));
      }
      return { snapshot };
    },
    onError: (_error, _vars, context) => {
      for (const [key, data] of context?.snapshot ?? []) client.setQueryData(key, data);
    },
    onSettled: refresh,
  });
}

/** Today's tasks of a routine given now: routines and every task list refetch. */
export function useGiveToday() {
  const cid = useCompanyId();
  const client = useQueryClient();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ id, dueTime }: { id: number; dueTime: string | null }) => routinesApi.giveToday(cid.value, id, dueTime),
    onSettled: () => Promise.all([refresh(), client.invalidateQueries({ queryKey: moduleKey(cid.value, TASKS) })]),
  });
}

export function useDeleteRoutine() {
  const cid = useCompanyId();
  const refresh = useRefresh();
  return useMutation({ mutationFn: (id: number) => routinesApi.remove(cid.value, id), onSettled: refresh });
}
