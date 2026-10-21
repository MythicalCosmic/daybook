// The tasks module's Overview widgets: one-off work only (routines have their own tile), and
// today's half-done day never read as a fall.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import KpiCard from "@/components/KpiCard.vue";
import LineChart from "@/components/LineChart.vue";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

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
