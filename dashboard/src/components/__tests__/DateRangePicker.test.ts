import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { orderedRange, pickRangeDay, previewRange, monthGrid, keyTarget } from "@/components/calendar";
import DateRangePicker from "@/components/DateRangePicker.vue";
import { compareOf, customValue, rangeParams, rangeValue, resolveRange, type DateRangeValue } from "@/lib/dateRange";
import { parseRangeQuery, rangeQueryPatch } from "@/lib/useRangeState";
import { mountWithProviders, testApp } from "@/test/plugins";

const TZ = "Asia/Tashkent";
// Tuesday 20 October 2026, 10:00 in Tashkent.
const NOW = Date.UTC(2026, 9, 20, 5, 0);

describe("range values", () => {
  it("resolves presets in the company timezone and keeps custom ranges", () => {
    expect(rangeValue("month", TZ, "prev", NOW)).toEqual({ preset: "month", range: { from: "2026-10-01", to: "2026-10-20" }, compare: "prev" });
    const stale: DateRangeValue = { preset: "month", range: { from: "2026-09-01", to: "2026-09-12" }, compare: "none" };
    expect(resolveRange(stale, TZ, NOW).range).toEqual({ from: "2026-10-01", to: "2026-10-20" });
    const custom = customValue({ from: "2026-08-03", to: "2026-08-09" });
    expect(resolveRange(custom, TZ, NOW)).toBe(custom);
  });

  it("compares month presets with the same days of the previous month, and a year back", () => {
    expect(compareOf(rangeValue("month", TZ, "prev", NOW))).toEqual({ from: "2026-09-01", to: "2026-09-20" });
    expect(compareOf(rangeValue("last_30", TZ, "prev", NOW))).toEqual({ from: "2026-08-22", to: "2026-09-20" });
    expect(compareOf(rangeValue("week", TZ, "year", NOW))).toEqual({ from: "2025-10-19", to: "2025-10-20" });
    expect(compareOf(rangeValue("week", TZ, "none", NOW))).toBeNull();
  });

  it("sends from, to and the compare mode to the API", () => {
    // A preset goes as itself: the server then compares 1–20 October with 1–20 September, as the
    // picker says, not with the 20 days just before (a custom range's rule).
    expect(rangeParams(rangeValue("month", TZ, "prev", NOW))).toEqual({ preset: "month", compare: "prev" });
    expect(compareOf(rangeValue("month", TZ, "prev", NOW))).toEqual({ from: "2026-09-01", to: "2026-09-20" });
    expect(rangeParams(rangeValue("last_30", TZ, "none", NOW))).toEqual({ preset: "last_30" });
    expect(rangeParams(customValue({ from: "2026-10-01", to: "2026-10-05" }))).toEqual({ from: "2026-10-01", to: "2026-10-05" });
    expect(rangeParams(customValue({ from: "2026-10-01", to: "2026-10-05" }, "year"))).toEqual({ from: "2026-10-01", to: "2026-10-05", compare: "year" });
  });

  it("round-trips through the URL, leaving defaults out", () => {
    const fallback = { preset: "month" as const, compare: "prev" as const };
    expect(rangeQueryPatch(rangeValue("month", TZ, "prev", NOW), fallback)).toEqual({ preset: undefined, from: undefined, to: undefined, compare: undefined });
    const custom = customValue({ from: "2026-10-02", to: "2026-10-09" }, "year");
    const patch = rangeQueryPatch(custom, fallback);
    expect(patch).toEqual({ preset: "custom", from: "2026-10-02", to: "2026-10-09", compare: "year" });
    expect(parseRangeQuery(patch as Record<string, string>, fallback, TZ, "", NOW)).toEqual(custom);
    // Junk falls back to the default; reversed custom days are put in order.
    expect(parseRangeQuery({ preset: "nonsense" }, fallback, TZ, "", NOW).preset).toBe("month");
    expect(parseRangeQuery({ preset: "custom", from: "2026-10-09", to: "2026-10-02" }, fallback, TZ, "", NOW).range).toEqual({ from: "2026-10-02", to: "2026-10-09" });
  });
});

describe("calendar helpers", () => {
  it("builds six Monday-first weeks", () => {
    const grid = monthGrid("2026-10");
    expect(grid).toHaveLength(6);
    expect(grid[0]![0]).toBe("2026-09-28");
    expect(grid.flat()).toContain("2026-10-31");
  });

  it("picks a range with two clicks in either order and previews while hovering", () => {
    let draft = pickRangeDay({ anchor: null, range: null }, "2026-10-15");
    expect(previewRange(draft, "2026-10-10")).toEqual({ from: "2026-10-10", to: "2026-10-15" });
    draft = pickRangeDay(draft, "2026-10-10");
    expect(draft).toEqual({ anchor: null, range: orderedRange("2026-10-10", "2026-10-15") });
  });

  it("moves keyboard focus by day, week, month and week edge", () => {
    expect(keyTarget("2026-10-20", "ArrowRight")).toBe("2026-10-21");
    expect(keyTarget("2026-10-20", "ArrowUp")).toBe("2026-10-13");
    expect(keyTarget("2026-01-31", "PageDown")).toBe("2026-02-28");
    expect(keyTarget("2026-10-22", "Home")).toBe("2026-10-19");
    expect(keyTarget("2026-10-22", "End")).toBe("2026-10-25");
    expect(keyTarget("2026-10-22", "x")).toBeNull();
  });
});

describe("DateRangePicker", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"], now: NOW });
  });
  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  async function open(value: DateRangeValue) {
    const app = await testApp("/c/1/sales");
    const { inner } = mountWithProviders(DateRangePicker, { props: { modelValue: value }, plugins: app.plugins });
    await inner.get("button").trigger("click");
    await flushPromises();
    return inner;
  }

  const button = (text: string) => [...document.body.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent?.trim() === text);

  it("shows the preset and its comparison on the trigger", async () => {
    const app = await testApp("/c/1/sales");
    const { inner } = mountWithProviders(DateRangePicker, { props: { modelValue: rangeValue("month", TZ, "prev", NOW) }, plugins: app.plugins });
    expect(inner.text()).toContain("This month");
    expect(inner.text()).toContain("1–20 Oct 2026");
    // en-GB writes September as "Sept".
    expect(inner.text()).toMatch(/vs 1–20 Sept? 2026/);
  });

  it("applies a preset at once, keeping the comparison", async () => {
    const picker = await open(rangeValue("month", TZ, "prev", NOW));
    button("Last month")!.click();
    await flushPromises();
    expect(picker.emitted("update:modelValue")?.at(-1)).toEqual([{ preset: "last_month", range: { from: "2026-09-01", to: "2026-09-30" }, compare: "prev" }]);
  });

  it("picks a custom range with two clicks and Apply", async () => {
    const picker = await open(rangeValue("month", TZ, "none", NOW));
    const day = (iso: string) => document.body.querySelectorAll<HTMLButtonElement>(`[data-day="${iso}"]`)[0]!;
    day("2026-10-14").click();
    await flushPromises();
    day("2026-10-05").click();
    await flushPromises();
    button("Last year")!.click();
    await flushPromises();
    button("Apply")!.click();
    await flushPromises();
    expect(picker.emitted("update:modelValue")?.at(-1)).toEqual([{ preset: "custom", range: { from: "2026-10-05", to: "2026-10-14" }, compare: "year" }]);
  });

  it("does not allow days after today by default", async () => {
    await open(rangeValue("month", TZ, "none", NOW));
    const future = document.body.querySelector<HTMLButtonElement>('[data-day="2026-10-25"]')!;
    expect(future.disabled).toBe(true);
  });
});
