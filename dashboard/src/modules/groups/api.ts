/**
 * Telegram group endpoints (plan §4.4) and vue-query helpers under `[companyId, "groups"]`
 * (`invalidates: ["groups"]` refreshes them when someone else changes a group). Changes move on
 * screen at once and move back if the server refuses.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed } from "vue";

import { http, ownerPath } from "@/api/http";
import { qk } from "@/api/keys";
import { useCompanyStore } from "@/stores/company";

import type { GroupPatch, GroupsList, TelegramGroup } from "./types";

export const MODULE = "groups";

export const listGroups = (cid: number, signal?: AbortSignal) => http.get<GroupsList>(ownerPath(cid, "groups/"), undefined, { signal });
export const updateGroup = (cid: number, id: number, patch: GroupPatch) => http.patch<TelegramGroup>(ownerPath(cid, `groups/${id}/`), patch);
export const disconnectGroup = (cid: number, id: number) => http.post<TelegramGroup>(ownerPath(cid, `groups/${id}/disconnect/`));

export const groupKeys = { list: (cid: number) => qk(cid, MODULE, "list") };

function useCompanyId() {
  const company = useCompanyStore();
  return computed(() => company.currentId ?? 0);
}

export function useGroups() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => groupKeys.list(cid.value)),
    queryFn: ({ signal }) => listGroups(cid.value, signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 30_000,
  });
}

/** Applies a change to the cached list right away (what the server will answer). */
export function applyPatch(group: TelegramGroup, patch: GroupPatch, options: GroupsList["options"]): TelegramGroup {
  const pick = (ids: number[], from: { id: number; name: string }[]) => from.filter((item) => ids.includes(item.id));
  return {
    ...group,
    events: patch.events ? group.events.map((e) => ({ ...e, on: patch.events!.includes(e.key) })) : group.events,
    positions: patch.position_ids ? pick(patch.position_ids, options.positions) : group.positions,
    branches: patch.branch_ids ? pick(patch.branch_ids, options.branches) : group.branches,
  };
}

export function useGroupMutations() {
  const client = useQueryClient();
  const cid = useCompanyId();
  const replace = (row: TelegramGroup) => {
    const data = client.getQueryData<GroupsList>(groupKeys.list(cid.value));
    if (data) client.setQueryData<GroupsList>(groupKeys.list(cid.value), { ...data, results: data.results.map((g) => (g.id === row.id ? row : g)) });
  };
  return {
    update: useMutation({
      mutationFn: ({ id, patch }: { id: number; patch: GroupPatch }) => updateGroup(cid.value, id, patch),
      onMutate: async ({ id, patch }) => {
        const key = groupKeys.list(cid.value);
        await client.cancelQueries({ queryKey: key });
        const before = client.getQueryData<GroupsList>(key);
        if (before) client.setQueryData<GroupsList>(key, { ...before, results: before.results.map((g) => (g.id === id ? applyPatch(g, patch, before.options) : g)) });
        return { before };
      },
      onError: (_e, _v, context) => context?.before && client.setQueryData(groupKeys.list(cid.value), context.before),
      onSuccess: replace,
      onSettled: () => void client.invalidateQueries({ queryKey: [cid.value, "setup"] }),
    }),
    disconnect: useMutation({
      mutationFn: (id: number) => disconnectGroup(cid.value, id),
      onSuccess: (row) => {
        replace(row);
        void client.invalidateQueries({ queryKey: [cid.value, "setup"] });
      },
    }),
  };
}
