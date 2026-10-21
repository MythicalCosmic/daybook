/** Wiring between ChartCard and the chart inside it (for "Download PNG"), and the shared chart props. */
import { defineAsyncComponent, h, type InjectionKey } from "vue";

import type { Currency, Language } from "@/api/types";
import { formatPercent } from "@/lib/format";

import SkeletonBlock from "./SkeletonBlock.vue";

/**
 * A part's share of a whole, in whole percent, never rounded to a claim it isn't: a sliver reads
 * "<1%" (not "0%", which says it isn't there), and a part that isn't the whole never reads "100%".
 */
export function shareText(percent: number, lang: Language): string {
  if (percent > 0 && percent < 0.5) return `<${formatPercent(1, lang)}`;
  if (percent < 100 && percent >= 99.5) return `>${formatPercent(99, lang)}`;
  return formatPercent(percent, lang);
}

export interface ChartCardContext {
  register: (toPng: ((background: string) => string | null) | null) => void;
}

export const CHART_CARD_KEY: InjectionKey<ChartCardContext> = Symbol("chart-card");

/**
 * The ECharts canvas, loaded on first use so pages without charts never download ECharts. A
 * skeleton fills the chart's box (after 150 ms) while the chunk loads.
 */
export const EChartAsync = defineAsyncComponent({
  loader: () => import("./EChart.vue"),
  loadingComponent: { name: "ChartLoading", render: () => h(SkeletonBlock, { height: "100%", radius: "10px" }) },
  delay: 150,
  suspensible: false,
});

export type ValueFormat = "number" | "money" | "percent" | "compact" | ((value: number) => string);

export interface ChartSeries {
  name: string;
  /** One value per category; money may come as decimal strings (plotted, never summed). */
  data: Array<number | string | null>;
  color?: string;
  /** Draw dashed (plans, targets, previous period). */
  dashed?: boolean;
  /** Same stack name → stacked. */
  stack?: string;
}

export interface ChartBaseProps {
  categories: string[];
  series: ChartSeries[];
  /** Previous period, drawn as a dashed warm-gray line. */
  compare?: ChartSeries | null;
  valueFormat?: ValueFormat;
  currency?: Currency;
  /** How to show category labels: "day" turns "2026-10-20" into "20 Oct". */
  xFormat?: "day" | "month" | "none";
  height?: string;
  legend?: boolean;
  /** A horizontal line (a sales target, a budget); its label is named in the legend and tooltip. */
  target?: { value: number | string; label?: string } | null;
  /** The value axis runs 0…yMax in four steps (100: a percentage axis stops at 100 %). */
  yMax?: number;
  /** Whole-number ticks only (counts). */
  integer?: boolean;
  label?: string;
}

export function toNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? number : null;
}
