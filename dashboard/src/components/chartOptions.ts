/**
 * ECharts options for the line, area and bar charts, built from the tokens (useChartTheme) and the
 * dataviz mark specs: 2 px lines, area washes, bars at most 24 px thick with 4 px rounded ends and
 * 2 px surface gaps, hairline solid grid, a crosshair tooltip, compact axis numbers, and animation
 * of 400 ms that switches off above 1 000 points or with reduced motion.
 */
import type { Currency, Language } from "@/api/types";
import { formatDay } from "@/lib/dates";
import { formatNumber, formatPercent } from "@/lib/format";
import { formatCompact, formatMoney } from "@/lib/money";

import { toNumber, type ChartSeries, type ValueFormat } from "./chartCard";
import { axisStyle, CHART_TYPE, escapeHtml, tooltipStyle, type ChartTheme } from "./useChartTheme";

export interface FormatContext {
  lang: Language;
  currency: Currency;
}

/** Full value text for tooltips. */
export function valueText(value: number | null, format: ValueFormat | undefined, ctx: FormatContext): string {
  if (value === null) return "—";
  if (typeof format === "function") return format(value);
  switch (format) {
    case "money":
      return formatMoney(value, ctx.currency, ctx.lang, { decimals: "never" });
    case "percent":
      return formatPercent(value, ctx.lang, 1);
    case "compact":
      return formatCompact(value, ctx.lang);
    default:
      return formatNumber(value, ctx.lang, 1);
  }
}

/** Short value text for axis ticks: "12,5 mln", "40%". */
export function axisText(value: number, format: ValueFormat | undefined, ctx: FormatContext): string {
  if (typeof format === "function") return format(value);
  if (format === "percent") return formatPercent(value, ctx.lang);
  if (Math.abs(value) >= 10_000) return formatCompact(value, ctx.lang);
  return formatNumber(value, ctx.lang, 1);
}

export function categoryText(category: string, xFormat: "day" | "month" | "none" | undefined, lang: Language): string {
  if (xFormat === "day" && /^\d{4}-\d{2}-\d{2}$/.test(category)) return formatDay(category, lang, "short");
  if (xFormat === "month" && /^\d{4}-\d{2}/.test(category)) return formatDay(`${category.slice(0, 7)}-01`, lang, "monthYear");
  return category;
}

export function reducedMotion(): boolean {
  if (typeof document === "undefined") return false;
  return document.documentElement.dataset.motion === "reduced";
}

interface TooltipRow {
  name: string;
  color: string;
  value: number | null;
  dashed?: boolean;
}

export function tooltipHtml(title: string, rows: TooltipRow[], format: ValueFormat | undefined, ctx: FormatContext, theme: ChartTheme): string {
  const lines = rows
    .map((row) => {
      const swatch = row.dashed
        ? `<span style="display:inline-block;width:10px;border-top:2px dashed ${row.color};margin-right:8px;vertical-align:middle"></span>`
        : `<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${row.color};margin-right:8px"></span>`;
      return `<div style="display:flex;align-items:center;gap:16px;justify-content:space-between;line-height:20px"><span style="display:flex;align-items:center;opacity:.8">${swatch}${escapeHtml(row.name)}</span><b style="font-variant-numeric:tabular-nums;font-weight:600">${escapeHtml(valueText(row.value, format, ctx))}</b></div>`;
    })
    .join("");
  return `<div style="font-family:${theme.fontFamily};min-width:140px"><div style="opacity:.6;font-size:12px;margin-bottom:4px">${escapeHtml(title)}</div>${lines}</div>`;
}

export interface CartesianInput {
  categories: string[];
  series: ChartSeries[];
  compare?: ChartSeries | null;
  valueFormat?: ValueFormat;
  xFormat?: "day" | "month" | "none";
  legend?: boolean;
  target?: { value: number | string; label?: string } | null;
}

export interface CartesianStyle {
  type: "line" | "bar";
  area?: boolean;
  horizontal?: boolean;
  stacked?: boolean;
  /** 100% stacks (shares per category). */
  normalize?: boolean;
  smooth?: boolean;
}

