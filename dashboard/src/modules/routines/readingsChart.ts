/**
 * The journal chart of a readings routine (PLAN-OWNER §14.10): one reading's daily values as a
 * line over its allowed band (a soft area between the lowest and highest allowed value, a dashed
 * line at each bound), values out of range marked in the danger colour. Built on the shared chart
 * theme and drawn by the dashboard's own ECharts component (no new chart library).
 */
import { categoryText, withAlpha } from "@/components/chartOptions";
import { axisStyle, CHART_TYPE, escapeHtml, tooltipStyle, type ChartTheme } from "@/components/useChartTheme";
import type { Language } from "@/api/types";

import { readingNumber } from "./readings";

export interface ReadingsChartInput {
  days: string[];
  /** The day's first value, null on a day without one. */
  values: Array<number | null>;
  min: number | null;
  max: number | null;
  label: string;
  unit: string;
  lang: Language;
  /** "Out of range", "Allowed" in the reader's language. */
  words: { out: string; allowed: string };
}

export function inRange(value: number, min: number | null, max: number | null): boolean {
  return (min === null || value >= min) && (max === null || value <= max);
}

export function readingsOption(theme: ChartTheme, input: ReadingsChartInput): Record<string, unknown> {
  const { min, max, unit, lang } = input;
  const labels = input.days.map((day) => categoryText(day, "day", lang));
  const axes = axisStyle(theme);
  const point = (value: number | null) =>
    value === null
      ? null
      : inRange(value, min, max)
        ? { value }
        : { value, symbolSize: 9, itemStyle: { color: theme.danger, borderColor: theme.surface, borderWidth: 2 } };
  const bounds = [min, max].filter((bound): bound is number => bound !== null);
  const series: Array<Record<string, unknown>> = [];
  if (min !== null && max !== null) {
    // The band: an invisible base at the lowest bound and the band's height stacked on it.
    const quiet = { lineStyle: { opacity: 0 }, symbol: "none", silent: true, tooltip: { show: false } };
    series.push({ type: "line", name: "__base", data: input.days.map(() => min), stack: "band", ...quiet });
    series.push({ type: "line", name: "__band", data: input.days.map(() => max - min), stack: "band", areaStyle: { color: withAlpha(theme.success, theme.dark ? 0.16 : 0.12) }, ...quiet });
  }
  series.push({
    type: "line",
    name: input.label,
    data: input.values.map(point),
    connectNulls: false,
    showSymbol: true,
    symbol: "circle",
    symbolSize: 5,
    lineStyle: { width: 2, color: theme.series[0] },
    itemStyle: { color: theme.series[0] },
    z: 3,
    markLine: bounds.length
      ? {
          silent: true,
          symbol: "none",
          label: { show: true, position: "insideEndTop", color: theme.muted, fontSize: CHART_TYPE.axis, formatter: (param: { value: number }) => readingNumber(param.value, lang) },
          lineStyle: { color: theme.warning, type: "dashed", width: 1 },
          data: bounds.map((bound) => ({ yAxis: bound })),
        }
      : undefined,
  });
  const known = [...input.values.filter((value): value is number => value !== null), ...bounds];
  const low = known.length ? Math.min(...known) : 0;
  const high = known.length ? Math.max(...known) : 1;
  const pad = Math.max((high - low) * 0.15, 0.5);
  return {
    animation: false,
    textStyle: { fontFamily: theme.fontFamily },
    grid: { top: 14, right: 12, bottom: 4, left: 4, containLabel: true },
    legend: { show: false },
    tooltip: {
      trigger: "axis",
      confine: true,
      ...tooltipStyle(theme),
      formatter: (params: Array<{ dataIndex: number; seriesName: string }>) => {
        const index = params[0]?.dataIndex ?? 0;
        const value = input.values[index] ?? null;
        const title = escapeHtml(labels[index] ?? "");
        if (value === null) return title;
        const text = `${readingNumber(value, lang)} ${escapeHtml(unit)}`.trim();
        const flag = inRange(value, min, max) ? "" : ` · <b>${escapeHtml(input.words.out)}</b>`;
        return `${title}<br/>${escapeHtml(input.label)}: <b>${text}</b>${flag}`;
      },
    },
    xAxis: {
      type: "category",
      data: labels,
      boundaryGap: false,
      ...axes,
      splitLine: { show: false },
      axisLine: { show: true, lineStyle: { color: theme.border } },
      axisPointer: { type: "line", lineStyle: { color: theme.subtle, width: 1, type: "solid" } },
    },
    yAxis: {
      type: "value",
      ...axes,
      min: Math.floor((low - pad) * 2) / 2,
      max: Math.ceil((high + pad) * 2) / 2,
      splitNumber: 4,
      axisLabel: { ...axes.axisLabel, formatter: (value: number) => readingNumber(value, lang) },
    },
    series,
  };
}
