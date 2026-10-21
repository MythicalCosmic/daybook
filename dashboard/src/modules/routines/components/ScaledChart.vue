<script setup lang="ts">
/**
 * The shared line/bar chart (the same option builder as `@/components/CartesianChart`) with a
 * fixed value-axis ceiling and whole-number ticks: a percentage axis stops at 100 % instead of
 * the next "nice" 120 %, and counts never get 0.5 ticks. Candidate for `src/components` at
 * integration (as `yMax` / `integer` props on CartesianChart).
 */
import { computed, ref } from "vue";

import { EChartAsync, type ChartSeries, type ValueFormat } from "@/components/chartCard";
import { cartesianOption } from "@/components/chartOptions";
import { useChartTheme } from "@/components/useChartTheme";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

const props = withDefaults(
  defineProps<{
    type?: "line" | "bar";
    categories: string[];
    series: ChartSeries[];
    valueFormat?: ValueFormat;
    xFormat?: "day" | "month" | "none";
    height?: string;
    legend?: boolean;
    label?: string;
    stacked?: boolean;
    horizontal?: boolean;
    smooth?: boolean;
    /** The value axis never goes past this (100 for percentages). */
    yMax?: number;
    /** Whole-number ticks only (counts). */
    integer?: boolean;
  }>(),
  { type: "line", valueFormat: "number", xFormat: "none", height: "240px", legend: undefined, label: undefined, stacked: false, horizontal: false, smooth: false, yMax: undefined, integer: false },
);

const fmt = useFormat();
const company = useCompanyStore();
const host = ref<HTMLElement | null>(null);
const theme = useChartTheme(host);

const option = computed(() => {
  const base = cartesianOption(
    theme.value,
    { categories: props.categories, series: props.series, compare: null, valueFormat: props.valueFormat, xFormat: props.xFormat, legend: props.legend, target: null },
    { type: props.type, area: false, stacked: props.stacked, horizontal: props.horizontal, normalize: false, smooth: props.smooth },
    { lang: fmt.lang.value, currency: company.currency },
  ) as Record<string, unknown>;
  const axisKey = props.horizontal ? "xAxis" : "yAxis";
  const axis = base[axisKey] as Record<string, unknown> | undefined;
  if (axis) {
    base[axisKey] = {
      ...axis,
      ...(props.yMax !== undefined ? { min: 0, max: props.yMax, interval: props.yMax / 4 } : {}),
      ...(props.integer ? { minInterval: 1 } : {}),
    };
  }
  return base;
});
</script>

<template>
  <div ref="host" class="min-w-0" :style="{ height }">
    <EChartAsync :option="option" height="100%" :label="label" />
  </div>
</template>
