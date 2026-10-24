// The tasks module's Overview widgets: one-off work only (routines have their own tile), and
// today's half-done day never read as a fall.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import KpiCard from "@/components/KpiCard.vue";
import LineChart from "@/components/LineChart.vue";
import { useSessionStore } from "@/stores/session";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import BranchesNowWidget from "../BranchesNowWidget.vue";
import DoneTodayWidget from "../DoneTodayWidget.vue";
import LateNowWidget from "../LateNowWidget.vue";
import OnTimeTrendWidget from "../OnTimeTrendWidget.vue";
import OnTimeWidget from "../OnTimeWidget.vue";

const summary = {
  today: "2026-10-21",
  done_today: 4,
  total_today: 6,
  late_now: 3,
  review: 2,
  open: 20,
  on_time_percent: 79,
  on_time_previous: 85.2,
  done_7d: 30,
  done_prev_7d: 32,
  series: [
    { date: "2026-10-19", on_time: 9, late: 3, missed: 0, total: 12, done: 12, on_time_percent: 75 },
    { date: "2026-10-20", on_time: 10, late: 1, missed: 2, total: 13, done: 11, on_time_percent: 76.9 },
    // Only what was due so far: not a real fall.
    { date: "2026-10-21", on_time: 1, late: 3, missed: 4, total: 8, done: 4, on_time_percent: 12.5 },
  ],
};

function stubSummary(body: unknown): string[] {
  const urls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      urls.push(String(url));
      return String(url).includes("/tasks/summary/") ? json(body) : json({ detail: "Not found." }, 404);
    }),
  );
  return urls;
}

const mounted: Array<{ unmount: () => void }> = [];
afterEach(() => {
  mounted.splice(0).forEach((wrapper) => wrapper.unmount());
  vi.unstubAllGlobals();
});

async function mountWidget(component: object) {
  const app = await testApp("/c/1");
  const { wrapper } = mountWithProviders(component, { plugins: app.plugins, props: { companyId: 1 } });
  mounted.push(wrapper);
  await flushPromises();
  return wrapper;
}

describe("tasks Overview widgets", () => {
  it("count one-off work only", async () => {
    const urls = stubSummary(summary);
    for (const widget of [DoneTodayWidget, LateNowWidget, OnTimeWidget, OnTimeTrendWidget]) await mountWidget(widget);
    const asked = urls.filter((url) => url.includes("/tasks/summary/"));
    expect(asked.length).toBeGreaterThan(0);
    for (const url of asked) expect(new URL(url, "http://x").searchParams.get("routines")).toBe("without");
  });

  it("leave today's half day out of the KPI sparkline and mark it 'so far' on the trend", async () => {
    stubSummary(summary);
    const tile = await mountWidget(OnTimeWidget);
    const chart = await mountWidget(OnTimeTrendWidget);
    // Under a loaded test run the answer can take a few more ticks than one flush.
    await vi.waitFor(() => expect(tile.findComponent(KpiCard).props("spark")).toEqual([75, 76.9]));
    await vi.waitFor(() => expect(chart.findComponent(LineChart).props("partial")).toEqual({ label: "so far" }));
  });

  it("have nothing in progress when the series ends before today", async () => {
    stubSummary({ ...summary, today: "2026-10-22" });
    const chart = await mountWidget(OnTimeTrendWidget);
    await vi.waitFor(() => expect(chart.findComponent(LineChart).exists()).toBe(true));
    expect(chart.findComponent(LineChart).props("partial")).toBeNull();
  });
});

describe("Branches now (R2 §3.19)", () => {
  it("shows each branch's day, late work, checks and answers waiting, each opening its list", async () => {
    const urls: string[] = [];
    const page = (count: number, results: unknown[] = []) => json({ count, next: null, previous: null, results });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        urls.push(String(url));
        const params = new URL(String(url), "http://x").searchParams;
        const first = params.get("branch") === "1";
        if (String(url).includes("/tasks/summary/")) return json({ ...summary, late_now: first ? 3 : 0 });
        if (params.get("blocked") === "true") return first ? page(1, [{ id: 5, blocker: { reason_code: "broken", note: "", at: "2026-10-21T08:00:00Z" } }]) : page(0);
        if (params.get("extension") === "true") return page(0);
        return json({ detail: "Not found." }, 404);
      }),
    );
    const app = await testApp("/c/1");
    useSessionStore().me = me([company({ branches: [{ id: 1, name: "Chilonzor", code: "CHL" }, { id: 2, name: "Yunusobod", code: "YUN" }] })]);
    const { wrapper } = mountWithProviders(BranchesNowWidget, { plugins: app.plugins, props: { companyId: 1 } });
    mounted.push(wrapper);
    await flushPromises();
    await vi.waitFor(() => expect(wrapper.findAll("[data-branch]")).toHaveLength(2));
    // All work counts here (routines too): no `routines=without`.
    for (const url of urls.filter((u) => u.includes("/tasks/summary/"))) expect(new URL(url, "http://x").searchParams.get("routines")).toBeNull();
    const chilonzor = wrapper.find("[data-branch='1']");
    expect(chilonzor.text()).toContain("Chilonzor");
    expect(chilonzor.text()).toContain("4/6");
    await vi.waitFor(() => expect(chilonzor.find("[data-stat=late]").text()).toContain("3"));
    expect(chilonzor.find("[data-stat=late]").attributes("href")).toContain("overdue=true");
    expect(chilonzor.find("[data-stat=late]").attributes("href")).toContain("branch=1");
    await vi.waitFor(() => expect(chilonzor.find("[data-stat=answers]").text()).toContain("1"));
    expect(chilonzor.find("[data-stat=answers]").attributes("href")).toContain("blocked=true");
    expect(wrapper.find("[data-branch='2'] [data-stat=late]").classes()).toContain("text-subtle");
  });
});