export function cartesianOption(theme: ChartTheme, input: CartesianInput, style: CartesianStyle, ctx: FormatContext): Record<string, unknown> {
  const { categories } = input;
  const format: ValueFormat | undefined = style.normalize ? "percent" : input.valueFormat;
  const colorOf = (series: ChartSeries, index: number) => series.color ?? theme.series[index % theme.series.length]!;

  let values = input.series.map((series) => series.data.map(toNumber));
  if (style.normalize) {
    const totals = categories.map((_, i) => values.reduce((sum, list) => sum + Math.max(0, list[i] ?? 0), 0));
    values = values.map((list) => list.map((v, i) => (v === null || !totals[i] ? null : (Math.max(0, v) / totals[i]!) * 100)));
  }
  const points = values.reduce((sum, list) => sum + list.length, 0);
  const animate = points <= 1000 && !reducedMotion();
  const showLegend = input.legend ?? input.series.length + (input.compare ? 1 : 0) > 1;
  const stacked = style.stacked || style.normalize;

  const series: Record<string, unknown>[] = input.series.map((entry, index) => {
    const color = colorOf(entry, index);
    const data = values[index]!;
    if (style.type === "line") {
      return {
        type: "line",
        name: entry.name,
        data,
        stack: stacked ? "total" : entry.stack,
        smooth: style.smooth ? 0.3 : false,
        showSymbol: data.length <= 2,
        symbol: "circle",
        symbolSize: 8,
        connectNulls: false,
        lineStyle: { width: 2, color, type: entry.dashed ? [5, 4] : "solid", cap: "round", join: "round" },
        itemStyle: { color, borderColor: theme.surface, borderWidth: 2 },
        emphasis: { focus: "series", lineStyle: { width: 2 } },
        areaStyle: style.area
          ? {
              opacity: 1,
              color: {
                type: "linear",
                x: 0,
                y: 0,
                x2: 0,
                y2: 1,
                colorStops: [
                  { offset: 0, color: withAlpha(color, stacked ? 0.28 : 0.18) },
                  { offset: 1, color: withAlpha(color, stacked ? 0.12 : 0.01) },
                ],
              },
            }
          : undefined,
        z: 3,
      };
    }
    const radius = style.horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0];
    return {
      type: "bar",
      name: entry.name,
      data,
      stack: stacked ? "total" : entry.stack,
      barMaxWidth: 24,
      barGap: "25%",
      barCategoryGap: "38%",
      itemStyle: {
        color: entry.dashed ? withAlpha(color, 0.25) : color,
        borderRadius: stacked ? 2 : radius,
        borderColor: stacked ? theme.surface : undefined,
        borderWidth: stacked ? 1 : 0,
      },
      emphasis: { focus: "series" },
    };
  });

  if (input.compare) {
    series.push({
      type: "line",
      name: input.compare.name,
      data: input.compare.data.map(toNumber),
      showSymbol: false,
      symbol: "circle",
      symbolSize: 7,
      lineStyle: { width: 1.75, color: theme.compare, type: [5, 4] },
      itemStyle: { color: theme.compare },
      z: 2,
    });
  }

  if (input.target) {
    const value = toNumber(input.target.value);
    if (value !== null) {
      (series[0] ??= { type: style.type, data: [] }).markLine = {
        silent: true,
        symbol: "none",
        lineStyle: { color: theme.muted, type: [4, 4], width: 1 },
        label: { formatter: input.target.label ?? "", color: theme.muted, fontFamily: theme.fontFamily, fontSize: CHART_TYPE.axis, position: "insideEndTop" },
        data: [style.horizontal ? { xAxis: value } : { yAxis: value }],
      };
    }
  }

  const labels = categories.map((category) => categoryText(category, input.xFormat, ctx.lang));
  const axes = axisStyle(theme);
  const categoryAxis = {
    type: "category",
    data: labels,
    boundaryGap: style.type === "bar",
    ...axes,
    splitLine: { show: false },
    axisLine: { show: true, lineStyle: { color: theme.border } },
    axisPointer: style.type === "line" ? { type: "line", lineStyle: { color: theme.subtle, width: 1, type: "solid" } } : { type: "shadow", shadowStyle: { color: withAlpha(theme.text, 0.05) } },
  };
  const valueAxis = {
    type: "value",
    ...axes,
    max: style.normalize ? 100 : undefined,
    splitNumber: 4,
    axisLabel: { ...axes.axisLabel, formatter: (value: number) => axisText(value, format, ctx) },
  };

  const swatchColors = [...input.series.map((s, i) => colorOf(s, i)), ...(input.compare ? [theme.compare] : [])];

  return {
    animation: animate,
    animationDuration: 400,
    animationDurationUpdate: 300,
    animationEasing: "cubicOut",
    color: swatchColors,
    textStyle: { fontFamily: theme.fontFamily },
    grid: { top: showLegend ? 40 : 14, right: 12, bottom: 4, left: 4, containLabel: true },
    legend: showLegend
      ? {
          top: 0,
          left: 0,
          icon: "roundRect",
          itemWidth: 10,
          itemHeight: 10,
          itemGap: 16,
          textStyle: { color: theme.muted, fontFamily: theme.fontFamily, fontSize: CHART_TYPE.label },
        }
      : { show: false },
    tooltip: {
      trigger: "axis",
      confine: true,
      ...tooltipStyle(theme),
      formatter: (params: Array<{ dataIndex: number; seriesIndex: number; seriesName: string; color: string; value: number | null }>) => {
        const first = params[0];
        if (!first) return "";
        const rows = params.map((param) => ({
          name: param.seriesName,
          color: param.seriesIndex >= input.series.length ? theme.compare : colorOf(input.series[param.seriesIndex]!, param.seriesIndex),
          value: typeof param.value === "number" ? param.value : null,
          dashed: param.seriesIndex >= input.series.length || input.series[param.seriesIndex]?.dashed,
        }));
        return tooltipHtml(labels[first.dataIndex] ?? "", rows, format, ctx, theme);
      },
    },
    xAxis: style.horizontal ? valueAxis : categoryAxis,
    yAxis: style.horizontal ? { ...categoryAxis, inverse: true, axisPointer: { type: "shadow", shadowStyle: { color: withAlpha(theme.text, 0.05) } } } : valueAxis,
    series,
  };
}

/** "rgb(198, 113, 57)" or "#c67139" with an alpha channel. */
export function withAlpha(color: string, alpha: number): string {
  const rgb = /^rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(color);
  if (rgb) return `rgba(${rgb[1]}, ${rgb[2]}, ${rgb[3]}, ${alpha})`;
  const hex = /^#([0-9a-f]{6})$/i.exec(color);
  if (hex) {
    const n = parseInt(hex[1]!, 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
  }
  return color;
}
