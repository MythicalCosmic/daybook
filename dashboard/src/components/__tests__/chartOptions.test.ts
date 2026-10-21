import { describe, expect, it } from "vitest";

import { cartesianOption, type CartesianInput } from "@/components/chartOptions";
import type { ChartTheme } from "@/components/useChartTheme";

const theme: ChartTheme = {
  text: "#201e1d",
  muted: "#6b6359",
  subtle: "#8e8579",
  border: "rgba(32,30,29,0.1)",
  surface: "#ffffff",
  surface2: "#f6f3ee",
  primary: "#c67139",
  success: "#2f7d4f",
  warning: "#b7791f",
  danger: "#c0392b",
  info: "#2b6cb0",
  series: ["#c67139", "#2b6cb0", "#2f7d4f"],
  compare: "#a39b90",
  fontFamily: "Figtree",
  dark: false,
};
const ctx = { lang: "en" as const, currency: "UZS" as const };
const days = ["2026-10-19", "2026-10-20", "2026-10-21"];

// ECharts options are loosely typed; the tests read them as plain objects.
type Option = Record<string, any>;
const build = (input: Partial<CartesianInput>, style: Parameters<typeof cartesianOption>[2] = { type: "line" }): Option =>
  cartesianOption(theme, { categories: days, series: [{ name: "On time", data: [80, 95, 100] }], ...input }, style, ctx) as Option;

describe("cartesianOption", () => {
  it("caps the value axis at yMax in four steps from zero", () => {
    expect(build({ yMax: 100, valueFormat: "percent" }).yAxis).toMatchObject({ min: 0, max: 100, interval: 25 });
    // Without it ECharts picks a "nice" ceiling (120 % for a 100 % peak).
    const free = build({ valueFormat: "percent" }).yAxis;
    expect(free.max).toBeUndefined();
    expect(free.interval).toBeUndefined();
    // Horizontal bars put the value axis on x.
    const sideways = build({ yMax: 40 }, { type: "bar", horizontal: true });
    expect(sideways.xAxis).toMatchObject({ type: "value", min: 0, max: 40, interval: 10 });
    expect(sideways.yAxis.type).toBe("category");
  });

  it("gives counts whole-number ticks", () => {
    expect(build({ integer: true }, { type: "bar", stacked: true }).yAxis.minInterval).toBe(1);
    expect(build({}).yAxis.minInterval).toBeUndefined();
  });

  it("names a target in the legend and the tooltip instead of on the plot", () => {
    const option = build({ target: { value: 90, label: "Goal" }, valueFormat: "percent" });
    const target = option.series.find((s: Option) => s.name === "Goal");
    expect(target).toMatchObject({ type: "line", data: [] });
    expect(target.markLine).toMatchObject({ silent: true, label: { show: false }, data: [{ yAxis: 90 }] });
    expect(option.series[0].markLine).toBeUndefined();
    // One series plus the target: the legend is on, the target with a dashed key.
    expect(option.legend.show).not.toBe(false);
    expect(option.legend.data).toEqual(["On time", { name: "Goal", icon: expect.stringMatching(/^path:\/\//) }]);
    const html: string = option.tooltip.formatter([{ dataIndex: 2, seriesIndex: 0, seriesName: "On time", color: "#c67139", value: 100 }]);
    expect(html).toContain("Goal");
    expect(html).toContain("90");
  });

  it("finishes an in-progress last point with a dashed segment and says so in the tooltip", () => {
    const option = build({ partial: { label: "so far" }, valueFormat: "percent", xFormat: "day" });
    // The solid line stops a point early; a helper of the same name dashes into a hollow dot.
    expect(option.series).toHaveLength(2);
    expect(option.series[0].data).toEqual([80, 95, null]);
    expect(option.series[1]).toMatchObject({ name: "On time", lineStyle: { type: [4, 4] }, tooltip: { show: false } });
    expect(option.series[1].data).toEqual([null, 95, { value: 100, symbol: "emptyCircle", symbolSize: 8 }]);
    // One row per series, with today's real value, titled "so far".
    const html: string = option.tooltip.formatter([{ dataIndex: 2, seriesIndex: 0, seriesName: "On time", color: "#c67139", value: null }]);
    expect(html).toContain("21 Oct · so far");
    expect(html.match(/On time/g)).toHaveLength(1);
    expect(html).toContain("100");
    // Bars and stacks have no in-progress look.
    expect(build({ partial: { label: "so far" } }, { type: "bar" }).series).toHaveLength(1);
  });

  it("draws an unnamed target as the line alone", () => {
    const option = build({ target: { value: 50 } });
    expect(option.series).toHaveLength(1);
    expect(option.series[0].markLine).toMatchObject({ label: { show: false }, data: [{ yAxis: 50 }] });
    expect(option.legend).toEqual({ show: false });
  });
});
