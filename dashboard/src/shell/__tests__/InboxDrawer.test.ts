// The registry first, as in the app.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Notification, QueueItem } from "@/api/types";
import { confirmQueue, settleConfirm } from "@/components/useConfirm";
import { toasts } from "@/components/useToast";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import InboxDrawer from "../InboxDrawer.vue";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stub(routes: Record<string, (call: Call) => Response | Promise<Response>>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url: input, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      return routes[`${call.method} ${path}`]?.(call) ?? json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const item = (id: number, kind: string): QueueItem => ({
  kind,
  id,
  title: `Request ${id}`,
  subtitle: "Waiting",
  created_at: "2026-10-21T04:00:00Z",
  url: `/c/1/time-off?request=${id}`,
  actions: [{ key: "approve", label: "Approve", style: "primary", method: "POST", endpoint: `time-off/${id}/approve/`, body: { source: "dashboard" }, needs_reason: false }],
});

const note: Notification = {
  id: 7,
  kind: "finance.claim",
  severity: "info",
  title: "Expense claim",
  body: "450 000 so‘m",
  url: "",
  app_screen: "",
  target_type: "claim",
  target_id: 88,
  actor: null,
  actions: [{ key: "reject", label: "Reject", style: "danger", needs_reason: true }],
  data: {},
  created_at: "2026-10-21T04:00:00Z",
  read_at: null,
  acted_at: null,
  acted_by: null,
};

beforeEach(() => toasts.splice(0, toasts.length));
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
  confirmQueue.value = [];
});

describe("InboxDrawer", () => {
  it("groups Needs you by kind and decides an item in place", async () => {
    let release!: () => void;
    const calls = stub({
      "GET queue/counts/": () => json({ total: 2, kinds: [{ kind: "timeoff.requests", label: "Time off", count: 2 }, { kind: "members.join", label: "Join requests", count: 0 }] }),
      "GET queue/": () => json({ items: [item(1, "timeoff.requests"), item(2, "timeoff.requests")] }),
      "POST time-off/1/approve/": () => new Promise<Response>((resolve) => (release = () => resolve(json({ ok: true })))),
    });
    const app = await testApp("/c/1?inbox=needs");
    mountWithProviders(InboxDrawer, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const body = document.body;
    expect(body.textContent).toContain("Time off");
    // A kind with nothing waiting gets no heading.
    expect(body.textContent).not.toContain("Join requests");
    const approve = [...body.querySelectorAll("button")].find((b) => b.textContent?.trim() === "Approve")!;
    approve.click();
    await flushPromises();
    expect(body.textContent).not.toContain("Request 1");
    release();
    await flushPromises();
    const post = calls.find((c) => c.method === "POST");
    expect(post?.url).toBe("/api/v1/owner/companies/1/time-off/1/approve/");
    // The action's own body goes along.
    expect(post?.body).toEqual({ source: "dashboard" });
  });

  it("closes from the button in its own header, like every other drawer", async () => {
    stub({ "GET queue/counts/": () => json({ total: 0, kinds: [] }), "GET queue/": () => json({ items: [] }) });
    const app = await testApp("/c/1?inbox=needs");
    mountWithProviders(InboxDrawer, { plugins: app.plugins });
    await flushPromises();
    const close = document.body.querySelector<HTMLButtonElement>("[data-inbox-close]")!;
    expect(close.getAttribute("aria-label")).toBe("Close");
    close.click();
    await flushPromises();
    expect(app.router.currentRoute.value.query.inbox).toBeUndefined();
  });

  it("asks for a reason before a notification action that needs one and shows the server's answer", async () => {
    const calls = stub({
      "GET queue/counts/": () => json({ total: 0, kinds: [] }),
      "GET queue/": () => json({ items: [] }),
      "GET inbox/": () => json({ count: 1, next: null, previous: null, results: [note] }),
      "POST inbox/7/actions/reject/": () => json({ message: "Claim rejected.", notification: { ...note, actions: [], acted_at: "2026-10-21T05:00:00Z" } }),
    });
    const app = await testApp("/c/1?inbox=notifications");
    mountWithProviders(InboxDrawer, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const reject = [...document.body.querySelectorAll("button")].find((b) => b.textContent?.trim() === "Reject")!;
    reject.click();
    await flushPromises();
    expect(confirmQueue.value[0]?.request).toMatchObject({ title: "Reject", reason: "required" });
    settleConfirm(confirmQueue.value[0]!.id, { reason: "No receipt" }, 0);
    await flushPromises();
    await flushPromises();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ reason: "No receipt" });
    expect(toasts.at(-1)?.title).toBe("Claim rejected.");
  });
});
