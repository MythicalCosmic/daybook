/**
 * VITE_MOCK=1 (dev server only): answers the shell's endpoints from src/dev/mockData.ts so the
 * console runs, and can be screenshotted, without the backend. Shapes follow plan §4.2 and §4.3 and
 * src/api/types.ts. Unknown endpoints answer 404 like the real API would for a missing module.
 * main.ts imports this only behind `import.meta.env.DEV`, so it never reaches a build.
 */
import type { Language } from "@/api/types";

import { companies, meFor, notifications, notificationsFor, pulseCounters, queueCountsFor, queueFor, queueItems, search } from "./mockData";
import { auditRecords, createExport, exportersFor, exportList, exportStatus, MORE_NOTIFICATIONS, PEOPLE, POSITIONS } from "./mockExtras";
import { branchesToday, streamFor } from "./mockOverview";

// A longer history for the inbox page (the drawer shows the first page).
notifications[1]?.push(...(MORE_NOTIFICATIONS as unknown as NonNullable<(typeof notifications)[number]>));

interface MockResult {
  status: number;
  body?: unknown;
}

const SIGNED_OUT = "daybook.console.mock.signedOut";
const LANGUAGE = "daybook.console.mock.language";

function storedLanguage(): Language {
  try {
    const value = window.localStorage.getItem(LANGUAGE);
    return value === "uz" || value === "ru" || value === "en" ? value : "en";
  } catch {
    return "en";
  }
}

function setStoredLanguage(language: Language): void {
  try {
    window.localStorage.setItem(LANGUAGE, language);
  } catch {
    // Mock only: forgetting the choice is fine.
  }
}

function signedOut(): boolean {
  try {
    return window.sessionStorage.getItem(SIGNED_OUT) === "1";
  } catch {
    return false;
  }
}

function setSignedOut(value: boolean): void {
  try {
    if (value) window.sessionStorage.setItem(SIGNED_OUT, "1");
    else window.sessionStorage.removeItem(SIGNED_OUT);
  } catch {
    // ignore
  }
}

const versions: Record<number, Record<string, number>> = {};

interface MockSavedView {
  id: number;
  module: string;
  name: string;
  state: Record<string, unknown>;
  is_shared: boolean;
  order: number;
  owner: { id: number; name: string };
  is_mine: boolean;
}
const savedViews: MockSavedView[] = [];
function bumpVersions(companyId: number): Record<string, string> {
  const current = (versions[companyId] ??= { "inbox.unread": 1, "console.queue": 1, "console.saved_views": 1, "exports.exports": 1, "tasks.tasks": 1, "sales.shifts": 1 });
  // Now and then something changes, so pulse-driven refreshes are exercised in development.
  if (Math.random() < 0.15) {
    const keys = Object.keys(current);
    const key = keys[Math.floor(Math.random() * keys.length)]!;
    current[key] = (current[key] ?? 0) + 1;
  }
  return Object.fromEntries(Object.entries(current).map(([k, v]) => [k, String(v)]));
}

const access = () => ({ access: `mock.${Date.now().toString(36)}` });

function companyOf(path: string): { id: number; rest: string } | null {
  const match = /^\/owner\/companies\/(\d+)\/(.*)$/.exec(path);
  if (!match) return null;
  return { id: Number(match[1]), rest: match[2] ?? "" };
}

