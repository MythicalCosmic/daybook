// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BranchToday, StreamItem } from "@/api/types";
import { modules } from "@/core/modules";
import { mergeModuleMessages } from "@/i18n";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { json } from "@/test/fixtures";
import { mountWithProviders as mountRaw, testApp } from "@/test/plugins";

import { listBranchesToday, listStream, minutesLate, overviewKeys } from "../api";
import { cockpit, isDefaultLayout, layoutFromState, layoutToState, pack } from "../layout";
import en from "../i18n/en.json";
import module from "../index";
import OverviewPage from "../pages/OverviewPage.vue";
import ActivityWidget from "../widgets/ActivityWidget.vue";
import BranchesWidget from "../widgets/BranchesWidget.vue";
import RoutinesTodayWidget from "../widgets/RoutinesTodayWidget.vue";

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
  it("serves the company index with its widgets and the hero slot's page", () => {
    expect(module).toMatchObject({ id: "overview", group: "overview", order: 10, index: true, hotkey: "o" });
    expect(module.routes[0]).toMatchObject({ path: "", name: "overview.today" });
    expect(module.widgets?.map((w) => [w.id, w.span, w.kind])).toEqual([
      ["overview.branches", 4, "card"],
      // Beside the one-off task tiles (orders 10-12), for whoever sees everyone's work.
      ["overview.routines", 1, "kpi"],
      ["overview.activity", 2, "card"],
    ]);
    expect(module.widgets?.find((w) => w.id === "overview.routines")).toMatchObject({ order: 13, perm: "tasks.view_all" });
  });

  it("shows a widget's skeleton at once while its first data loads (its cell's placeholder came just before)", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));
    const app = await testApp("/c/1");
    const { wrapper } = mountWithProviders(ActivityWidget, { plugins: app.plugins, props: { companyId: 1 } });
    await flushPromises();
    // No 150 ms wait: the card never shrinks to its header between two placeholders.
    expect(wrapper.findComponent(SkeletonBlock).exists()).toBe(true);
  });

  it("counts today's routine work apart from one-off tasks", async () => {
    const day = (totals: Partial<Record<string, number>>, holiday = false) =>
      json({ day: "2026-10-21", holiday, idle: 1, routines: [], totals: { done: 0, review: 0, late: 0, missed: 0, open: 0, returned: 0, cancelled: 0, skipped: 0, total: 0, finished: 0, routines: 0, ...totals } });
    const calls = stub({ "routines/day/": () => day({ done: 9, review: 3, late: 2, missed: 1, open: 3, total: 18, finished: 12, routines: 6 }) });
    const app = await testApp("/c/1");
    const { wrapper } = mountWithProviders(RoutinesTodayWidget, { plugins: app.plugins, props: { companyId: 1 } });
    await flushPromises();
    expect(calls).toEqual(["/api/v1/owner/companies/1/routines/day/"]);
    expect(wrapper.text()).toContain(en["overview.routines.title"]);
    expect(wrapper.text()).toContain("12 of 18");
    expect(wrapper.text()).toContain("3 late · 3 to confirm");
    expect(wrapper.find("a").attributes("href")).toContain("/c/1/routines");

    stub({ "routines/day/": () => day({}, true) });
    const holiday = mountWithProviders(RoutinesTodayWidget, { plugins: (await testApp("/c/1")).plugins, props: { companyId: 1 } });
    await flushPromises();
    expect(holiday.wrapper.text()).toContain(en["overview.routines.holiday"]);
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
    expect(wrapper.text()).toContain("Demo Dorixona");
    const ids = wrapper.findAll("[data-widget]").map((el) => el.attributes("data-widget")!);
    // Other modules add widgets of their own, so this checks the rules, not one exact list:
    // W0's own widgets are there, in their order (branches 10, the inbox's Needs you 30, activity 40)…
    const w0 = ["overview.branches", "inbox.needs", "overview.activity"];
    expect(ids).toEqual(expect.arrayContaining(w0));
    expect(ids.filter((id) => w0.includes(id))).toEqual(w0);
    // …each widget once, every one of them registered…
    const registered = new Map(modules.flatMap((m) => m.widgets ?? []).map((w) => [w.id, w]));
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids.every((id) => registered.has(id))).toBe(true);
    // …branches leading the page, then every KPI tile together, by `order` and then by id.
    const kpis = wrapper.findAll('[data-band="kpis"] [data-widget]').map((el) => el.attributes("data-widget")!);
    const allKpis = ids.filter((id) => registered.get(id)!.kind === "kpi");
    expect(ids.slice(0, ids.indexOf(allKpis[0]!))).toContain("overview.branches");
    expect(kpis.slice(0, allKpis.length)).toEqual(allKpis);
    const byOrder = [...allKpis].sort((a, b) => registered.get(a)!.order - registered.get(b)!.order || a.localeCompare(b));
    expect(allKpis).toEqual(byOrder);
  });

  it("saves the person's arrangement as their overview layout and resets it", async () => {
    const sent: Array<{ method: string; path: string; body: unknown }> = [];
    let views: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string, init?: RequestInit) => {
        const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
        const method = init?.method ?? "GET";
        if (method !== "GET") sent.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : null });
        if (path === "saved-views/" && method === "GET") return json(views);
        if (path === "saved-views/" && method === "POST") {
          views = [{ id: 9, module: "overview", name: "layout", state: (sent.at(-1)!.body as { state: unknown }).state, is_shared: false, order: 0, owner: { id: 1, name: "Dilnoza" }, is_mine: true }];
          return json(views[0], 201);
        }
        if (path === "saved-views/9/" && method === "DELETE") {
          views = [];
          return new Response(null, { status: 204 });
        }
        if (path === "branches/today/") return json([]);
        if (path === "stream/") return json({ items: [] });
        if (path === "queue/counts/") return json({ total: 0, kinds: [] });
        if (path === "queue/") return json({ items: [] });
        return json({ detail: "Not found." }, 404);
      }),
    );
    const app = await testApp("/c/1");
    const { wrapper } = mountWithProviders(OverviewPage, { plugins: app.plugins });
    await flushPromises();
    const button = (label: string) => wrapper.findAll("button").find((b) => b.text() === label)!;

    await button(en["overview.customize.open"]).trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain(en["overview.customize.hint"]);
    // Hide Activity with its eye, then Done: the layout is saved with Activity hidden.
    const activity = wrapper.find('[data-widget="overview.activity"]');
    await activity.find("button[aria-pressed]").trigger("click");
    await button("Done").trigger("click");
    // The write loads its helper on use: wait for it, then for the list to refetch.
    await vi.waitFor(() => expect(sent.some((call) => call.method === "POST" && call.path === "saved-views/")).toBe(true));
    await flushPromises();
    const created = sent.find((call) => call.method === "POST" && call.path === "saved-views/")!;
    expect(created.body).toMatchObject({ module: "overview", name: "layout", is_shared: false });
    const rows = (created.body as { state: { widgets: Array<{ id: string; hidden: boolean; order: number }> } }).state.widgets;
    expect(rows.find((row) => row.id === "overview.activity")).toMatchObject({ hidden: true });
    expect(rows.map((row) => row.order)).toEqual(rows.map((_, index) => index));
    expect(wrapper.find('[data-widget="overview.activity"]').exists()).toBe(false);

    // Reset brings back the registered order and deletes the saved layout.
    await button(en["overview.customize.open"]).trigger("click");
    await button(en["overview.customize.reset"]).trigger("click");
    await button("Done").trigger("click");
    await flushPromises();
    await vi.waitFor(() => expect(sent.some((call) => call.method === "DELETE" && call.path === "saved-views/9/")).toBe(true));
    await flushPromises();
    expect(wrapper.find('[data-widget="overview.activity"]').exists()).toBe(true);
  });
});

