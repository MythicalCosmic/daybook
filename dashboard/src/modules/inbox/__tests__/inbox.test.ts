// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { confirmQueue, settleConfirm } from "@/components/useConfirm";
import { toasts } from "@/components/useToast";
import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { archiveNotification, inboxKeys, listNotifications, listQueue, markRead, runNotificationAction, runQueueAction } from "../api";
import en from "../i18n/en.json";
import module from "../index";
import InboxPage from "../pages/InboxPage.vue";
import type { Notification, QueueItem, QueueResponse } from "../types";

const item = (id: number, kind: string, needsReason = false): QueueItem => ({
  kind,
  id,
  title: `Item ${id}`,
  subtitle: "Subtitle",
  created_at: "2026-10-20T09:00:00Z",
  url: `tasks?task=${id}`,
  actor: { id: 1, name: "Madina Saidova", photo_url: null },
  actions: [
    { key: "approve", label: "Approve", style: "primary", method: "POST", endpoint: `${kind}/${id}/approve/`, needs_reason: false },
    { key: "reject", label: "Reject", style: "danger", method: "POST", endpoint: `${kind}/${id}/reject/`, needs_reason: needsReason },
  ],
});

const note = (id: number, read = false): Notification => ({
  id,
  kind: "sales.cash_difference",
  severity: "critical",
  title: `Note ${id}`,
  body: "Body",
  url: "sales/shifts/1042",
  created_at: "2026-10-20T09:00:00Z",
  read_at: read ? "2026-10-20T10:00:00Z" : null,
  acted_at: null,
  actor: null,
  actions: [],
  data: {},
});

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stubApi(routes: Record<string, (call: Call) => Response | Promise<Response>>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url: input, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      const handler = routes[`${call.method} ${path}`];
      return handler ? handler(call) : json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

beforeEach(() => {
  mergeModuleMessages("inbox", { en, ru: en, uz: en });
  toasts.splice(0, toasts.length);
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
  confirmQueue.value = [];
});

describe("api", () => {
  it("calls the plan's endpoints with the right params and bodies", async () => {
    const calls = stubApi({
      "GET queue/": () => json({ total: 0, kinds: [], results: [] }),
      "GET inbox/": () => json({ count: 0, next: null, previous: null, results: [] }),
      "POST inbox/read/": () => json(null, 204),
      "POST inbox/9/archive/": () => json(null, 204),
      "POST inbox/9/actions/approve/": () => json({}),
      "POST time-off/42/reject/": () => json({}),
    });
    await listQueue(1, { kind: "timeoff.request" });
    await listNotifications(1, { tab: "unread", page: 2 });
    await markRead(1, [3, 4]);
    await markRead(1, "all");
    await archiveNotification(1, 9);
    await runNotificationAction(1, 9, "approve", "ok");
    await runQueueAction(1, { key: "reject", label: "Reject", style: "danger", method: "POST", endpoint: "time-off/42/reject/", body: { notify: true }, needs_reason: true }, "Busy week");
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET /api/v1/owner/companies/1/queue/?kind=timeoff.request",
      "GET /api/v1/owner/companies/1/inbox/?tab=unread&page=2&page_size=30",
      "POST /api/v1/owner/companies/1/inbox/read/",
      "POST /api/v1/owner/companies/1/inbox/read/",
      "POST /api/v1/owner/companies/1/inbox/9/archive/",
      "POST /api/v1/owner/companies/1/inbox/9/actions/approve/",
      "POST /api/v1/owner/companies/1/time-off/42/reject/",
    ]);
    expect(calls[2]!.body).toEqual({ ids: [3, 4] });
    expect(calls[3]!.body).toEqual({ all: true });
    expect(calls[5]!.body).toEqual({ reason: "ok" });
    expect(calls[6]!.body).toEqual({ notify: true, reason: "Busy week" });
  });

  it("keys every query under the company and the module", () => {
    expect(inboxKeys.queue(4, "x")).toEqual([4, "inbox", "queue", { kind: "x" }]);
    expect(inboxKeys.notifications(4, { tab: "all" })).toEqual([4, "inbox", "notifications", { tab: "all" }]);
    expect(inboxKeys.all(4)).toEqual([4, "inbox"]);
  });

  it("registers as the catalog says, with a widget, a command and pulse keys", () => {
    expect(module).toMatchObject({ id: "inbox", group: "overview", order: 20, hotkey: "i", invalidates: ["inbox", "queue"] });
    expect(module.widgets?.map((w) => w.id)).toEqual(["inbox.needs"]);
    expect(module.badge?.({ counters: { "queue.total": 5 }, versions: {} })).toBe(5);
    expect(module.deepLinks?.inbox?.("notifications")).toBe("inbox?tab=notifications");
  });
});

