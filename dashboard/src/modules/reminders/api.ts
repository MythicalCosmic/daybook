/**
 * The reminders endpoints (plan §4.5): policies with texts per step, the reminder log and the
 * people who blocked the bot. Keys start with `[companyId, "reminders"]`; the
 * `reminders.policies` pulse key refreshes them.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import { useCompanyStore } from "@/stores/company";

import type { BlockedPerson, LogPage, Policy, PolicyInput } from "./types";

export const MODULE = "reminders";

type Params = Record<string, string | number | boolean | string[] | undefined | null>;

export const remindersApi = {
  policies: (cid: number, signal?: AbortSignal) => http.get<Policy[]>(ownerPath(cid, "reminder-policies/"), undefined, { signal }),
  create: (cid: number, input: PolicyInput) => http.post<Policy>(ownerPath(cid, "reminder-policies/"), input),
  update: (cid: number, id: number, input: PolicyInput) => http.patch<Policy>(ownerPath(cid, `reminder-policies/${id}/`), input),
  remove: (cid: number, id: number) => http.delete(ownerPath(cid, `reminder-policies/${id}/`)),
  makeDefault: (cid: number, id: number) => http.post<Policy>(ownerPath(cid, `reminder-policies/${id}/make-default/`)),
  log: (cid: number, params: Params, signal?: AbortSignal) => http.get<LogPage>(ownerPath(cid, "reminder-log/"), params, { signal }),
  blocked: (cid: number, signal?: AbortSignal) => http.get<BlockedPerson[]>(ownerPath(cid, "blocked-bot/"), undefined, { signal }),
};

export const reminderKeys = {
  all: (cid: number) => moduleKey(cid, MODULE),
  policies: (cid: number) => qk(cid, MODULE, "policies"),
  log: (cid: number, params: Params) => qk(cid, MODULE, "log", params),
  blocked: (cid: number) => qk(cid, MODULE, "blocked"),
};

function useCompanyId() {
  const company = useCompanyStore();
  return computed(() => company.currentId ?? 0);
}

export function usePolicies() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => reminderKeys.policies(cid.value)),
    queryFn: ({ signal }) => remindersApi.policies(cid.value, signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 60_000,
  });
}

export function useReminderLog(params: MaybeRefOrGetter<Params>, enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => reminderKeys.log(cid.value, toValue(params))),
    queryFn: ({ signal }) => remindersApi.log(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useBlocked(enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => reminderKeys.blocked(cid.value)),
    queryFn: ({ signal }) => remindersApi.blocked(cid.value, signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    staleTime: 60_000,
  });
}

function useRefresh() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return () => client.invalidateQueries({ queryKey: reminderKeys.all(cid.value) });
}

export function useSavePolicy() {
  const cid = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ id, input }: { id: number | null; input: PolicyInput }) => (id ? remindersApi.update(cid.value, id, input) : remindersApi.create(cid.value, input)),
    onSettled: refresh,
  });
}

/** Moves the "Default" badge at once; back where it was if the server refuses. */
export function useMakeDefault() {
  const cid = useCompanyId();
  const client = useQueryClient();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (id: number) => remindersApi.makeDefault(cid.value, id),
    onMutate: async (id) => {
      const key = reminderKeys.policies(cid.value);
      await client.cancelQueries({ queryKey: key });
      const previous = client.getQueryData<Policy[]>(key);
      if (previous) client.setQueryData(key, previous.map((policy) => ({ ...policy, is_default: policy.id === id })));
      return { previous };
    },
    onError: (_error, _id, context) => context?.previous && client.setQueryData(reminderKeys.policies(cid.value), context.previous),
    onSettled: refresh,
  });
}

export function useDeletePolicy() {
  const cid = useCompanyId();
  const refresh = useRefresh();
  return useMutation({ mutationFn: (id: number) => remindersApi.remove(cid.value, id), onSettled: refresh });
}
