/**
 * The people endpoints (plan §4.6) as typed functions, and the vue-query helpers the pages use.
 * Keys start with `[companyId, "people"]`, so the `members.*` pulse keys refresh everything here.
 * The pickers in @/components read `people/` and `positions/` under the same module id.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import type { Page, PermissionInfo } from "@/api/types";
import { useCompanyStore } from "@/stores/company";

import type {
  ApproveInput,
  HistoryRecord,
  JoinRequest,
  OffboardInput,
  OffboardPreview,
  PeopleParams,
  Person,
  PersonDetail,
  PersonUpdate,
  PositionRow,
  Role,
  RoleInput,
} from "./types";

export const MODULE = "people";

// ─── Endpoints ──────────────────────────────────────────────────────────────

export const listPeople = (cid: number, params: PeopleParams, signal?: AbortSignal) =>
  http.get<Page<Person>>(ownerPath(cid, "people/"), { ...params }, { signal });

export const getPerson = (cid: number, id: number, signal?: AbortSignal) => http.get<PersonDetail>(ownerPath(cid, `people/${id}/`), undefined, { signal });

export const updatePerson = (cid: number, id: number, body: PersonUpdate) => http.patch<PersonDetail>(ownerPath(cid, `people/${id}/`), body);

export const personAction = (cid: number, id: number, action: "block" | "unblock" | "reinstate") => http.post<PersonDetail>(ownerPath(cid, `people/${id}/${action}/`));

export const suspendPerson = (cid: number, id: number, body: { until: string | null; reason: string }) =>
  http.post<PersonDetail>(ownerPath(cid, `people/${id}/suspend/`), body);

export const getOffboardPreview = (cid: number, id: number, signal?: AbortSignal) =>
  http.get<OffboardPreview>(ownerPath(cid, `people/${id}/offboard-preview/`), undefined, { signal });

export const offboardPerson = (cid: number, id: number, body: OffboardInput) => http.post<PersonDetail>(ownerPath(cid, `people/${id}/offboard/`), body);

export const listHistory = (cid: number, id: number, page: number, signal?: AbortSignal) =>
  http.get<Page<HistoryRecord>>(ownerPath(cid, `people/${id}/history/`), { page, page_size: 30 }, { signal });

export const listJoinRequests = (cid: number, signal?: AbortSignal) => http.get<JoinRequest[]>(ownerPath(cid, "join-requests/"), undefined, { signal });

export const approveRequest = (cid: number, id: number, body: ApproveInput) => http.post<PersonDetail>(ownerPath(cid, `join-requests/${id}/approve/`), body);

export const rejectRequest = (cid: number, id: number, reason: string) => http.post<void>(ownerPath(cid, `join-requests/${id}/reject/`), { reason });

export const listRoles = (cid: number, signal?: AbortSignal) => http.get<Role[]>(ownerPath(cid, "roles/"), undefined, { signal });

export const createRole = (cid: number, body: RoleInput) => http.post<Role>(ownerPath(cid, "roles/"), body);

export const updateRole = (cid: number, id: number, body: RoleInput) => http.patch<Role>(ownerPath(cid, `roles/${id}/`), body);

export const deleteRole = (cid: number, id: number) => http.delete<void>(ownerPath(cid, `roles/${id}/`));

export const listPositions = (cid: number, signal?: AbortSignal) => http.get<PositionRow[]>(ownerPath(cid, "positions/"), undefined, { signal });

export const createPosition = (cid: number, name: string) => http.post<PositionRow>(ownerPath(cid, "positions/"), { name });

export const updatePosition = (cid: number, id: number, body: { name?: string; is_active?: boolean }) =>
  http.patch<PositionRow>(ownerPath(cid, `positions/${id}/`), body);

export const deletePosition = (cid: number, id: number) => http.delete<void>(ownerPath(cid, `positions/${id}/`));

export const reorderPositions = (cid: number, ids: number[]) => http.post<PositionRow[]>(ownerPath(cid, "positions/reorder/"), { ids });

/** The permission registry for the roles matrix (outside the company prefix). */
export const listPermissions = (signal?: AbortSignal) => http.get<PermissionInfo[]>("/owner/permissions/", undefined, { signal });

// ─── Keys and queries ──────────────────────────────────────────────────────

export const peopleKeys = {
  all: (cid: number) => moduleKey(cid, MODULE),
  list: (cid: number, params: PeopleParams) => qk(cid, MODULE, "list", { ...params }),
  person: (cid: number, id: number) => qk(cid, MODULE, "person", { id }),
  history: (cid: number, id: number) => qk(cid, MODULE, "history", { id }),
  offboard: (cid: number, id: number) => qk(cid, MODULE, "offboard", { id }),
  requests: (cid: number) => qk(cid, MODULE, "requests"),
  roles: (cid: number) => qk(cid, MODULE, "roles"),
  positions: (cid: number) => qk(cid, MODULE, "positions"),
};

export function useCompanyId() {
  const company = useCompanyStore();
  return computed(() => company.currentId ?? 0);
}

export function usePeople(params: MaybeRefOrGetter<PeopleParams>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => peopleKeys.list(cid.value, toValue(params))),
    queryFn: ({ signal }) => listPeople(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function usePerson(id: MaybeRefOrGetter<number>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => peopleKeys.person(cid.value, toValue(id))),
    queryFn: ({ signal }) => getPerson(cid.value, toValue(id), signal),
    enabled: computed(() => cid.value > 0 && toValue(id) > 0),
    staleTime: 15_000,
  });
}

