// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { company, json, manager } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { actOnInsight, fetchCockpit, makeTask, withInsight, withoutDecision, type Cockpit, type CockpitBranch, type Insight, type PeriodFigures } from "../api";
import en from "../i18n/en.json";
import module from "../index";
import { decisionGroups, lowKind, marginPoints, profitChange, rankBranches, topCosts } from "../lib";
import CockpitPage from "../pages/CockpitPage.vue";

function figures(overrides: Partial<PeriodFigures> = {}): PeriodFigures {
  return {
    revenue: "100000000.00",
    goods: "70000000.00",
    gross: "30000000.00",
    gross_margin: "30.0",
    expense: "90000000.00",
    profit: "10000000.00",
    margin: "10.0",
    costs: [
      { key: "goods", name: "Medicines and goods", amount: "70000000.00", previous: "60000000.00" },
      { key: "rent", name: "Rent", amount: "15000000.00", previous: "15000000.00" },
      { key: "utilities", name: "Utilities", amount: "3000000.00" },
      { key: "repairs", name: "Repairs", amount: "2000000.00" },
    ],
    previous: { revenue: "90000000.00", gross: "30000000.00", gross_margin: "33.3", expense: "75000000.00", profit: "15000000.00", margin: "16.7" },
    missing: [],
    ...overrides,
  };
}

function branch(id: number, name: string, profit: string, state: "green" | "amber" | "red" = "green"): CockpitBranch {
  return {
    id,
    name,
    code: name.slice(0, 3).toUpperCase(),
    month: figures({ profit }),
    last_month: figures({ profit: "8000000.00" }),
    trend: [
      { month: "2026-08", profit: "5000000.00" },
      { month: "2026-09", profit: "9000000.00" },
      { month: "2026-10", profit: "8000000.00" },
    ],
    states: { month: { state, reasons: state === "green" ? [] : ["margin_down"] }, last_month: { state: "green", reasons: [] } },
  };
}

const insight = (overrides: Partial<Insight> = {}): Insight => ({
  id: 7,
  kind: "cash_low",
  domain: "finance",
  severity: "warning",
  status: "open",
  branch: null,
  subject: null,
  title: "Cash drops to 110 mln so‘m on 23.11",
  explanation: "On 23.11 the accounts hold 110 mln so‘m, 40 mln so‘m less than your buffer.",
  suggested_action: "Plan the payments of that week.",
  metrics: { value: "110000000.00", series: ["500", "300", "110", "200"] },
  window: { from: "2026-11-10", to: "2026-11-23" },
  detected_at: "2026-11-10T02:00:00Z",
  last_seen_at: "2026-11-10T02:00:00Z",
  acknowledged_at: null,
  task: null,
  ...overrides,
});

