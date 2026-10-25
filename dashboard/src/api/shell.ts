/** Endpoints the shell itself calls (plan §4.2, §4.3). Modules call their own in modules/<id>/api.ts. */
import { http, ownerPath, request } from "@/api/http";
import type {
  AccessResponse,
  Language,
  Me,
  Notification,
  NotificationActionResult,
  Page,
  Pulse,
  QueueAction,
  QueueCounts,
  QueueItemsResponse,
  QueueView,
  SearchResponse,
  UnreadCount,
} from "@/api/types";

/**
 * "Needs you" as one value: `queue/counts/` (total and a label per kind) and `queue/` (the items,
 * oldest first) fetched together. Used by the shell's drawer and the inbox module alike.
 */
export async function fetchQueue(companyId: number, kind?: string | null, signal?: AbortSignal): Promise<QueueView> {
  const [counts, list] = await Promise.all([
    http.get<QueueCounts>(ownerPath(companyId, "queue/counts/"), undefined, { signal }),
    http.get<QueueItemsResponse>(ownerPath(companyId, "queue/"), { kind: kind ?? undefined }, { signal }),
  ]);
  return { total: counts.total, kinds: counts.kinds, items: list.items };
}

/** Runs a "Needs you" action: `method` on `endpoint` (relative to the company) with `body` plus `reason`. */
export function runQueueAction(companyId: number, action: QueueAction, reason?: string): Promise<unknown> {
  return request<unknown>(ownerPath(companyId, action.endpoint), {
    method: action.method,
    json: { ...action.body, ...(reason ? { reason } : {}) },
  });
}

/** The queue without one decided item (optimistic update). */
export function withoutQueueItem(view: QueueView, item: { kind: string; id: number | string }): QueueView {
  const items = view.items.filter((row) => !(row.kind === item.kind && String(row.id) === String(item.id)));
  if (items.length === view.items.length) return view;
  return {
    total: Math.max(0, view.total - 1),
    kinds: view.kinds.map((kind) => (kind.kind === item.kind ? { ...kind, count: Math.max(0, kind.count - 1) } : kind)),
    items,
  };
}

export const shellApi = {
  me: () => http.get<Me>("/owner/me/"),
  setLanguage: (language: Language) => http.patch<Me>("/owner/me/", { language }, { toast: false }),
  /** One company everywhere: the bot follows a company picked in the switcher (and says so). */
  setBotCompany: (companyId: number) => http.patch<Me>("/owner/me/", { bot_company: companyId }, { toast: false }),

  devLogin: (telegramId: number) =>
    request<AccessResponse>("/owner/auth/dev-login/", { method: "POST", json: { telegram_id: telegramId }, anonymous: true }),
  telegramLogin: (initData: string) =>
    request<AccessResponse>("/owner/auth/telegram/", { method: "POST", json: { init_data: initData }, anonymous: true, toast: false }),
  logout: () => request<void>("/owner/auth/logout/", { method: "POST", json: {}, anonymous: true, toast: false }),

  pulse: (companyId: number, signal?: AbortSignal) => http.get<Pulse>(ownerPath(companyId, "pulse/"), undefined, { signal }),
  search: (companyId: number, q: string, signal?: AbortSignal) =>
    http.get<SearchResponse>(ownerPath(companyId, "search/"), { q }, { signal }),
  queue: (companyId: number, kind?: string | null, signal?: AbortSignal) => fetchQueue(companyId, kind, signal),
  runQueueAction,

  inbox: (companyId: number, tab: "unread" | "all", page = 1, signal?: AbortSignal) =>
    http.get<Page<Notification>>(ownerPath(companyId, "inbox/"), { tab, page, page_size: 30 }, { signal }),
  unreadCount: (companyId: number, signal?: AbortSignal) => http.get<UnreadCount>(ownerPath(companyId, "inbox/unread-count/"), undefined, { signal }),
  markRead: (companyId: number, ids: number[] | "all") =>
    http.post<{ updated: number }>(ownerPath(companyId, "inbox/read/"), ids === "all" ? { all: true } : { ids }, { toast: false }),
  archive: (companyId: number, id: number) => http.post<Notification>(ownerPath(companyId, `inbox/${id}/archive/`)),
  runInboxAction: (companyId: number, id: number, key: string, reason?: string) =>
    http.post<NotificationActionResult>(ownerPath(companyId, `inbox/${id}/actions/${key}/`), reason ? { reason } : {}),
};
