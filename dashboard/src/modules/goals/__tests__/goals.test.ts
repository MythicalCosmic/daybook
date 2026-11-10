// v11: business goals. The pure helpers (periods, order, counts, ring tones), the page (cards worst
// first with their numbers, the state counts, the owners' button), the drawer from `?goal=`, and the
// dialog (the first metric whose module is on, the preview, the suggested title, the body it sends).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { toasts } from "@/components/useToast";
import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { presetPeriod, ringTone, sortGoals, stateCounts, type Goal, type GoalList, type Metrics } from "../api";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import module from "../index";

vi.setConfig({ testTimeout: 20_000 });

interface Call {
  method: string;
  url: string;
  body: unknown;
}

const PREFIX = "/api/v1/owner/companies/1/goals/";

function stub(routes: Record<string, (call: Call) => Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const raw = init?.body;
      const body = raw ? JSON.parse(String(raw)) : undefined;
      const call = { method: init?.method ?? "GET", url: input, body };
      calls.push(call);
      const path = input.replace(PREFIX, "").split("?")[0]!;
      return routes[`${call.method} ${path}`]?.(call) ?? json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

beforeEach(() => {
  mergeModuleMessages("goals", { en, ru: en, uz: en });
  toasts.splice(0, toasts.length);
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

function goal(overrides: Partial<Goal> = {}): Goal {
  return {
    id: 1,
    title: "IV chorak tushumi: 1,6 mlrd so‘m",
    metric: "revenue",
    unit: "money",
    better: "up",
    kind: "sum",
    target: "1580000000.00",
    starts_on: "2026-10-01",
    ends_on: "2026-12-31",
    branch: null,
    owner: { id: 11, name: "Dilnoza Karimova" },
    note: "",
    status: "active",
    state: "on_track",
    value: "760390000.00",
    forecast: "1706240975.61",
    baseline: null,
    progress: "48.1",
    days_left: 51,
    time_share: "0.4457",
    available: true,
    series: [
      { on: "2026-10-05", value: "70000000.00", forecast: "1600000000.00", state: "on_track" },
      { on: "2026-11-02", value: "560000000.00", forecast: "1620000000.00", state: "on_track" },
      { on: "2026-11-10", value: "760390000.00", forecast: "1706240975.61", state: "on_track" },
    ],
    can_edit: true,
    ...overrides,
  };
}

const list = (goals: Goal[], canManage = true): GoalList => ({ today: "2026-11-10", currency: "UZS", can_manage: canManage, goals, counts: { active: goals.length, done: 1, archived: 0 } });

const metrics = (): Metrics => ({
  metrics: [
    { key: "revenue", label: "Revenue", hint: "", unit: "money", better: "up", kind: "sum", branchable: true, available: true, feature: "finance" },
    { key: "late_arrivals", label: "Late arrivals", hint: "", unit: "percent", better: "down", kind: "ratio", branchable: true, available: true, feature: "attendance" },
    { key: "training", label: "Training completed", hint: "", unit: "percent", better: "up", kind: "level", branchable: true, available: false, feature: "learning" },
  ],
  branches: [{ id: 1, name: "Chilonzor" }],
  people: [{ id: 11, name: "Dilnoza Karimova" }],
  company_wide: true,
});

describe("goals helpers", () => {
  it("knows the periods of each preset", () => {
    expect(presetPeriod("month", "2026-11-10")).toEqual({ starts_on: "2026-11-01", ends_on: "2026-11-30" });
    expect(presetPeriod("quarter", "2026-11-10")).toEqual({ starts_on: "2026-10-01", ends_on: "2026-12-31" });
    expect(presetPeriod("half", "2026-02-10")).toEqual({ starts_on: "2026-01-01", ends_on: "2026-06-30" });
    expect(presetPeriod("year", "2026-11-10")).toEqual({ starts_on: "2026-01-01", ends_on: "2026-12-31" });
    expect(presetPeriod("month", "2028-02-03").ends_on).toBe("2028-02-29");
  });

  it("puts the goals that need the owner first, and counts them", () => {
    const rows = [goal({ id: 1, state: "on_track" }), goal({ id: 2, state: "off_track" }), goal({ id: 3, state: "at_risk", ends_on: "2026-11-30" }), goal({ id: 4, state: "at_risk" })];
    expect(sortGoals(rows).map((row) => row.id)).toEqual([2, 3, 4, 1]);
    expect(stateCounts(rows)).toEqual([
      { state: "off_track", count: 1 },
      { state: "at_risk", count: 2 },
      { state: "on_track", count: 1 },
    ]);
    expect(ringTone({ state: "at_risk" })).toBe("warning");
    expect(ringTone({ state: "achieved" })).toBe("primary");
    expect(ringTone({ state: "no_data" })).toBe("info");
  });

  it("is registered in Money with its dictionaries in three languages", async () => {
    expect(module.group).toBe("money");
    expect(module.perm).toBe("reports.view");
    for (const dict of [en, ru, uz]) expect(Object.keys(dict).sort()).toEqual(Object.keys(en).sort());
    expect(uz["goals.title"]).toBe("Maqsadlar");
  });
});

describe("GoalsPage", () => {
  it("shows each goal's numbers, worst first, with the state counts", async () => {
    stub({
      "GET ": () =>
        json(
          list([
            goal(),
            goal({ id: 2, title: "Uchinchi dorixona: Sergeli", metric: "branches", unit: "count", kind: "level", target: "3.00", value: "2.00", forecast: "2.00", baseline: "2.00", progress: "0.0", state: "at_risk", series: [] }),
            goal({ id: 3, title: "Kechikishlar", metric: "late_arrivals", unit: "percent", better: "down", kind: "ratio", target: "3.00", value: "7.69", forecast: "7.69", progress: "39.0", state: "off_track", branch: { id: 1, name: "Chilonzor" } }),
          ]),
        ),
    });
    const app = await testApp("/c/1/goals");
    const Page = (await import("../pages/GoalsPage.vue")).default;
    mountWithProviders(Page, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();

    const cards = [...document.querySelectorAll("[data-goal]")];
    expect(cards.map((card) => card.getAttribute("data-state"))).toEqual(["off_track", "at_risk", "on_track"]);
    expect(cards[0]!.textContent).toContain("Chilonzor");
    expect(cards[0]!.textContent).toContain(en["goals.atMost"].replace("{target}", "3%"));
    expect(cards[2]!.textContent).toContain(en["goals.forecast"].split(":")[0]!);
    expect(document.querySelector("[data-state-counts]")?.textContent).toContain("1 off track");
    expect(document.querySelector("[data-new-goal]")).not.toBeNull();
  });

  it("hides the owners' button from someone who only sees goals, and shows an empty state", async () => {
    stub({ "GET ": () => json(list([], false)) });
    const app = await testApp("/c/1/goals");
    const Page = (await import("../pages/GoalsPage.vue")).default;
    mountWithProviders(Page, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(document.querySelector("[data-new-goal]")).toBeNull();
    expect(document.body.textContent).toContain(en["goals.emptyTitle"]);
  });
});

describe("GoalDialog", () => {
  it("picks the first metric that is on, previews it, suggests a title and sends the goal", async () => {
    const calls = stub({
      "GET metrics/": () => json(metrics()),
      "GET preview/": () => json({ metric: "revenue", state: "on_track", value: "760390000.00", forecast: "1706240975.61", baseline: null, progress: "48.1", days_left: 51 }),
      "POST ": () => json(goal(), 201),
    });
    const app = await testApp("/c/1/goals");
    const Dialog = (await import("../components/GoalDialog.vue")).default;
    mountWithProviders(Dialog, { plugins: app.plugins, props: { open: true, today: "2026-11-10" } });
    await flushPromises();
    await flushPromises();

    expect(document.querySelector('[data-metric="revenue"]')?.getAttribute("aria-checked")).toBe("true");
    expect(document.querySelector<HTMLButtonElement>('[data-metric="training"]')?.disabled).toBe(true);
    const target = document.querySelector<HTMLInputElement>("input[data-target]")!;
    target.value = "1500000000";
    target.dispatchEvent(new Event("input"));
    await new Promise((resolve) => setTimeout(resolve, 400));
    await flushPromises();
    await flushPromises();
    const preview = calls.filter((call) => call.url.includes("preview/")).at(-1);
    expect(preview?.url).toContain("metric=revenue");
    expect(preview?.url).toContain("starts_on=2026-10-01");
    expect(document.querySelector("[data-preview]")?.textContent).toContain(en["goals.state.on_track"]);
    const title = document.querySelector<HTMLInputElement>("input[data-title]")!;
    expect(title.value).toContain(en["goals.metric.revenue"]);

    document.querySelector<HTMLButtonElement>("[data-save]")!.click();
    await flushPromises();
    await flushPromises();
    const sent = calls.find((call) => call.method === "POST");
    expect(sent?.body).toMatchObject({ metric: "revenue", target: "1500000000.00", starts_on: "2026-10-01", ends_on: "2026-12-31", branch: null });
    expect(String((sent?.body as { title: string }).title)).toContain(en["goals.metric.revenue"]);
  });
});