function cockpit(overrides: Partial<Cockpit> = {}): Cockpit {
  return {
    today: "2026-11-10",
    currency: "UZS",
    generated_at: "2026-11-10T03:05:00Z",
    can: { money: true, insights: true, settings: true },
    money: {
      periods: {
        month: { from: "2026-11-01", to: "2026-11-10", previous_from: "2026-10-01", previous_to: "2026-10-10" },
        last_month: { from: "2026-10-01", to: "2026-10-31", previous_from: "2026-09-01", previous_to: "2026-09-30" },
      },
      total: {
        month: figures({ profit: "12000000.00", missing: [{ key: "salaries", name: "Salaries", last_month: "98000000.00" }] }),
        last_month: figures(),
        trend: [],
      },
      branches: [branch(2, "Yunusobod", "1000000.00", "amber"), branch(1, "Chilonzor", "11000000.00")],
      unassigned: null,
    },
    cash: {
      currency: "UZS",
      now: "550000000.00",
      buffer: "150000000.00",
      buffer_source: "setting",
      daily_spend: "15000000.00",
      runway: { days: 36, basis: "spending", below_zero_on: null, horizon: 90 },
      low: {
        date: "2026-11-23",
        balance: "110000000.00",
        short_by: "0.00",
        under_buffer_by: "40000000.00",
        causes: [{ title: "Sergeli: opening stock", kind: "bill", date: "2026-11-23", amount: "422000000.00", overdue: false }],
      },
      end: "800000000.00",
      points: [
        { date: "2026-11-10", balance: "550000000.00" },
        { date: "2026-11-23", balance: "110000000.00" },
      ],
    },
    decisions: {
      total: 2,
      sources: [
        { key: "finance.claims", group: "expense", label: "Expense claims", count: 1 },
        { key: "timeoff.request", group: "time_off", label: "Time off", count: 1 },
        { key: "members.join", group: "people", label: "Join requests", count: 0 },
      ],
      items: [
        {
          kind: "finance.claims",
          id: 5,
          title: "Madina · 1 850 000 so‘m · Repairs",
          subtitle: "My own money",
          created_at: "2026-11-09T10:00:00Z",
          url: "/c/1/finance/claims?claim=5",
          source: "finance.claims",
          group: "expense",
          actions: [
            { key: "approve", label: "Approve", style: "primary", method: "POST", endpoint: "finance/claims/5/approve/", body: {}, needs_reason: false },
            { key: "reject", label: "Reject", style: "danger", method: "POST", endpoint: "finance/claims/5/reject/", body: {}, needs_reason: true },
          ],
        },
        {
          kind: "timeoff.request",
          id: 9,
          title: "Kamola asks for time off",
          subtitle: "13.11 · 1 days",
          created_at: "2026-11-09T11:00:00Z",
          url: "time-off?request=9",
          source: "timeoff.request",
          group: "time_off",
          actions: [{ key: "approve", label: "Approve", style: "primary", method: "POST", endpoint: "time-off/9/approve/", body: {}, needs_reason: false }],
        },
      ],
    },
    insights: { live: 2, open: 1, critical: 0, items: [insight(), insight({ id: 8, status: "acknowledged", title: "Supplier bills overdue: 10,1 mln so‘m", metrics: {} })] },
    ...overrides,
  };
}

interface Call {
  url: string;
  method: string;
  body: unknown;
}