describe("InboxPage", () => {
  async function page(path: string, routes: Record<string, (call: Call) => Response | Promise<Response>>) {
    const calls = stubApi(routes);
    const app = await testApp(path);
    const { wrapper } = mountWithProviders(InboxPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    return { wrapper, calls, app };
  }

  const queue = (): QueueResponse => ({
    total: 3,
    kinds: [
      { kind: "tasks.review", label: "Waiting for your check", count: 2 },
      { kind: "timeoff.request", label: "Time off", count: 1 },
    ],
    results: [item(1, "tasks.review"), item(2, "tasks.review"), item(3, "timeoff.request", true)],
  });

  it("groups Needs you by kind and filters by kind from the URL", async () => {
    const { wrapper } = await page("/c/1/inbox?kind=timeoff.request", { "GET queue/": () => json(queue()) });
    expect(wrapper.text()).toContain("Waiting for your check");
    const cards = wrapper.findAll("[data-queue-item]");
    expect(cards.map((c) => c.text())).toEqual([expect.stringContaining("Item 3")]);
  });

  it("decides an item in place: it leaves at once and the server is told", async () => {
    let release!: () => void;
    const { wrapper, calls } = await page("/c/1/inbox", {
      "GET queue/": () => json(queue()),
      "POST tasks.review/1/approve/": () => new Promise<Response>((resolve) => (release = () => resolve(json({ detail: "ok" })))),
    });
    expect(wrapper.findAll("[data-queue-item]")).toHaveLength(3);
    await wrapper.findAll("button").find((b) => b.text() === "Approve")!.trigger("click");
    await flushPromises();
    // Optimistic: gone before the server answered.
    expect(wrapper.findAll("[data-queue-item]").map((c) => c.text()).some((t) => t.includes("Item 1"))).toBe(false);
    release();
    await flushPromises();
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("tasks.review/1/approve/"))).toBe(true);
    expect(toasts.at(-1)?.title).toBe("Done: Approve");
  });

  it("puts an item back when the server refuses", async () => {
    const { wrapper } = await page("/c/1/inbox", {
      "GET queue/": () => json(queue()),
      "POST tasks.review/2/approve/": () => json({ detail: "Already decided." }, 409),
    });
    await wrapper.findAll("[data-queue-item]")[1]!.findAll("button").find((b) => b.text() === "Approve")!.trigger("click");
    await flushPromises();
    await flushPromises();
    expect(wrapper.findAll("[data-queue-item]").some((c) => c.text().includes("Item 2"))).toBe(true);
  });

  it("asks for a reason before an action that needs one", async () => {
    const { wrapper, calls } = await page("/c/1/inbox?kind=timeoff.request", {
      "GET queue/": () => json(queue()),
      "POST timeoff.request/3/reject/": () => json({ detail: "ok" }),
    });
    await wrapper.findAll("button").find((b) => b.text() === "Reject")!.trigger("click");
    await flushPromises();
    expect(confirmQueue.value[0]?.request).toMatchObject({ reason: "required", title: "Reject" });
    settleConfirm(confirmQueue.value[0]!.id, { reason: "Short-staffed that week" }, 0);
    await flushPromises();
    await flushPromises();
    const call = calls.find((c) => c.url.endsWith("timeoff.request/3/reject/"));
    expect(call?.body).toEqual({ reason: "Short-staffed that week" });
  });

  it("opens a notification from the URL, marks it read and archives it", async () => {
    let server = [note(7), note(8, true)];
    const { wrapper, calls, app } = await page("/c/1/inbox?tab=notifications&show=all&note=7", {
      "GET queue/": () => json(queue()),
      "GET inbox/": () => json({ count: server.length, next: null, previous: null, results: server }),
      "POST inbox/read/": () => json(null, 204),
      "POST inbox/7/archive/": () => {
        server = server.filter((n) => n.id !== 7);
        return json(null, 204);
      },
    });
    expect(wrapper.text()).toContain("Urgent");
    expect(calls.find((c) => c.url.endsWith("inbox/read/"))?.body).toEqual({ ids: [7] });
    await wrapper.findAll("button").find((b) => b.text().startsWith("Archive"))!.trigger("click");
    await flushPromises();
    expect(calls.some((c) => c.url.endsWith("inbox/7/archive/"))).toBe(true);
    expect(app.router.currentRoute.value.query.note).toBeUndefined();
    expect(wrapper.findAll("[data-note]").map((el) => el.attributes("data-note"))).toEqual(["8"]);
  });

  it("says when everything is handled", async () => {
    const { wrapper } = await page("/c/1/inbox", { "GET queue/": () => json({ total: 0, kinds: [], results: [] }) });
    expect(wrapper.text()).toContain("All caught up");
  });
});
