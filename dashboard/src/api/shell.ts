/** Endpoints the shell itself calls (plan §4.2, §4.3). Modules call their own in modules/<id>/api.ts. */
import { http, ownerPath, request } from "@/api/http";
import type {
  AccessResponse,
  Language,
  Me,
  Notification,
  Page,
  Pulse,
  QueueAction,
  QueueResponse,
  SearchResponse,
  UnreadCount,
} from "@/api/types";

export const shellApi = {
  me: () => http.get<Me>("/owner/me/"),
  setLanguage: (language: Language) => http.patch<Me>("/owner/me/", { language }, { toast: false }),

  devLogin: (telegramId: number) =>
    request<AccessResponse>("/owner/auth/dev-login/", { method: "POST", json: { telegram_id: telegramId }, anonymous: true }),
  telegramLogin: (initData: string) =>
    request<AccessResponse>("/owner/auth/telegram/", { method: "POST", json: { init_data: initData }, anonymous: true, toast: false }),
  logout: () => request<void>("/owner/auth/logout/", { method: "POST", json: {}, anonymous: true, toast: false }),

  pulse: (companyId: number, signal?: AbortSignal) => http.get<Pulse>(ownerPath(companyId, "pulse/"), undefined, { signal }),
  search: (companyId: number, q: string, signal?: AbortSignal) =>
    http.get<SearchResponse>(ownerPath(companyId, "search/"), { q }, { signal }),
  queue: (companyId: number, kind?: string) => http.get<QueueResponse>(ownerPath(companyId, "queue/"), { kind }),
  runQueueAction: (companyId: number, action: QueueAction, reason?: string) =>
    request<unknown>(ownerPath(companyId, action.endpoint), {
      method: action.method,
      json: { ...(action.body ?? {}), ...(reason ? { reason } : {}) },
    }),

  inbox: (companyId: number, tab: "unread" | "all", page = 1) =>
    http.get<Page<Notification>>(ownerPath(companyId, "inbox/"), { tab, page }),
  unreadCount: (companyId: number) => http.get<UnreadCount>(ownerPath(companyId, "inbox/unread-count/")),
  markRead: (companyId: number, ids: number[] | "all") =>
    http.post<void>(ownerPath(companyId, "inbox/read/"), ids === "all" ? { all: true } : { ids }, { toast: false }),
  archive: (companyId: number, id: number) => http.post<void>(ownerPath(companyId, `inbox/${id}/archive/`)),
  runInboxAction: (companyId: number, id: number, key: string, reason?: string) =>
    http.post<unknown>(ownerPath(companyId, `inbox/${id}/actions/${key}/`), reason ? { reason } : {}),
};