function stub(routes: Record<string, (call: Call) => Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call = { url: input, method: init?.method ?? "GET", body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      return routes[`${call.method} ${path}`]?.(call) ?? routes[path]?.(call) ?? json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const mounted: Array<{ unmount: () => void }> = [];

beforeEach(() => {
  mergeModuleMessages("cockpit", { en, ru: en, uz: en });
});

afterEach(() => {
  mounted.splice(0).forEach((wrapper) => wrapper.unmount());
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

/** The server's cockpit as it stands: an action changes what the next read returns. */
const server: { data: Cockpit | null } = { data: null };

async function mountPage(data: Cockpit, routes: Record<string, (call: Call) => Response> = {}, path = "/c/1/owner") {
  server.data = data;
  const calls = stub({ "cockpit/": () => json(server.data), ...routes });
  const app = await testApp(path);
  const result = mountWithProviders(CockpitPage, { plugins: app.plugins });
  mounted.push(result.wrapper);
  await flushPromises();
  return { ...result, calls, app };
}

describe("registration", () => {
  it("is first in the sidebar and an owner's landing page", () => {
    expect(module).toMatchObject({ id: "cockpit", group: "overview", order: 5, hotkey: "e", perm: ["finance.view", "reports.view"] });
    expect(module.routes[0]).toMatchObject({ path: "owner", name: "cockpit.owner", meta: { ownerLanding: true } });
    expect(module.settings?.[0]).toMatchObject({ id: "insights", perm: ["ai.configure", "company.settings"] });
    expect(module.deepLinks?.owner?.("")).toBe("owner");
  });
});

describe("rules", () => {
  it("ranks branches by the period's profit", () => {
    const data = cockpit();
    expect(rankBranches(data.money!.branches, "month").map((b) => b.name)).toEqual(["Chilonzor", "Yunusobod"]);
  });

  it("compares profit and margin with the period before", () => {
    const now = figures();
    expect(profitChange(now)).toBe(-33.3);
    expect(marginPoints(now)).toBe(-6.7);
    expect(profitChange(figures({ previous: { ...now.previous!, profit: "-1000.00" } }))).toBeNull();
    expect(marginPoints(figures({ margin: null }))).toBeNull();
  });

  it("keeps the three biggest costs and sums the rest", () => {
    const costs = topCosts(figures(), 2);
    expect(costs.map((cost) => cost.key)).toEqual(["goods", "rent", "_other"]);
    expect(costs[2]!.amount).toBe("5000000.00");
    expect(Math.round(costs[0]!.share)).toBe(78);
  });

  it("names the low point: short, under the buffer or fine", () => {
    const cash = cockpit().cash!;
    expect(lowKind(cash)).toBe("under");
    expect(lowKind({ ...cash, low: { ...cash.low, short_by: "5.00" } })).toBe("short");
    expect(lowKind({ ...cash, low: { ...cash.low, under_buffer_by: "0.00" } })).toBe("fine");
  });

  it("groups the decisions with something waiting", () => {
    expect(decisionGroups(cockpit().decisions)).toEqual([
      { group: "expense", count: 1, sources: ["finance.claims"] },
      { group: "time_off", count: 1, sources: ["timeoff.request"] },
    ]);
  });

  it("drops a decided item and updates an insight in place", () => {
    const data = cockpit();
    const after = withoutDecision(data, { kind: "finance.claims", id: 5 });
    expect(after.decisions.total).toBe(1);
    expect(after.decisions.items.map((item) => item.id)).toEqual([9]);
    expect(after.decisions.sources[0]!.count).toBe(0);
    const seen = withInsight(data, insight({ status: "acknowledged" }));
    expect(seen.insights.open).toBe(0);
    expect(seen.insights.items[0]!.status).toBe("acknowledged");
    const gone = withInsight(data, insight({ status: "dismissed" }));
    expect(gone.insights.items.map((item) => item.id)).toEqual([8]);
    expect(gone.insights.live).toBe(1);
  });
});

describe("api", () => {
  it("reads the cockpit and acts on insights at their endpoints", async () => {
    const calls = stub({
      "cockpit/": () => json(cockpit()),
      "POST insights/7/dismiss/": () => json(insight({ status: "dismissed" })),
      "POST insights/7/make-task/": () => json({ insight: insight(), task: { id: 3, title: "x", status: "todo" } }),
    });
    await fetchCockpit(1);
    await actOnInsight(1, 7, "dismiss", "Agreed");
    await makeTask(1, 7, { title: "Call them" });
    expect(calls.map((call) => `${call.method} ${call.url}`)).toEqual([
      "GET /api/v1/owner/companies/1/cockpit/",
      "POST /api/v1/owner/companies/1/insights/7/dismiss/",
      "POST /api/v1/owner/companies/1/insights/7/make-task/",
    ]);
    expect(calls[1]!.body).toEqual({ reason: "Agreed" });
    expect(calls[2]!.body).toEqual({ title: "Call them" });
  });
});

describe("the page", () => {
  it("shows the headline, the branches ranked, the low point, the decisions and the insights", async () => {
    const { wrapper } = await mountPage(cockpit());
    const text = wrapper.text();
    expect(text).toContain(en["cockpit.kpi.profit"]);
    expect(text).toContain(en["cockpit.kpi.runway"]);
    expect(wrapper.findAll("[data-branch]").map((card) => card.attributes("aria-label"))).toEqual(["Chilonzor", "Yunusobod"]);
    expect(wrapper.find('[data-branch="2"]').attributes("data-state")).toBe("amber");
    expect(wrapper.find("[data-missing]").text()).toContain("Salaries");
    expect(wrapper.find("[data-low]").text()).toContain("under your buffer");
    expect(wrapper.find("[data-cause]").text()).toContain("Sergeli: opening stock");
    expect(wrapper.findAll("[data-decision]")).toHaveLength(2);
    expect(wrapper.findAll("[data-insight]")).toHaveLength(2);
    expect(wrapper.find('[data-insight="8"]').attributes("data-status")).toBe("acknowledged");
  });

  it("approves in one tap through the endpoint the module gave the item", async () => {
    const { wrapper, calls } = await mountPage(cockpit(), {
      "POST finance/claims/5/approve/": () => {
        server.data = withoutDecision(server.data!, { kind: "finance.claims", id: 5 });
        return json({ id: 5, status: "approved" });
      },
    });
    await wrapper.find('[data-decision="finance.claims:5"] [data-action="approve"]').trigger("click");
    await flushPromises();
    const post = calls.find((call) => call.method === "POST");
    expect(post?.url).toBe("/api/v1/owner/companies/1/finance/claims/5/approve/");
    expect(wrapper.find('[data-decision="finance.claims:5"]').exists()).toBe(false);
  });

  it("marks an insight seen", async () => {
    const { wrapper, calls } = await mountPage(cockpit(), {
      "POST insights/7/acknowledge/": () => {
        const seen = insight({ status: "acknowledged" });
        server.data = withInsight(server.data!, seen);
        return json(seen);
      },
    });
    await wrapper.find('[data-insight="7"] [data-act="seen"]').trigger("click");
    await flushPromises();
    expect(calls.some((call) => call.method === "POST" && call.url.endsWith("/insights/7/acknowledge/"))).toBe(true);
    expect(wrapper.find('[data-insight="7"]').attributes("data-status")).toBe("acknowledged");
  });

  it("makes a task of an insight", async () => {
    const { wrapper, calls } = await mountPage(cockpit(), {
      "POST insights/7/make-task/": () => {
        const task = { id: 31, title: "Plan the payments", status: "todo" };
        const changed = insight({ status: "acknowledged", task });
        server.data = withInsight(server.data!, changed);
        return json({ insight: changed, task });
      },
    });
    await wrapper.find('[data-insight="7"] [data-act="task"]').trigger("click");
    await flushPromises();
    expect(calls.some((call) => call.url.endsWith("/insights/7/make-task/"))).toBe(true);
    expect(wrapper.find('[data-insight="7"] [data-act="open-task"]').attributes("href")).toContain("/c/1/tasks?task=31");
  });

  it("shows no money to someone without finance", async () => {
    const data = cockpit({ can: { money: false, insights: true, settings: false } });
    delete data.money;
    delete data.cash;
    const { wrapper } = await mountPage(data);
    expect(wrapper.find("[data-no-money]").exists()).toBe(true);
    expect(wrapper.find("[data-branches]").exists()).toBe(false);
    expect(wrapper.find("[data-runway]").exists()).toBe(false);
    expect(wrapper.find("[data-check]").exists()).toBe(false);
    expect(wrapper.findAll("[data-decision]")).toHaveLength(2);
  });

  it("says when nothing waits and all is quiet", async () => {
    const data = cockpit({ decisions: { total: 0, sources: [], items: [] }, insights: { live: 0, open: 0, critical: 0, items: [] } });
    const { wrapper } = await mountPage(data);
    expect(wrapper.text()).toContain(en["cockpit.decisions.empty"]);
    expect(wrapper.text()).toContain(en["cockpit.insights.empty"]);
  });

  it("shows the error with a retry", async () => {
    stub({ "cockpit/": () => json({ detail: "Boom" }, 500) });
    const app = await testApp("/c/1/owner");
    const result = mountWithProviders(CockpitPage, { plugins: app.plugins });
    mounted.push(result.wrapper);
    await flushPromises();
    await flushPromises();
    expect(result.wrapper.text()).toContain(en["cockpit.error"]);
  });
});

describe("who sees it", () => {
  it("is in the sidebar for a finance or reports holder, not for a plain employee", async () => {
    const { buildNav } = await import("@/core/nav");
    const { modules } = await import("@/core/modules");
    const reader = manager(["dashboard.access", "reports.view"]);
    const clerk = manager(["dashboard.access", "tasks.view_all"]);
    const first = (who: ReturnType<typeof manager>) => buildNav(modules, who)[0]?.modules[0]?.moduleId;
    expect(first(company())).toBe("cockpit");
    expect(first(reader)).toBe("cockpit");
    expect(first(clerk)).not.toBe("cockpit");
  });
});