function route(method: string, path: string, query: URLSearchParams, body: Record<string, unknown> | undefined, language: Language): MockResult {
  // Auth (§4.3)
  if (path === "/owner/auth/refresh/") return signedOut() ? { status: 401, body: { detail: "Not signed in." } } : { status: 200, body: access() };
  if (path === "/owner/auth/logout/") {
    setSignedOut(true);
    return { status: 204 };
  }
  if (path === "/owner/auth/dev-login/" || path === "/owner/auth/telegram/") {
    setSignedOut(false);
    return { status: 200, body: access() };
  }
  if (signedOut()) return { status: 401, body: { detail: "Authentication credentials were not provided." } };

  // Me (§4.2)
  if (path === "/owner/me/") {
    if (method === "PATCH" && (body?.language === "uz" || body?.language === "ru" || body?.language === "en")) setStoredLanguage(body.language);
    return { status: 200, body: meFor(storedLanguage()) };
  }

  const scoped = companyOf(path);
  if (!scoped) return { status: 404, body: { detail: "Not found." } };
  const { id, rest } = scoped;
  if (!companies.some((c) => c.id === id)) return { status: 404, body: { detail: "Not found." } };

  if (rest === "pulse/") {
    const counters = { ...(pulseCounters[id] ?? {}) };
    counters["console.queue"] = queueItems[id]?.length ?? 0;
    counters["inbox.unread"] = (notifications[id] ?? []).filter((n) => !n.read_at).length;
    return { status: 200, body: { counters, versions: bumpVersions(id) } };
  }
  if (rest === "search/") return { status: 200, body: { results: search(id, language, query.get("q") ?? "") } };
  if (rest === "queue/") return { status: 200, body: queueFor(id, language, query.get("kind")) };
  if (rest === "queue/counts/") return { status: 200, body: queueCountsFor(id, language) };
  if (rest === "stream/") return { status: 200, body: { items: streamFor(id, language) } };
  if (rest === "branches/today/") return { status: 200, body: branchesToday(id, language) };
  if (rest === "inbox/") {
    const all = notificationsFor(id, language, query.get("tab") ?? "all");
    const page = Number(query.get("page") ?? 1);
    const size = Number(query.get("page_size") ?? 30);
    const results = all.slice((page - 1) * size, page * size);
    const next = page * size < all.length ? `?page=${page + 1}` : null;
    return { status: 200, body: { count: all.length, next, previous: page > 1 ? `?page=${page - 1}` : null, results } };
  }
  const archived = /^inbox\/(\d+)\/archive\/$/.exec(rest);
  if (archived && method === "POST") {
    const list = notifications[id] ?? [];
    const index = list.findIndex((n) => n.id === Number(archived[1]));
    if (index < 0) return { status: 404, body: { detail: "Not found." } };
    const [gone] = list.splice(index, 1);
    return { status: 200, body: notificationsFor(id, language, "all", gone ? [gone] : [])[0] };
  }
  if (rest === "audit/records/") {
    const results = auditRecords(language);
    return { status: 200, body: { count: results.length, next: null, previous: null, results } };
  }
  if (rest === "exports/" && method === "POST") return { status: 202, body: createExport(body) };
  if (rest === "exports/") {
    const results = exportList(language);
    return { status: 200, body: { count: results.length, next: null, previous: null, results } };
  }
  if (rest === "exports/kinds/") return { status: 200, body: exportersFor(language) };
  const exportJob = /^exports\/(\d+)\/$/.exec(rest);
  if (exportJob) {
    const job = exportStatus(Number(exportJob[1]), language);
    return job ? { status: 200, body: job } : { status: 404, body: { detail: "Not found." } };
  }
  if (rest === "people/") return { status: 200, body: { count: PEOPLE.length, next: null, previous: null, results: PEOPLE } };
  if (rest === "positions/") return { status: 200, body: { count: POSITIONS.length, next: null, previous: null, results: POSITIONS } };
  if (rest === "saved-views/") {
    if (method === "GET") return { status: 200, body: savedViews.filter((view) => !query.get("module") || view.module === query.get("module")) };
    const view = { id: Date.now(), module: String(body?.module ?? ""), name: String(body?.name ?? ""), state: (body?.state as Record<string, unknown>) ?? {}, is_shared: body?.is_shared === true, order: 0, owner: { id: 11, name: "Dilnoza Karimova" }, is_mine: true };
    savedViews.push(view);
    return { status: 201, body: view };
  }
  const savedView = /^saved-views\/(\d+)\/$/.exec(rest);
  if (savedView) {
    const index = savedViews.findIndex((view) => view.id === Number(savedView[1]));
    if (index < 0) return { status: 404, body: { detail: "Not found." } };
    if (method === "DELETE") {
      savedViews.splice(index, 1);
      return { status: 204 };
    }
    savedViews[index] = { ...savedViews[index]!, ...(body as object) };
    return { status: 200, body: savedViews[index] };
  }
  if (rest === "inbox/unread-count/") {
    const list = notifications[id] ?? [];
    return { status: 200, body: { count: list.filter((n) => !n.read_at).length, critical: list.filter((n) => !n.read_at && n.severity === "critical").length } };
  }
  if (rest === "inbox/read/" && method === "POST") {
    const ids = Array.isArray(body?.ids) ? (body.ids as number[]) : null;
    let updated = 0;
    for (const note of notifications[id] ?? []) {
      if ((body?.all || ids?.includes(note.id)) && !note.read_at) {
        note.read_at = new Date().toISOString();
        updated += 1;
      }
    }
    return { status: 200, body: { updated } };
  }
  const inboxAction = /^inbox\/(\d+)\/actions\/(\w+)\/$/.exec(rest);
  if (inboxAction && method === "POST") {
    const note = (notifications[id] ?? []).find((n) => n.id === Number(inboxAction[1]));
    if (!note) return { status: 404, body: { detail: "Not found." } };
    note.acted_at = new Date().toISOString();
    note.read_at ??= note.acted_at;
    note.acted_by = "Dilnoza Karimova";
    const done = { en: "Done.", ru: "Готово.", uz: "Bajarildi." }[language];
    return { status: 200, body: { message: done, notification: notificationsFor(id, language, "all", [note])[0] } };
  }

  // Any queue action endpoint (relative to the company): the decision succeeds and the item leaves the queue.
  if (method !== "GET") {
    const list = queueItems[id] ?? [];
    const index = list.findIndex((item) => item.actions.some((action) => action.endpoint === rest));
    if (index >= 0) {
      list.splice(index, 1);
      return { status: 200, body: { detail: "ok" } };
    }
  }
  return { status: 404, body: { detail: "This part of the console isn’t built yet." } };
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export function installMock(): void {
  const realFetch = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const href = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(href, window.location.origin);
    if (!url.pathname.startsWith("/api/v1/")) return realFetch(input, init);

    const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
    const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
    const header = headers.get("Accept-Language");
    const language: Language = header === "ru" || header === "uz" || header === "en" ? header : "en";
    let body: Record<string, unknown> | undefined;
    if (typeof init?.body === "string") {
      try {
        body = JSON.parse(init.body) as Record<string, unknown>;
      } catch {
        body = undefined;
      }
    }
    const path = url.pathname.slice("/api/v1".length);
    await sleep(path.endsWith("/pulse/") ? 60 : 140 + Math.random() * 220);
    if (init?.signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const result = route(method, path, url.searchParams, body, language);
    const noBody = result.status === 204 || result.body === undefined;
    return new Response(noBody ? null : JSON.stringify(result.body), {
      status: result.status,
      headers: { "Content-Type": "application/json" },
    });
  };
  console.info("[mock] API answered from src/dev/mockData.ts");
}
