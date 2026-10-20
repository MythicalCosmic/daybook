<script setup lang="ts">
/**
 * An ECharts heatmap for dense analytics (sales by hour × weekday): one sequential terracotta ramp,
 * a tooltip per cell, Monday-first rows. For people × days grids with clickable cells use HeatmapGrid.
 *
 *   <HeatmapChart :x="hours" :y="weekdayNames" :values="[[hourIndex, dayIndex, net], …]" value-format="money" />
 */
import { computed, ref } from "vue";

import type { Currency } from "@/api/types";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { EChartAsync, toNumber, type ValueFormat } from "./chartCard";
import { reducedMotion, tooltipHtml, withAlpha } from "./chartOptions";
import { axisStyle, tooltipStyle, useChartTheme } from "./useChartTheme";

const props = withDefaults(
  defineProps<{
    x: string[];
    y: string[];
    /** [xIndex, yIndex, value] triples. */
    values: Array<[number, number, number | string | null]>;
    valueFormat?: ValueFormat;
    currency?: Currency;
    height?: string;
    label?: string;
  }>(),
  { valueFormat: "number", currency: undefined, height: "260px", label: undefined },
);

const fmt = useFormat();
const company = useCompanyStore();
const host = ref<HTMLElement | null>(null);
const theme = useChartTheme(host);

const data = computed(() => props.values.map(([x, y, v]) => [x, y, toNumber(v)] as [number, number, number | null]));
const max = computed(() => Math.max(1, ...data.value.map((d) => d[2] ?? 0)));

const option = computed(() => {
  const axes = axisStyle(theme.value);
  const ctx = { lang: fmt.lang.value, currency: props.currency ?? company.currency };
  return {
    animation: !reducedMotion(),
    animationDuration: 400,
    grid: { top: 4, right: 4, bottom: 4, left: 4, containLabel: true },
    tooltip: {
      trigger: "item",
      confine: true,
      ...tooltipStyle(theme.value),
      formatter: (param: { value: [number, number, number | null] }) => {
        const [x, y, v] = param.value;
        return tooltipHtml(`${props.y[y] ?? ""} · ${props.x[x] ?? ""}`, [{ name: props.label ?? "", color: theme.value.primary, value: v }], props.valueFormat, ctx, theme.value);
      },
    },
    xAxis: { type: "category", data: props.x, ...axes, splitLine: { show: false }, splitArea: { show: false } },
    yAxis: { type: "category", data: props.y, inverse: true, ...axes, splitLine: { show: false } },
    visualMap: {
      show: false,
      min: 0,
      max: max.value,
      inRange: { color: [withAlpha(theme.value.series[0]!, 0.08), withAlpha(theme.value.series[0]!, 0.45), theme.value.primary] },
    },
    series: [
      {
        type: "heatmap",
        data: data.value,
        itemStyle: { borderColor: theme.value.surface, borderWidth: 2, borderRadius: 4 },
        emphasis: { itemStyle: { borderColor: theme.value.text, borderWidth: 1 } },
      },
    ],
  };
});
</script>

<template>
  <div ref="host" class="min-w-0" :style="{ height }">
    <EChartAsync :option="option" height="100%" :label="label" />
  </div>
</template>
