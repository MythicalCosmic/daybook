import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { barBox, dayCenter, dragDates, dragModeAt, isoWeek, pxToDays, PX_PER_DAY, ticks, timelineRange, type GanttRow } from "@/components/gantt";
import GanttTimeline from "@/components/GanttTimeline.vue";
import { mountWithProviders, testApp } from "@/test/plugins";

const rows: GanttRow[] = [
  {
    id: "p1",
    label: "Chilonzor opening",
    bars: [{ id: "b1", start: "2026-10-12", end: "2026-10-23", label: "Fit-out", progress: 60 }],
    milestones: [{ id: "m1", date: "2026-10-26", label: "Soft launch" }],
  },
  { id: "p2", label: "Website", bars: [{ id: "b2", start: "2026-11-02", end: "2026-11-30" }] },
];

describe("gantt math", () => {
  it("places a bar by its days, end day included", () => {
    expect(barBox({ start: "2026-10-12", end: "2026-10-23" }, "2026-10-05", "day")).toEqual({ left: 7 * 40, width: 12 * 40 });
    expect(barBox({ start: "2026-10-12", end: "2026-10-12" }, "2026-10-12", "week")).toEqual({ left: 0, width: PX_PER_DAY.week });
    // A bar whose end comes before its start still takes one day.
    expect(barBox({ start: "2026-10-12", end: "2026-10-10" }, "2026-10-12", "day").width).toBe(40);
    expect(dayCenter("2026-10-06", "2026-10-05", "day")).toBe(60);
  });

  it("turns a drag into whole days, symmetric around zero", () => {
    expect(pxToDays(59, "day")).toBe(1);
    expect(pxToDays(61, "day")).toBe(2);
    expect(pxToDays(-61, "day")).toBe(-2);
    expect(pxToDays(-19, "day")).toBe(-0);
    expect(pxToDays(5 * 16, "week")).toBe(5);
  });

  it("moves and resizes without making a bar shorter than a day", () => {
    const bar = { start: "2026-10-12", end: "2026-10-16" };
    expect(dragDates(bar, "move", 3)).toEqual({ start: "2026-10-15", end: "2026-10-19" });
    expect(dragDates(bar, "end", -2)).toEqual({ start: "2026-10-12", end: "2026-10-14" });
    expect(dragDates(bar, "end", -10)).toEqual({ start: "2026-10-12", end: "2026-10-12" });
    expect(dragDates(bar, "start", 9)).toEqual({ start: "2026-10-16", end: "2026-10-16" });
    expect(dragDates(bar, "start", -3)).toEqual({ start: "2026-10-09", end: "2026-10-16" });
  });

  it("grabs the edges of wide bars to resize and the middle to move", () => {
    expect(dragModeAt(3, 200)).toBe("start");
    expect(dragModeAt(197, 200)).toBe("end");
    expect(dragModeAt(100, 200)).toBe("move");
    expect(dragModeAt(3, 16)).toBe("move");
  });

  it("covers every bar, milestone and today, aligned to the zoom", () => {
    const week = timelineRange(rows, "2026-10-20", "week");
    expect(week.from <= "2026-10-12").toBe(true);
    expect(new Date(`${week.from}T00:00:00Z`).getUTCDay()).toBe(1);
    expect(week.to >= "2026-11-30").toBe(true);
    const month = timelineRange(rows, "2026-10-20", "month");
    expect(month.from.endsWith("-01")).toBe(true);
    expect(month.to).toBe("2026-12-31");
  });

  it("builds header ticks per zoom", () => {
    const range = { from: "2026-10-05", to: "2026-11-01" };
    const day = ticks(range, "day");
    expect(day.bottom).toHaveLength(28);
    expect(day.top.map((t) => t.day)).toEqual(["2026-10-01", "2026-11-01"]);
    expect(day.top[0]).toMatchObject({ left: 0, width: 27 * 40 });
    const week = ticks(range, "week");
    expect(week.bottom).toHaveLength(4);
    expect(week.bottom[1]).toMatchObject({ day: "2026-10-12", left: 7 * 16, width: 7 * 16 });
    const month = ticks({ from: "2026-10-01", to: "2027-02-28" }, "month");
    expect(month.top.map((t) => t.day)).toEqual(["2026-01-01", "2027-01-01"]);
    expect(month.bottom).toHaveLength(5);
  });

  it("numbers ISO weeks", () => {
    expect(isoWeek("2026-10-20")).toBe(43);
    expect(isoWeek("2026-01-01")).toBe(1);
    expect(isoWeek("2027-01-01")).toBe(53);
  });
});

describe("GanttTimeline", () => {
  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  it("moves the focused bar a day with the keyboard and changes its end with Shift", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: Date.UTC(2026, 9, 20, 6) });
    const app = await testApp("/c/1/projects/1");
    const { inner } = mountWithProviders(GanttTimeline, { props: { rows, zoom: "day" }, plugins: app.plugins });
    await flushPromises();
    const bar = inner.findAll("[role=button]").find((el) => el.attributes("aria-label")?.startsWith("Fit-out"))!;
    await bar.trigger("keydown", { key: "ArrowRight" });
    await bar.trigger("keydown", { key: "ArrowLeft", shiftKey: true });
    expect(inner.emitted("change")).toEqual([
      [{ rowId: "p1", barId: "b1", start: "2026-10-13", end: "2026-10-24", mode: "move" }],
      [{ rowId: "p1", barId: "b1", start: "2026-10-12", end: "2026-10-22", mode: "end" }],
    ]);
    await bar.trigger("keydown", { key: "Enter" });
    expect(inner.emitted("bar-click")).toHaveLength(1);
  });

  it("shows milestones and leaves read-only bars alone", async () => {
    const app = await testApp("/c/1/projects/roadmap");
    const { inner } = mountWithProviders(GanttTimeline, { props: { rows, editable: false }, plugins: app.plugins });
    await flushPromises();
    expect(inner.text()).toContain("Soft launch");
    const bar = inner.findAll("[role=button]").find((el) => el.attributes("aria-label")?.startsWith("Website"))!;
    await bar.trigger("keydown", { key: "ArrowRight" });
    expect(inner.emitted("change")).toBeUndefined();
  });
});
