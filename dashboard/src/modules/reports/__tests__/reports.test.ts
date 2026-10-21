// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { customValue } from "@/lib/dateRange";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { periodParams, reportsApi } from "../api";
import en from "../i18n/en.json";
import module from "../index";
import TeamReportPage from "../pages/TeamReportPage.vue";
import type { Score, TeamReport } from "../types";

// jsdom has no ResizeObserver, and the report's chart measures itself after a test can be done.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

interface Call {
  method: string;
  url: string;
}

function stub(routes: Record<string, (call: Call) => Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url: input };
      calls.push(call);
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      return routes[`${call.method} ${path}`]?.(call) ?? json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const score = (overrides: Partial<Score> = {}): Score => ({
  total: 10,
  done: 9,
  on_time: 8,
  late: 1,
  missed: 1,
  on_time_percent: 80,
  late_now: 0,
  reminders: 4,
  avg_delay_minutes: 35,
  ...overrides,
});

const report = (): TeamReport => ({
  range: { from: "2026-09-22", to: "2026-10-21" },
  compare: { from: "2026-08-23", to: "2026-09-21" },
  group_by: "member",
  totals: score({ total: 20, on_time: 15, on_time_percent: 75 }),
  previous: score(),
  series: [],
  breakdown: [
    { key: "11", label: "Nigora Azimova", member: { id: 11, name: "Nigora Azimova", photo_url: null, position: "Delivery" }, position: "Delivery", previous_on_time_percent: 90, ...score({ on_time_percent: 96 }) },
    { key: "12", label: "Jasur Tursunov", member: { id: 12, name: "Jasur Tursunov", photo_url: null, position: "Stock" }, position: "Stock", previous_on_time_percent: 50, ...score({ on_time_percent: 65, late_now: 5 }) },
  ],
});

beforeEach(() => {
  mergeModuleMessages("reports", { en, ru: en, uz: en });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("api", () => {
  it("sends a preset as a preset and a custom range as dates, with the comparison", () => {
    expect(periodParams({ preset: "this_month", range: { from: "2026-10-01", to: "2026-10-21" }, compare: "previous" } as never)).toEqual({ preset: "this_month", compare: "previous" });
    expect(periodParams(customValue({ from: "2026-10-01", to: "2026-10-10" }))).toEqual({ from: "2026-10-01", to: "2026-10-10" });
    expect(periodParams(customValue({ from: "2026-10-01", to: "2026-10-10" }, "year"))).toEqual({ from: "2026-10-01", to: "2026-10-10", compare: "year" });
  });

  it("reads the team and routine reports", async () => {
    const calls = stub({ "GET reports/team/": () => json(report()), "GET reports/routines/": () => json({}) });
    await reportsApi.team(1, { preset: "last_30", group_by: "routine", branch: ["1", "2"] });
    await reportsApi.routines(1, { from: "2026-10-01", to: "2026-10-21" });
    expect(calls.map((c) => c.url)).toEqual([
      "/api/v1/owner/companies/1/reports/team/?preset=last_30&group_by=routine&branch=1&branch=2",
      "/api/v1/owner/companies/1/reports/routines/?from=2026-10-01&to=2026-10-21",
    ]);
  });

  it("registers in Insights behind reports.view", () => {
    expect(module).toMatchObject({ id: "reports", group: "insights", order: 10, perm: "reports.view" });
  });
});

describe("TeamReportPage", () => {
  it("asks for the grouping in the URL and lists everyone with their on-time share", async () => {
    const calls = stub({ "GET reports/team/": () => json(report()) });
    const app = await testApp("/c/1");
    // The page's tabs link to the module's named routes.
    for (const name of ["reports.team", "reports.routines"]) app.router.addRoute({ name, path: `/c/:companyId/${name.replace(".", "/")}`, component: { render: () => null } });
    await app.router.push("/c/1/reports/team?group_by=member&preset=last_30&compare=previous");
    const { wrapper } = mountWithProviders(TeamReportPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const request = calls.find((c) => c.url.includes("/reports/team/"));
    expect(request?.url).toContain("group_by=member");
    const text = document.body.textContent ?? "";
    expect(text).toContain("Nigora Azimova");
    expect(text).toContain("Jasur Tursunov");
    expect(text).toContain("96%");
    wrapper.unmount();
  });

  it("stops the on-time line at yesterday: today's rate only counts what was due so far", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-21T10:00:00Z")); // 15:00 in Tashkent
    const day = (date: string, on_time_percent: number) => ({ date, total: 10, done: 10, on_time: on_time_percent / 10, late: 0, missed: 0, on_time_percent });
    stub({ "GET reports/team/": () => json({ ...report(), series: [day("2026-10-19", 90), day("2026-10-20", 80), day("2026-10-21", 10)] }) });
    const app = await testApp("/c/1");
    for (const name of ["reports.team", "reports.routines"]) app.router.addRoute({ name, path: `/c/:companyId/${name.replace(".", "/")}`, component: { render: () => null } });
    await app.router.push("/c/1/reports/team?preset=last_30");
    const { wrapper } = mountWithProviders(TeamReportPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    // The On time tile's sparkline: two points (the 19th and the 20th), not today's dip.
    const line = wrapper.find("svg path[stroke]").attributes("d") ?? "";
    expect(line.match(/[ML]/g)).toHaveLength(2);
    wrapper.unmount();
    vi.useRealTimers();
  });
});
