/**
 * The overview's hour chart (docs/KOZ.md §6.1) as one ECharts option: visitors as bars and
 * receipts as a line on top, then two thin strips on the same hours: the longest wait as heat
 * (calm → too long against the queue rule) and who stood at the counter against who was checked
 * in (a gap shows in amber). One tooltip tells the whole hour. Colours come from the theme.
 */
import { escapeHtml, tooltipStyle, axisStyle, CHART_TYPE, type ChartTheme } from "@/components/useChartTheme";
import { withAlpha } from "@/components/chartOptions";

import type { HourRow } from "../types";
import { hourLabel, hourRange, waitHeat } from "./overview";

export interface HourChartText {
  visitors: string;
  receipts: string;
  left: string;
  conversion: string;
  queue: string;
  wait: string;
  waitRow: string;
  staffRow: string;
  atCounter: string;
  onShift: string;
  unattended: string;
  partial: string;
  number: (value: number, decimals?: number) => string;
  percent: (value: number) => string;
  seconds: (value: number) => string;
  minutes: (value: number) => string;
}

export interface HourChartInput {
  hours: HourRow[];
  queueWaitS: number;
  /** The hour still in progress (today's current hour), or null. */
  partialHour: number | null;
  /** Narrow (a phone): fewer labels, no numbers in the strips. */
  narrow: boolean;
}

const HEAT_ALPHA = [0.12, 0.35, 0.6, 0.82, 1] as const;

