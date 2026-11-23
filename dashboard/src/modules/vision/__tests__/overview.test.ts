/**
 * The overview's null and edge values (docs/KOZ.md §6.1): no entrance camera, the sales module
 * off, more receipts than visitors, a day with no visitors, empty hours at the edges, nothing to
 * compare with; and a company without boxes gets the page that leads to pairing.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import "@/core/modules";
import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { bySeverity, comparedLeft, conversionPercent, conversionPoints, hourRange, missingReason, needsSetup, peakHour, percentChange, trimHours, waitHeat } from "../lib/overview";
import en from "../i18n/en.json";
import OverviewPage from "../pages/OverviewPage.vue";
import { DEFAULT_RULES } from "../lib/rules";
import type { HourRow, Overview, Totals } from "../types";

const hour = (h: number, visitors: number | null, receipts: number | null = 0, extra: Partial<HourRow> = {}): HourRow => ({
  hour: h,
  visitors,
  receipts,
  queue_max: 0,
  wait_max_s: 0,
  staff_avg: 0,
  staff_checked_in: 0,
  unattended_minutes: 0,
  ...extra,
});

const totals = (extra: Partial<Totals> = {}): Totals => ({
  visitors: 412,
  receipts: 267,
  conversion: 0.648,
  conversion_note: null,
  left: 145,
  wait_avg_s: 38,
  wait_max_s: 260,
  alerts: 6,
  unattended_minutes: 14,
  compare: { visitors: 380, receipts: 251, conversion: 0.661, label: "same_weekday_last_week" },
  ...extra,
});

function overview(extra: Partial<Overview> = {}): Overview {
  return {
    day: "2026-11-23",
    branch: null,
    setup: { agents: 1, cameras: 4, entrance: true, counter: true },
    agents: [{ id: 4, name: "Asosiy qutisi", branch_id: 1, online: true, last_seen_at: "2026-11-23T16:30:00Z", version: "0.1.0" }],
    totals: totals(),
    hours: Array.from({ length: 24 }, (_, h) => hour(h, h >= 9 && h <= 20 ? 30 : 0, h >= 9 && h <= 20 ? 20 : 0)),
    insights: [],
    open_alerts: [],
    ...extra,
  };
}

describe("the numbers", () => {
  it("trims the empty hours before opening and after closing, and keeps gaps inside", () => {
    const hours = [hour(7, 0), hour(8, 0), hour(9, 12), hour(10, 0), hour(11, 5), hour(12, 0, 0), hour(23, 0)];
    expect(trimHours(hours).map((row) => row.hour)).toEqual([9, 10, 11]);
    // An hour with only staff in it still counts as open.
    expect(trimHours([hour(8, 0, 0, { staff_checked_in: 2 }), hour(9, 3)]).map((row) => row.hour)).toEqual([8, 9]);
    expect(trimHours([hour(8, 0), hour(9, null, null)])).toEqual([]);
    expect(trimHours([])).toEqual([]);
  });

  it("compares only with something to compare with", () => {
    expect(percentChange(110, 100)).toBeCloseTo(10);
    expect(percentChange(90, 100)).toBeCloseTo(-10);
    expect(percentChange(5, 0)).toBeNull();
    expect(percentChange(null, 100)).toBeNull();
    expect(percentChange(100, null)).toBeNull();
  });

  it("gives conversion in percent and its change in points", () => {
    expect(conversionPercent(0.648)).toBeCloseTo(64.8);
    expect(conversionPercent(null)).toBeNull();
    expect(conversionPoints(totals())).toBeCloseTo(-1.3);
    expect(conversionPoints(totals({ conversion: null }))).toBeNull();
    expect(conversionPoints(totals({ compare: null }))).toBeNull();
    expect(conversionPoints(totals({ compare: { visitors: 0, receipts: 0, conversion: null, label: "same_weekday_last_week" } }))).toBeNull();
  });

  it("works out who left without buying on the comparison day, never below zero", () => {
    expect(comparedLeft(totals())).toBe(129);
    expect(comparedLeft(totals({ compare: { visitors: 10, receipts: 14, conversion: null, label: "x" } }))).toBe(0);
    expect(comparedLeft(totals({ compare: { visitors: null, receipts: 4, conversion: null, label: "x" } }))).toBeNull();
  });

  it("says why a number is missing", () => {
    const setup = { agents: 1, cameras: 2, entrance: false, counter: true };
    const noEntrance = { setup, totals: totals({ visitors: null, conversion: null, left: null }) };
    expect(missingReason("visitors", noEntrance)).toBe("no_entrance");
    expect(missingReason("conversion", noEntrance)).toBe("no_entrance");
    expect(missingReason("left", noEntrance)).toBe("no_entrance");
    const noSales = { setup: { ...setup, entrance: true }, totals: totals({ receipts: null, conversion: null, left: null }) };
    expect(missingReason("receipts", noSales)).toBe("no_sales");
    expect(missingReason("conversion", noSales)).toBe("no_sales");
    expect(missingReason("left", noSales)).toBe("no_sales");
    const undercount = { setup: { ...setup, entrance: true }, totals: totals({ visitors: 80, receipts: 95, conversion: null, conversion_note: "entrance_undercount" }) };
    expect(missingReason("conversion", undercount)).toBe("undercount");
    const empty = { setup: { ...setup, entrance: true }, totals: totals({ visitors: 0, receipts: 0, conversion: null }) };
    expect(missingReason("conversion", empty)).toBe("no_visitors");
    expect(missingReason("wait", { setup: { ...setup, counter: false }, totals: totals({ wait_max_s: null }) })).toBe("no_counter");
    expect(missingReason("visitors", { setup: { ...setup, entrance: true }, totals: totals() })).toBeNull();
  });

  it("heats the wait against the rule, and finds the busiest hour", () => {
    expect([0, 30, 70, 110, 150, 260].map((s) => waitHeat(s, 120))).toEqual([0, 0, 1, 2, 3, 4]);
    expect(waitHeat(null, 120)).toBe(0);
    expect(peakHour([hour(9, 10), hour(18, 61), hour(19, 61)])?.hour).toBe(18);
    expect(peakHour([hour(9, 0)])).toBeNull();
    expect(hourRange(23)).toBe("23:00–00:00");
  });

  it("lists what hurts first, good news last", () => {
    const sorted = bySeverity([
      { severity: "good" as const, id: 1 },
      { severity: "warn" as const, id: 2 },
      { severity: "bad" as const, id: 3 },
      { severity: "warn" as const, id: 4 },
    ]);
    expect(sorted.map((item) => item.id)).toEqual([3, 2, 4, 1]);
  });

  it("knows a company without boxes", () => {
    expect(needsSetup(overview({ setup: { agents: 0, cameras: 0, entrance: false, counter: false } }))).toBe(true);
    expect(needsSetup(overview())).toBe(false);
    expect(needsSetup(null)).toBe(false);
  });
});

describe("the overview page", () => {
  let answer: Overview;

  beforeEach(() => {
    mergeModuleMessages("vision", { en });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        const url = String(input);
        if (url.includes("/vision/overview/")) return json(answer);
        if (url.includes("/vision/settings/")) return json(DEFAULT_RULES);
        return json({ detail: "Not found." }, 404);
      }),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  async function render() {
    const app = await testApp("/c/1/vision");
    const { wrapper } = mountWithProviders(OverviewPage, { plugins: app.plugins });
    await vi.waitFor(() => expect(wrapper.find("[data-headline], [data-pitch]").exists()).toBe(true), { timeout: 4000 });
    return wrapper;
  }

  it("shows a dash and the reason for every number it can't have, and what to set up", async () => {
    answer = overview({
      setup: { agents: 1, cameras: 2, entrance: false, counter: true },
      totals: totals({ visitors: null, conversion: null, left: null, compare: null, receipts: 120 }),
    });
    const wrapper = await render();
    const tile = (id: string) => wrapper.find(`[data-kpi="${id}"]`);
    expect(tile("visitors").text()).toContain("—");
    expect(tile("visitors").text()).toContain("No entrance camera");
    expect(tile("conversion").text()).toContain("No entrance camera");
    expect(tile("left").text()).toContain("—");
    expect(tile("receipts").text()).toContain("120");
    expect(wrapper.find('[data-setup="entrance"]').text()).toContain("Visitors need an entrance camera");
    expect(wrapper.find('[data-setup="counter"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("says when receipts outnumber visitors instead of showing a conversion over 100%", async () => {
    answer = overview({ totals: totals({ visitors: 80, receipts: 95, conversion: null, conversion_note: "entrance_undercount", left: 0 }) });
    const wrapper = await render();
    const conversion = wrapper.find('[data-kpi="conversion"]');
    expect(conversion.text()).toContain("—");
    expect(conversion.text()).toContain("More receipts than visitors");
    expect(conversion.text()).not.toContain("118");
    wrapper.unmount();
  });

  it("says when the sales module is off", async () => {
    answer = overview({ totals: totals({ receipts: null, conversion: null, left: null }) });
    const wrapper = await render();
    expect(wrapper.find('[data-kpi="receipts"]').text()).toContain("Sales module is off");
    wrapper.unmount();
  });

  it("sells Ko‘z to a company without boxes and leads to pairing", async () => {
    answer = overview({ setup: { agents: 0, cameras: 0, entrance: false, counter: false }, agents: [], totals: totals({ visitors: null, receipts: null, conversion: null, left: null }) });
    const wrapper = await render();
    expect(wrapper.find("[data-pitch]").exists()).toBe(true);
    expect(wrapper.find("[data-headline]").exists()).toBe(false);
    expect(wrapper.find('[data-pitch] a[href$="/vision/cameras?pair=1"]').exists()).toBe(true);
    wrapper.unmount();
  });
});
