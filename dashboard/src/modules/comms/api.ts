/**
 * The announcements endpoints (plan §4.6) as typed functions, and the vue-query helpers. Keys
 * start with `[companyId, "comms"]`; the `announcements.*` pulse key refreshes them.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import type { Page } from "@/api/types";
import { useCompanyStore } from "@/stores/company";

import type { Announcement, AnnouncementParams, AnnouncementStats, AudienceCount, PublishInput, Receipt } from "./types";

export const MODULE = "comms";

// ─── Endpoints ──────────────────────────────────────────────────────────────

export const listAnnouncements = (cid: number, params: AnnouncementParams, signal?: AbortSignal) =>
  http.get<Page<Announcement>>(ownerPath(cid, "announcements/"), { ...params }, { signal });

export const getAnnouncement = (cid: number, id: number, signal?: AbortSignal) => http.get<Announcement>(ownerPath(cid, `announcements/${id}/`), undefined, { signal });

export const publishAnnouncement = (cid: number, body: PublishInput) => http.post<Announcement>(ownerPath(cid, "announcements/"), body);

export const updateAnnouncement = (cid: number, id: number, body: Partial<PublishInput>) => http.patch<Announcement>(ownerPath(cid, `announcements/${id}/`), body);

export const listReceipts = (cid: number, id: number, params: { state?: "read" | "unread"; q?: string; page?: number; page_size?: number }, signal?: AbortSignal) =>
  http.get<Page<Receipt>>(ownerPath(cid, `announcements/${id}/receipts/`), { ...params }, { signal });

export const remindUnread = (cid: number, id: number) => http.post<{ reminded: number }>(ownerPath(cid, `announcements/${id}/remind/`));

export const cancelAnnouncement = (cid: number, id: number) => http.post<Announcement>(ownerPath(cid, `announcements/${id}/cancel/`));

export const pinAnnouncement = (cid: number, id: number, until: string) => http.post<Announcement>(ownerPath(cid, `announcements/${id}/pin/`), { pinned_until: until });

export const unpinAnnouncement = (cid: number, id: number) => http.post<Announcement>(ownerPath(cid, `announcements/${id}/unpin/`));

export const getAudience = (cid: number, params: { position: number[]; branch: number[] }, signal?: AbortSignal) =>
  http.get<AudienceCount>(ownerPath(cid, "announcements/audience/"), { position: params.position, branch: params.branch }, { signal });

export const getStats = (cid: number, signal?: AbortSignal) => http.get<AnnouncementStats>(ownerPath(cid, "announcements/stats/"), undefined, { signal });

// ─── Keys and queries ──────────────────────────────────────────────────────

export const commsKeys = {
  all: (cid: number) => moduleKey(cid, MODULE),
  list: (cid: number, params: AnnouncementParams) => qk(cid, MODULE, "list", { ...params }),
  one: (cid: number, id: number) => qk(cid, MODULE, "one", { id }),
  receipts: (cid: number, id: number, params: Record<string, unknown>) => qk(cid, MODULE, "receipts", { id, ...params }),
  audience: (cid: number, params: Record<string, unknown>) => qk(cid, MODULE, "audience", params),
  stats: (cid: number) => qk(cid, MODULE, "stats"),
};

export function useCompanyId() {
  const company = useCompanyStore();
  return computed(() => company.currentId ?? 0);
}

export function useAnnouncements(params: MaybeRefOrGetter<AnnouncementParams>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => commsKeys.list(cid.value, toValue(params))),
    queryFn: ({ signal }) => listAnnouncements(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useAnnouncement(id: MaybeRefOrGetter<number>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => commsKeys.one(cid.value, toValue(id))),
    queryFn: ({ signal }) => getAnnouncement(cid.value, toValue(id), signal),
    enabled: computed(() => cid.value > 0 && toValue(id) > 0),
    staleTime: 15_000,
  });
}

export function useReceipts(id: MaybeRefOrGetter<number>, params: MaybeRefOrGetter<{ state?: "read" | "unread"; q?: string; page?: number; page_size?: number }>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => commsKeys.receipts(cid.value, toValue(id), { ...toValue(params) })),
    queryFn: ({ signal }) => listReceipts(cid.value, toValue(id), toValue(params), signal),
    enabled: computed(() => cid.value > 0 && toValue(id) > 0),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useAudience(params: MaybeRefOrGetter<{ position: number[]; branch: number[] }>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => commsKeys.audience(cid.value, { ...toValue(params) })),
    queryFn: ({ signal }) => getAudience(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

export function useStats() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => commsKeys.stats(cid.value)),
    queryFn: ({ signal }) => getStats(cid.value, signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 30_000,
  });
}

// ─── Mutations ─────────────────────────────────────────────────────────────

function useRefresh() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return () => {
    void client.invalidateQueries({ queryKey: commsKeys.all(cid.value) });
    void client.invalidateQueries({ queryKey: [cid.value, "shell"] });
  };
}

export function usePublish() {
  const cid = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ id, body }: { id: number | null; body: PublishInput }) => (id === null ? publishAnnouncement(cid.value, body) : updateAnnouncement(cid.value, id, body)),
    onSettled: refresh,
  });
}

/** Remind, cancel, pin and unpin: the fresh announcement goes straight into the cache. */
export function useAnnouncementAction() {
  const client = useQueryClient();
  const cid = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: async (input: { id: number; action: "cancel" | "unpin" } | { id: number; action: "pin"; until: string }): Promise<Announcement> => {
      if (input.action === "pin") return pinAnnouncement(cid.value, input.id, input.until);
      if (input.action === "cancel") return cancelAnnouncement(cid.value, input.id);
      return unpinAnnouncement(cid.value, input.id);
    },
    onSuccess: (row) => client.setQueryData(commsKeys.one(cid.value, row.id), row),
    onSettled: refresh,
  });
}

export function useRemind() {
  const cid = useCompanyId();
  const refresh = useRefresh();
  return useMutation({ mutationFn: (id: number) => remindUnread(cid.value, id), onSettled: refresh });
}