describe("cockpit layout", () => {
  const w = (id: string, kind: "kpi" | "card" | "chart", span: 1 | 2 | 3 | 4 = 1) => ({ id, kind, span });

  it("leads with the cards above the first KPI, gathers the KPIs and squares their band with narrow cards", () => {
    const result = cockpit([w("setup", "card", 2), w("branches", "card", 4), w("k1", "kpi"), w("needs", "card", 2), w("k2", "kpi"), w("k3", "kpi"), w("team", "card", 1), w("off", "card", 1), w("trend", "chart", 2)]);
    expect(result.lead.map((x) => x.id)).toEqual(["setup", "branches"]);
    expect(result.kpis.map((x) => [x.widget.id, x.span])).toEqual([["k1", 1], ["k2", 1], ["k3", 1], ["team", 1]]);
    expect(result.cards.map((x) => [x.widget.id, x.span])).toEqual([["needs", 2], ["off", 2], ["trend", 4]]);
  });

  it("packs cards into full rows: later cards fill earlier gaps and a short row widens", () => {
    const placed = pack([w("a", "card", 2), w("b", "card", 2), w("c", "card", 2), w("d", "card", 1), w("e", "chart", 2), w("f", "card", 1)]);
    // Rows: [a b] [c d f] -> f fills the gap beside c and d, [e] alone widens to the whole row.
    expect(placed.map((x) => [x.widget.id, x.span])).toEqual([["a", 2], ["b", 2], ["c", 2], ["d", 1], ["f", 1], ["e", 4]]);
    expect(pack([w("x", "card", 1), w("y", "card", 1)]).map((x) => x.span)).toEqual([2, 2]);
    expect(pack([w("k1", "kpi"), w("k2", "kpi"), w("k3", "kpi")]).map((x) => x.span)).toEqual([1, 1, 2]);
  });

  it("keeps neighbouring cards of one module in the same row", () => {
    // The registered order of Wave 1: finance's chart would otherwise sit beside "Projects at
    // risk" and leave "My projects" beside the tall agenda.
    const placed = pack([
      w("tasks.trend", "chart", 2),
      w("tasks.top", "card", 2),
      w("finance.flow", "chart", 2),
      w("projects.atRisk", "card", 2),
      w("projects.mine", "card", 2),
      w("agenda.upcoming", "card", 2),
    ]);
    expect(placed.map((x) => x.widget.id)).toEqual(["tasks.trend", "tasks.top", "finance.flow", "agenda.upcoming", "projects.atRisk", "projects.mine"]);
    expect(placed.map((x) => x.span)).toEqual([2, 2, 2, 2, 2, 2]);
    // Apart in the person's own order, they stay apart.
    expect(pack([w("projects.atRisk", "card", 2), w("finance.flow", "chart", 2), w("projects.mine", "card", 2)]).map((x) => x.widget.id)).toEqual(["projects.atRisk", "finance.flow", "projects.mine"]);
  });

  it("reads and writes the saved layout, and knows when it is just the default", () => {
    const widgets = [w("a", "card", 2), w("b", "card", 2), w("c", "kpi")];
    expect(layoutFromState({ widgets: [{ id: "b", hidden: false, order: 1 }, { id: "c", hidden: true, order: 0 }] })).toEqual({ order: ["c", "b"], hidden: ["c"] });
    expect(layoutFromState(null)).toEqual({ order: [], hidden: [] });
    expect(layoutFromState({ widgets: "broken" })).toEqual({ order: [], hidden: [] });
    expect(layoutToState(widgets, { order: ["b"], hidden: ["c"] }).widgets).toEqual([
      { id: "b", hidden: false, order: 0 },
      { id: "a", hidden: false, order: 1 },
      { id: "c", hidden: true, order: 2 },
    ]);
    expect(isDefaultLayout(widgets, { order: [], hidden: [] })).toBe(true);
    expect(isDefaultLayout(widgets, { order: ["a", "b", "c"], hidden: [] })).toBe(true);
    expect(isDefaultLayout(widgets, { order: ["b"], hidden: [] })).toBe(false);
    expect(isDefaultLayout(widgets, { order: [], hidden: ["a"] })).toBe(false);
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
          branch({ id: 4, name: "Olmazor", code: "OLM", opens_at: "07:30", status: "not_opened" }),
        ]),
    });
    const app = await testApp("/c/1");
    const { wrapper } = mountWithProviders(BranchesWidget, { plugins: app.plugins, props: { companyId: 1 } });
    await flushPromises();
    const cards = wrapper.findAll("li");
    expect(cards).toHaveLength(4);
    expect(cards[0]!.text()).toContain("Opened 08:57 by Dilnoza");
    expect(cards[0]!.text()).toContain("6/7");
    expect(cards[0]!.text()).toContain("1 late");
    expect(cards[1]!.text()).toContain("Not opened · 12m late");
    // Hours read as hours: "2h 42m late", not "+162 min".
    expect(cards[3]!.text()).toContain("Not opened · 2h 42m late");
    expect(cards[1]!.text()).toContain(en["overview.branches.noFacts"]);
    expect(cards[2]!.text()).toContain("Day off");
    expect(wrapper.text()).toContain("1 of 4 open");
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