export function useJoinRequests() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => peopleKeys.requests(cid.value)),
    queryFn: ({ signal }) => listJoinRequests(cid.value, signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 10_000,
  });
}

export function useRoles(enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => peopleKeys.roles(cid.value)),
    queryFn: ({ signal }) => listRoles(cid.value, signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    staleTime: 60_000,
  });
}

export function usePositions() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => peopleKeys.positions(cid.value)),
    queryFn: ({ signal }) => listPositions(cid.value, signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 60_000,
  });
}

export function usePermissionRegistry() {
  return useQuery({ queryKey: ["permissions"], queryFn: ({ signal }) => listPermissions(signal), staleTime: Infinity });
}

// ─── Mutations ─────────────────────────────────────────────────────────────

/** Everything under `[cid, "people"]` plus the shell's queue and pulse, after a change. */
export function useRefreshPeople() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return () => {
    void client.invalidateQueries({ queryKey: peopleKeys.all(cid.value) });
    void client.invalidateQueries({ queryKey: [cid.value, "shell"] });
    void client.invalidateQueries({ queryKey: [cid.value, "inbox"] });
  };
}

/** A Person 360 change: the answer is the fresh person, written into the cache at once. */
export function usePersonMutation<V>(fn: (cid: number, variables: V) => Promise<PersonDetail>) {
  const client = useQueryClient();
  const cid = useCompanyId();
  const refresh = useRefreshPeople();
  return useMutation({
    mutationFn: (variables: V) => fn(cid.value, variables),
    onSuccess: (person) => client.setQueryData(peopleKeys.person(cid.value, person.id), person),
    onSettled: refresh,
  });
}

/** Approve or reject a join request: it leaves the list at once and comes back on an error. */
export function useDecideRequest() {
  const client = useQueryClient();
  const cid = useCompanyId();
  const refresh = useRefreshPeople();
  return useMutation({
    mutationFn: async (input: { id: number; approve: true; body: ApproveInput } | { id: number; approve: false; reason: string }): Promise<PersonDetail | null> => {
      if (input.approve) return approveRequest(cid.value, input.id, input.body);
      await rejectRequest(cid.value, input.id, input.reason);
      return null;
    },
    onMutate: async (input) => {
      const key = peopleKeys.requests(cid.value);
      await client.cancelQueries({ queryKey: key });
      const previous = client.getQueryData<JoinRequest[]>(key);
      if (previous) client.setQueryData(key, previous.filter((row) => row.id !== input.id));
      return { previous };
    },
    onError: (_error, _input, context) => {
      if (context?.previous) client.setQueryData(peopleKeys.requests(cid.value), context.previous);
    },
    onSettled: refresh,
  });
}

export function useSaveRole() {
  const cid = useCompanyId();
  const refresh = useRefreshPeople();
  return useMutation({
    mutationFn: ({ id, body }: { id: number | null; body: RoleInput }) => (id === null ? createRole(cid.value, body) : updateRole(cid.value, id, body)),
    onSettled: refresh,
  });
}

export function useDeleteRole() {
  const cid = useCompanyId();
  const refresh = useRefreshPeople();
  return useMutation({ mutationFn: (id: number) => deleteRole(cid.value, id), onSettled: refresh });
}

export function usePositionMutations() {
  const client = useQueryClient();
  const cid = useCompanyId();
  const refresh = useRefreshPeople();
  const key = () => peopleKeys.positions(cid.value);
  const create = useMutation({ mutationFn: (name: string) => createPosition(cid.value, name), onSettled: refresh });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: number; body: { name?: string; is_active?: boolean } }) => updatePosition(cid.value, id, body),
    onMutate: async ({ id, body }) => {
      await client.cancelQueries({ queryKey: key() });
      const previous = client.getQueryData<PositionRow[]>(key());
      if (previous) client.setQueryData(key(), previous.map((row) => (row.id === id ? { ...row, ...body } : row)));
      return { previous };
    },
    onError: (_e, _v, context) => context?.previous && client.setQueryData(key(), context.previous),
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: number) => deletePosition(cid.value, id),
    onMutate: async (id) => {
      await client.cancelQueries({ queryKey: key() });
      const previous = client.getQueryData<PositionRow[]>(key());
      if (previous) client.setQueryData(key(), previous.filter((row) => row.id !== id));
      return { previous };
    },
    onError: (_e, _v, context) => context?.previous && client.setQueryData(key(), context.previous),
    onSettled: refresh,
  });
  const reorder = useMutation({
    mutationFn: (ids: number[]) => reorderPositions(cid.value, ids),
    onMutate: async (ids) => {
      await client.cancelQueries({ queryKey: key() });
      const previous = client.getQueryData<PositionRow[]>(key());
      if (previous) {
        const byId = new Map(previous.map((row) => [row.id, row]));
        const ordered = ids.map((id, order) => ({ ...byId.get(id)!, order })).filter((row) => row.id !== undefined);
        client.setQueryData(key(), [...ordered, ...previous.filter((row) => !ids.includes(row.id))]);
      }
      return { previous };
    },
    onError: (_e, _v, context) => context?.previous && client.setQueryData(key(), context.previous),
    onSettled: refresh,
  });
  return { create, update, remove, reorder };
}
