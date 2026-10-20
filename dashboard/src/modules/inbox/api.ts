/**
 * The inbox's endpoints (plan §4.2) as typed functions, and the vue-query helpers the pages use.
 * The pattern every module copies:
 *   - plain functions `(companyId, params) => Promise<T>` over @/api/http (testable with a fetch mock);
 *   - keys from `qk(companyId, "inbox", resource, params)`, so switching company never leaks data and
 *     the pulse (`invalidates` in index.ts) refreshes everything under `[companyId, "inbox"]`;
 *   - mutations that update the cache optimistically and roll back on error.
 * The shell's inbox drawer reads the same endpoints under `[companyId, "shell"]`; the page
 * invalidates both after a change, so the bell, the drawer and the page agree.
 */
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath, request } from "@/api/http";
import { keys as shellKeys, moduleKey, qk } from "@/api/keys";
import type { Page } from "@/api/types";
import { useCompanyStore } from "@/stores/company";

import { queueKey, type Notification, type NotificationParams, type QueueAction, type QueueCounts, type QueueItem, type QueueResponse, type UnreadCount } from "./types";

export const MODULE = "inbox";
export const PAGE_SIZE = 30;

// ─── Endpoints ──────────────────────────────────────────────────────────────

export function listQueue(companyId: number, params: { kind?: string | null } = {}, signal?: AbortSignal): Promise<QueueResponse> {
  return http.get<QueueResponse>(ownerPath(companyId, "queue/"), { kind: params.kind ?? undefined }, { signal });
}

export function queueCounts(companyId: number): Promise<QueueCounts> {
  return http.get<QueueCounts>(ownerPath(companyId, "queue/counts/"));
}

/** Runs a "Needs you" action: `method` on `endpoint` (relative to the company) with `body` + `reason`. */
export function runQueueAction(companyId: number, action: QueueAction, reason?: string): Promise<unknown> {
  return request<unknown>(ownerPath(companyId, action.endpoint), {
    method: action.method,
    json: { ...(action.body ?? {}), ...(reason ? { reason } : {}) },
  });
}

export function listNotifications(companyId: number, params: NotificationParams & { page?: number }, signal?: AbortSignal): Promise<Page<Notification>> {
  return http.get<Page<Notification>>(ownerPath(companyId, "inbox/"), { tab: params.tab, page: params.page ?? 1, page_size: params.page_size ?? PAGE_SIZE }, { signal });
}

export function unreadCount(companyId: number): Promise<UnreadCount> {
  return http.get<UnreadCount>(ownerPath(companyId, "inbox/unread-count/"));
}

export function markRead(companyId: number, ids: number[] | "all"): Promise<void> {
  return http.post<void>(ownerPath(companyId, "inbox/read/"), ids === "all" ? { all: true } : { ids }, { toast: false });
}

export function archiveNotification(companyId: number, id: number): Promise<void> {
  return http.post<void>(ownerPath(companyId, `inbox/${id}/archive/`));
}

export function runNotificationAction(companyId: number, id: number, key: string, reason?: string): Promise<unknown> {
  return http.post<unknown>(ownerPath(companyId, `inbox/${id}/actions/${key}/`), reason ? { reason } : {});
}

// ─── Keys ───────────────────────────────────────────────────────────────────

export const inboxKeys = {
  all: (companyId: number) => moduleKey(companyId, MODULE),
  queue: (companyId: number, kind: string | null) => qk(companyId, MODULE, "queue", kind ? { kind } : {}),
  queueAll: (companyId: number) => [companyId, MODULE, "queue"] as const,
  notifications: (companyId: number, params: NotificationParams) => qk(companyId, MODULE, "notifications", { ...params }),
  notificationsAll: (companyId: number) => [companyId, MODULE, "notifications"] as const,
};

// ─── Queries ────────────────────────────────────────────────────────────────

function useCompanyId() {
  const company = useCompanyStore();
  return computed(() => company.currentId ?? 0);
}

/** "Needs you", optionally one kind. */
export function useQueue(kind: MaybeRefOrGetter<string | null> = null) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => inboxKeys.queue(companyId.value, toValue(kind))),
    queryFn: ({ signal }) => listQueue(companyId.value, { kind: toValue(kind) }, signal),
    enabled: computed(() => companyId.value > 0),
    staleTime: 10_000,
  });
}

