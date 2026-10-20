// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BranchToday, StreamItem } from "@/api/types";
import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders as mountRaw, testApp } from "@/test/plugins";

import { listBranchesToday, listStream, minutesLate, overviewKeys } from "../api";
import en from "../i18n/en.json";
import module from "../index";
import OverviewPage from "../pages/OverviewPage.vue";
import ActivityWidget from "../widgets/ActivityWidget.vue";
import BranchesWidget from "../widgets/BranchesWidget.vue";

function stub(routes: Record<string, () => Response>): string[] {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      calls.push(input);
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      return routes[path]?.() ?? json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const branch = (overrides: Partial<BranchToday>): BranchToday => ({
  id: 1,
  name: "Chilonzor",
  code: "CHL",
  opens_at: "09:00",
  closes_at: "21:00",
  status: "open",
  ...overrides,
});

// Unmounted after each test, so shared tickers (useNow) start fresh with the next test's clock.
const mounted: Array<{ unmount: () => void }> = [];
function mountWithProviders(...args: Parameters<typeof mountRaw>) {
  const result = mountRaw(...args);
  mounted.push(result.wrapper);
  return result;
}

beforeEach(() => {
  mergeModuleMessages("overview", { en, ru: en, uz: en });
});

afterEach(() => {
  mounted.splice(0).forEach((wrapper) => wrapper.unmount());
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("registration", () => {
  it("serves the company index with its two widgets and the hero slot's page", () => {
    expect(module).toMatchObject({ id: "overview", group: "overview", order: 10, index: true, hotkey: "o" });
    expect(module.routes[0]).toMatchObject({ path: "", name: "overview.today" });
    expect(module.widgets?.map((w) => [w.id, w.span])).toEqual([
      ["overview.branches", 4],
      ["overview.activity", 2],
    ]);
  });

  it("reads the W0 console endpoints under its own keys", async () => {
    const calls = stub({ "branches/today/": () => json([]), "stream/": () => json({ items: [] }) });
    await listBranchesToday(1);
    await listStream(1, { limit: 8 });
    expect(calls).toEqual(["/api/v1/owner/companies/1/branches/today/", "/api/v1/owner/companies/1/stream/?limit=8"]);
    expect(overviewKeys.branches(1)).toEqual([1, "overview", "branches", {}]);
  });

  it("counts minutes past opening time on the company clock", () => {
    expect(minutesLate("09:00", { getHours: () => 9, getMinutes: () => 12 })).toBe(12);
    expect(minutesLate("09:00", { getHours: () => 8, getMinutes: () => 59 })).toBe(0);
    expect(minutesLate(null, { getHours: () => 12, getMinutes: () => 0 })).toBe(0);
  });
});

describe("OverviewPage", () => {
  it("greets the person in the company's time and lays out every registered widget", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    // 10:30 in Tashkent (UTC+5).
    vi.setSystemTime(new Date("2026-10-21T05:30:00Z"));
    stub({ "branches/today/": () => json([]), "stream/": () => json({ items: [] }), "queue/counts/": () => json({ total: 0, kinds: [] }), "queue/": () => json({ items: [] }) });
    const app = await testApp("/c/1");
    const { wrapper } = mountWithProviders(OverviewPage, { plugins: app.plugins });
    await flushPromises();
    expect(wrapper.find("h1").text()).toBe("Good morning, Dilnoza");
    expect(wrapper.text()).toContain("Demo Shop");
    const ids = wrapper.findAll("[data-widget]").map((el) => el.attributes("data-widget"));
    // Every module's widgets, by their order: branches (10), the inbox's Needs you (30), activity (40).
    expect(ids).toEqual(["overview.branches", "inbox.needs", "overview.activity"]);
  });
});

describe("BranchesWidget", () => {
  it("shows who opened each branch, which one is late, and the facts other modules send", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-21T05:12:00Z")); // 10:12 in Tashkent
    stub({
      "branches/today/": () =>
        json([
          branch({
            status: "open",
            sales: { opened_at: "2026-10-21T03:57:00Z", opened_by: { id: 11, name: "Dilnoza Karimova" }, open_tills: 2, net: "6140000.00", cash_in_branch: "4210000.00" },
            attendance: { rostered: 7, checked_in: 6, first_check_in: "2026-10-21T03:50:00Z" },
            tasks: { done: 18, total: 22, late: 1 },
          }),
          branch({ id: 2, name: "Yunusobod", code: "YNS", opens_at: "10:00", status: "not_opened" }),
          branch({ id: 3, name: "Sergeli", code: "SRG", status: "day_off" }),
        ]),
    });
    const app = await testApp("/c/1");
    const { wrapper } = mountWithProviders(BranchesWidget, { plugins: app.plugins, props: { companyId: 1 } });
    await flushPromises();
    const cards = wrapper.findAll("li");
    expect(cards).toHaveLength(3);
    expect(cards[0]!.text()).toContain("Opened 08:57 by Dilnoza");
    expect(cards[0]!.text()).toContain("6/7");
    expect(cards[0]!.text()).toContain("1 late");
    expect(cards[1]!.text()).toContain("Not opened · +12 min");
    expect(cards[1]!.text()).toContain(en["overview.branches.noFacts"]);
    expect(cards[2]!.text()).toContain("Day off");
    expect(wrapper.text()).toContain("1 of 3 open");
  });

  it("says so when there are no branches", async () => {
    stub({ "branches/today/": () => json([]) });
    const app = await testApp("/c/1");
    const { wrapper } = mountWithProviders(BranchesWidget, { plugins: app.plugins, props: { companyId: 1 } });
    await flushPromises();
    expect(wrapper.text()).toContain("No branches yet");
  });
});

describe("ActivityWidget", () => {
  it("lists the stream newest first and links each item inside the company", async () => {
    const items: StreamItem[] = [
      { at: "2026-10-21T05:00:00Z", kind: "tasks.done", actor: { id: 3, name: "Madina Saidova" }, title: "Fridge check", url: "tasks?task=351", photo_url: null },
      { at: "2026-10-21T04:00:00Z", kind: "finance.expense", actor: null, title: "Rent recorded", url: "/c/1/finance/transactions", photo_url: null },
    ];
    stub({ "stream/": () => json({ items }) });
    const app = await testApp("/c/1");
    const { wrapper } = mountWithProviders(ActivityWidget, { plugins: app.plugins, props: { companyId: 1 } });
    await flushPromises();
    const links = wrapper.findAll("a");
    expect(links.map((a) => a.attributes("href"))).toEqual(["/c/1/tasks?task=351", "/c/1/finance/transactions"]);
    expect(links[1]!.text()).toContain("System");
  });

  it("is quiet when nothing happened", async () => {
    stub({ "stream/": () => json({ items: [] }) });
    const app = await testApp("/c/1");
    const { wrapper } = mountWithProviders(ActivityWidget, { plugins: app.plugins, props: { companyId: 1 } });
    await flushPromises();
    expect(wrapper.text()).toContain("Quiet so far");
  });
});