export function hourChartOption(theme: ChartTheme, input: HourChartInput, text: HourChartText): Record<string, unknown> {
  const { hours } = input;
  const labels = hours.map((row) => String(row.hour).padStart(2, "0"));
  const visitorColor = theme.series[0]!;
  const receiptColor = theme.dark ? "#f3ece1" : "#3b342d";
  const left = input.narrow ? 46 : 74;
  const right = 10;
  const heatColor = (level: number) => (level === 0 ? withAlpha(theme.success, theme.dark ? 0.22 : 0.18) : level <= 2 ? withAlpha(theme.warning, HEAT_ALPHA[level]!) : withAlpha(theme.danger, HEAT_ALPHA[level]!));
  /**
   * Who stood at the counter: red when customers waited with nobody there, amber when people were
   * checked in but not at the counter while the wait was long (the staff gap), calm otherwise.
   * Being checked in and elsewhere is normal on a quiet hour, so it isn't coloured then.
   */
  const staffColor = (row: HourRow) => {
    if (!row.staff_checked_in && !row.staff_avg) return withAlpha(theme.text, theme.dark ? 0.06 : 0.05);
    if ((row.unattended_minutes ?? 0) > 0) return withAlpha(theme.danger, 0.55);
    const gap = (row.staff_checked_in ?? 0) - (row.staff_avg ?? 0);
    if (gap >= 1 && waitHeat(row.wait_max_s, input.queueWaitS) >= 2) return withAlpha(theme.warning, 0.6);
    return withAlpha(theme.success, theme.dark ? 0.26 : 0.18);
  };
  const axes = axisStyle(theme);
  const category = (gridIndex: number, show: boolean) => ({
    type: "category",
    gridIndex,
    data: labels,
    boundaryGap: true,
    axisTick: { show: false },
    axisLine: { show: show, lineStyle: { color: theme.border } },
    axisLabel: show ? { ...axes.axisLabel, interval: input.narrow ? 1 : 0, margin: 8 } : { show: false },
    splitLine: { show: false },
    axisPointer: { type: "shadow", shadowStyle: { color: withAlpha(theme.text, theme.dark ? 0.07 : 0.045) } },
  });
  // A strip is one row of cells: a value axis from 0 to 1 that shows only its name, on the left.
  const rowAxis = (gridIndex: number, name: string) => ({
    type: "value",
    gridIndex,
    min: 0,
    max: 1,
    show: true,
    axisTick: { show: false },
    axisLine: { show: false },
    axisLabel: { show: false },
    splitLine: { show: false },
    name,
    nameLocation: "middle",
    nameRotate: 0,
    nameGap: 8,
    nameTextStyle: { color: theme.muted, fontFamily: theme.fontFamily, fontSize: CHART_TYPE.axis, align: "right", verticalAlign: "middle", width: left - 12, overflow: "truncate" },
  });
  const strip = (grid: number, data: Array<{ value: number; itemStyle: { color: string; borderRadius: number }; label?: unknown }>) => ({
    type: "bar",
    xAxisIndex: grid,
    yAxisIndex: grid,
    data,
    barWidth: "86%",
    silent: false,
    animationDuration: 300,
    emphasis: { disabled: true },
    label: { show: !input.narrow, position: "inside", color: theme.text, fontFamily: theme.fontFamily, fontSize: 10, fontWeight: 600 },
  });

  return {
    animation: true,
    animationDuration: 420,
    animationEasing: "cubicOut",
    textStyle: { fontFamily: theme.fontFamily },
    // The legend's swatches take these (the bars colour each hour themselves).
    color: [visitorColor, receiptColor],
    legend: {
      top: 0,
      left: left - 6,
      icon: "roundRect",
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 16,
      textStyle: { color: theme.muted, fontFamily: theme.fontFamily, fontSize: CHART_TYPE.label },
      data: [text.visitors, text.receipts],
    },
    grid: [
      { top: 34, left, right, bottom: input.narrow ? 112 : 104 },
      { left, right, height: 18, bottom: input.narrow ? 66 : 62 },
      { left, right, height: 18, bottom: input.narrow ? 40 : 36 },
    ],
    xAxis: [category(0, true), category(1, false), category(2, false)],
    yAxis: [
      { type: "value", gridIndex: 0, minInterval: 1, splitNumber: 3, ...axes, axisLabel: { ...axes.axisLabel, formatter: (value: number) => text.number(value) } },
      rowAxis(1, text.waitRow),
      rowAxis(2, text.staffRow),
    ],
    tooltip: {
      trigger: "axis",
      confine: true,
      ...tooltipStyle(theme),
      axisPointer: { type: "shadow", link: [{ xAxisIndex: "all" }] },
      formatter: (params: Array<{ dataIndex: number }>) => {
        const row = hours[params[0]?.dataIndex ?? -1];
        if (!row) return "";
        const visitors = row.visitors ?? 0;
        const receipts = row.receipts ?? 0;
        const lines: Array<[string, string, string?]> = [
          [text.visitors, text.number(visitors), visitorColor],
          [text.receipts, text.number(receipts), receiptColor],
        ];
        if (visitors > 0 && visitors >= receipts) lines.push([text.conversion, text.percent((receipts / visitors) * 100)]);
        if (visitors > receipts) lines.push([text.left, text.number(visitors - receipts)]);
        if (row.queue_max) lines.push([text.queue, text.number(row.queue_max)]);
        if (row.wait_max_s) lines.push([text.wait, text.seconds(row.wait_max_s)]);
        if (row.staff_avg !== null) lines.push([text.atCounter, text.number(row.staff_avg ?? 0, 1)]);
        if (row.staff_checked_in !== null) lines.push([text.onShift, text.number(row.staff_checked_in ?? 0)]);
        if (row.unattended_minutes) lines.push([text.unattended, text.minutes(row.unattended_minutes)]);
        const title = hourRange(row.hour) + (row.hour === input.partialHour ? ` · ${text.partial}` : "");
        const body = lines
          .map(
            ([name, value, color]) =>
              `<div style="display:flex;justify-content:space-between;gap:18px;line-height:20px"><span style="display:flex;align-items:center;opacity:.8">${color ? `<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${color};margin-right:8px"></span>` : ""}${escapeHtml(name)}</span><b style="font-variant-numeric:tabular-nums;font-weight:600">${escapeHtml(value)}</b></div>`,
          )
          .join("");
        return `<div style="font-family:${theme.fontFamily};min-width:180px"><div style="opacity:.6;font-size:12px;margin-bottom:4px">${escapeHtml(title)}</div>${body}</div>`;
      },
    },
    series: [
      {
        type: "bar",
        name: text.visitors,
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: hours.map((row) => ({
          value: row.visitors ?? 0,
          itemStyle: { color: row.hour === input.partialHour ? withAlpha(visitorColor, 0.45) : visitorColor, borderRadius: [5, 5, 0, 0] },
        })),
        barMaxWidth: 26,
        barCategoryGap: "34%",
        emphasis: { itemStyle: { color: visitorColor } },
        z: 2,
      },
      {
        type: "line",
        name: text.receipts,
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: hours.map((row) => row.receipts ?? 0),
        smooth: 0.25,
        symbol: "circle",
        symbolSize: input.narrow ? 5 : 7,
        showSymbol: true,
        lineStyle: { width: 2.25, color: receiptColor },
        itemStyle: { color: receiptColor, borderColor: theme.surface, borderWidth: 2 },
        z: 3,
      },
      strip(
        1,
        hours.map((row) => ({
          value: 1,
          itemStyle: { color: heatColor(waitHeat(row.wait_max_s, input.queueWaitS)), borderRadius: 4 },
          label: { formatter: () => (row.wait_max_s && row.wait_max_s >= 60 ? `${Math.round(row.wait_max_s / 60)}′` : "") },
        })),
      ),
      strip(
        2,
        hours.map((row) => ({
          value: 1,
          itemStyle: { color: staffColor(row), borderRadius: 4 },
          label: { formatter: () => (row.staff_checked_in ? `${text.number(row.staff_avg ?? 0, 1)}/${text.number(row.staff_checked_in)}` : "") },
        })),
      ),
    ],
  };
}

/** The hours as CSV rows for the chart's download. */
export function hourCsv(hours: HourRow[]) {
  return hours.map((row) => ({ ...row, label: hourLabel(row.hour) }));
}