/** Notifications, page by page ("Show older"). */
export function useNotifications(params: MaybeRefOrGetter<NotificationParams>) {
  const companyId = useCompanyId();
  return useInfiniteQuery({
    queryKey: computed(() => inboxKeys.notifications(companyId.value, toValue(params))),
    queryFn: ({ pageParam, signal }) => listNotifications(companyId.value, { ...toValue(params), page: pageParam }, signal),
    initialPageParam: 1,
    getNextPageParam: (last, _all, page) => (last.next ? page + 1 : undefined),
    enabled: computed(() => companyId.value > 0),
    staleTime: 10_000,
  });
}

// ─── Mutations ──────────────────────────────────────────────────────────────

type NotificationPages = { pages: Array<Page<Notification>>; pageParams: unknown[] };

/** Everything the inbox page and the shell show about the inbox, refreshed after a change. */
function useRefresh() {
  const client = useQueryClient();
  const companyId = useCompanyId();
  return () => {
    void client.invalidateQueries({ queryKey: inboxKeys.all(companyId.value) });
    void client.invalidateQueries({ queryKey: [companyId.value, "shell"] });
    void client.invalidateQueries({ queryKey: shellKeys.pulse(companyId.value) });
  };
}

/** Decides a queue item; it leaves the list at once and comes back if the server refuses. */
export function useQueueDecision() {
  const client = useQueryClient();
  const companyId = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ action, reason }: { item: QueueItem; action: QueueAction; reason?: string }) => runQueueAction(companyId.value, action, reason),
    onMutate: async ({ item }) => {
      const prefix = inboxKeys.queueAll(companyId.value);
      await client.cancelQueries({ queryKey: prefix });
      const snapshot = client.getQueriesData<QueueResponse>({ queryKey: prefix });
      for (const [key, data] of snapshot) {
        if (!data) continue;
        client.setQueryData<QueueResponse>(key, {
          ...data,
          total: Math.max(0, data.total - 1),
          kinds: data.kinds.map((kind) => (kind.kind === item.kind ? { ...kind, count: Math.max(0, kind.count - 1) } : kind)).filter((kind) => kind.count > 0),
          results: data.results.filter((row) => queueKey(row) !== queueKey(item)),
        });
      }
      return { snapshot };
    },
    onError: (_error, _vars, context) => {
      for (const [key, data] of context?.snapshot ?? []) client.setQueryData(key, data);
    },
    onSettled: refresh,
  });
}

/** Changes notifications in every cached page (read, archive) and returns the snapshot to roll back. */
async function patchNotifications(client: ReturnType<typeof useQueryClient>, companyId: number, patch: (pages: NotificationPages) => NotificationPages) {
  const prefix = inboxKeys.notificationsAll(companyId);
  await client.cancelQueries({ queryKey: prefix });
  const snapshot = client.getQueriesData<NotificationPages>({ queryKey: prefix });
  for (const [key, data] of snapshot) if (data) client.setQueryData<NotificationPages>(key, patch(data));
  return snapshot;
}

export function useMarkRead() {
  const client = useQueryClient();
  const companyId = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (ids: number[] | "all") => markRead(companyId.value, ids),
    onMutate: async (ids) => {
      const now = new Date().toISOString();
      const hit = (note: Notification) => ids === "all" || ids.includes(note.id);
      const snapshot = await patchNotifications(client, companyId.value, (data) => ({
        ...data,
        pages: data.pages.map((page) => ({ ...page, results: page.results.map((note) => (hit(note) && !note.read_at ? { ...note, read_at: now } : note)) })),
      }));
      return { snapshot };
    },
    onError: (_error, _ids, context) => {
      for (const [key, data] of context?.snapshot ?? []) client.setQueryData(key, data);
    },
    onSettled: refresh,
  });
}

export function useArchive() {
  const client = useQueryClient();
  const companyId = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (ids: number[]) => Promise.all(ids.map((id) => archiveNotification(companyId.value, id))),
    onMutate: async (ids) => {
      const snapshot = await patchNotifications(client, companyId.value, (data) => ({
        ...data,
        pages: data.pages.map((page) => ({ ...page, count: Math.max(0, page.count - ids.length), results: page.results.filter((note) => !ids.includes(note.id)) })),
      }));
      return { snapshot };
    },
    onError: (_error, _ids, context) => {
      for (const [key, data] of context?.snapshot ?? []) client.setQueryData(key, data);
    },
    onSettled: refresh,
  });
}

export function useNotificationAction() {
  const companyId = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ note, key, reason }: { note: Notification; key: string; reason?: string }) => runNotificationAction(companyId.value, note.id, key, reason),
    onSettled: refresh,
  });
}
