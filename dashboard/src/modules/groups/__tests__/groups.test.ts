// The registry first, as in the app (core/modules loads every module's index.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { confirmQueue, settleConfirm } from "@/components/useConfirm";
import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { applyPatch } from "../api";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import GroupsPage from "../pages/GroupsPage.vue";
import type { GroupsList, TelegramGroup } from "../types";

mergeModuleMessages("groups", { en, ru, uz });

interface Call {
  method: string;
  url: string;
  body: unknown;
}

class NoResize {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

function stub(routes: Record<string, (call: Call) => Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("ResizeObserver", NoResize);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      const path = url.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      const handler = routes[`${call.method} ${path}`];
      return handler ? handler(call) : json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const GROUP: TelegramGroup = {
  id: 5,
  title: "Chilonzor jamoasi",
  chat_id: -100123,
  is_active: true,
  events: [
    { key: "daily_done", label: "Daily tasks done", feature: null, on: true, available: true },
    { key: "late", label: "Late tasks", feature: null, on: true, available: true },
    { key: "evening", label: "End-of-day summary", feature: null, on: false, available: true },
    { key: "sales", label: "Sales", feature: "sales", on: false, available: true },
  ],
  positions: [],
  branches: [{ id: 1, name: "Chilonzor" }],
  linked_by: { id: 2, name: "Bekzod Mirzayev" },
  connected_at: "2026-10-12T09:00:00Z",
  updated_at: "2026-10-12T09:00:00Z",
};

const LIST: GroupsList = {
  results: [GROUP],
  connect_link: "https://t.me/daybook_bot?startgroup=connect",
  bot_username: "daybook_bot",
  person_events: ["daily_done", "tasks_done", "late", "members"],
  options: { positions: [{ id: 3, name: "Cashier" }], branches: [{ id: 1, name: "Chilonzor" }, { id: 2, name: "Yunusobod" }] },
};

afterEach(() => {
  vi.unstubAllGlobals();
  confirmQueue.value = [];
});

describe("applyPatch", () => {
  it("is what the server answers", () => {
    const next = applyPatch(GROUP, { events: ["evening"], branch_ids: [2], position_ids: [3] }, LIST.options);
    expect(next.events.filter((e) => e.on).map((e) => e.key)).toEqual(["evening"]);
    expect(next.branches).toEqual([{ id: 2, name: "Yunusobod" }]);
    expect(next.positions).toEqual([{ id: 3, name: "Cashier" }]);
  });
});

describe("GroupsPage", () => {
  it("toggles an event at once, sends the whole event list, and rolls back on refusal", async () => {
    let refuse = false;
    const calls = stub({
      "GET groups/": () => json(LIST),
      "PATCH groups/5/": (call) => (refuse ? json({ detail: "No" }, 400) : json(applyPatch(GROUP, call.body as never, LIST.options))),
    });
    const app = await testApp("/c/1/groups");
    const { wrapper } = mountWithProviders(GroupsPage, { plugins: app.plugins });
    await flushPromises();

    expect(wrapper.text()).toContain("Chilonzor jamoasi");
    expect(wrapper.text()).toContain("Connected by Bekzod Mirzayev");
    const evening = () => wrapper.findAll('[role="switch"]')[2]!;
    await evening().trigger("click");
    await flushPromises();
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ events: ["daily_done", "late", "evening"] });
    expect(evening().attributes("data-state")).toBe("checked");

    refuse = true;
    await evening().trigger("click");
    await flushPromises();
    expect(evening().attributes("data-state")).toBe("checked");
  });

  it("disconnects after asking", async () => {
    const calls = stub({ "GET groups/": () => json(LIST), "POST groups/5/disconnect/": () => json({ ...GROUP, is_active: false }) });
    const app = await testApp("/c/1/groups");
    const { wrapper } = mountWithProviders(GroupsPage, { plugins: app.plugins, attach: true });
    await flushPromises();

    await wrapper.find('button[aria-label="Group actions"]').trigger("click");
    await flushPromises();
    const item = [...document.querySelectorAll('[role="menuitem"]')].find((el) => el.textContent?.includes("Disconnect")) as HTMLElement | undefined;
    item?.click();
    await flushPromises();
    if (confirmQueue.value[0]) settleConfirm(confirmQueue.value[0].id, { reason: "" }, 0);
    await flushPromises();
    if (item) expect(calls.some((c) => c.url.endsWith("groups/5/disconnect/"))).toBe(true);
  });

  it("explains how to connect the first group", async () => {
    stub({ "GET groups/": () => json({ ...LIST, results: [] }) });
    const app = await testApp("/c/1/groups");
    const { wrapper } = mountWithProviders(GroupsPage, { plugins: app.plugins });
    await flushPromises();

    expect(wrapper.text()).toContain("No groups connected yet");
    expect(wrapper.text()).toContain("@daybook_bot");
    expect(wrapper.find('a[href="https://t.me/daybook_bot?startgroup=connect"]').exists()).toBe(true);
  });
});
