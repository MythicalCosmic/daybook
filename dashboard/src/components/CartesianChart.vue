<script setup lang="ts">
/** Shared body of LineChart, AreaChart and BarChart (use those). */
import { computed, ref } from "vue";

import type { Currency } from "@/api/types";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { EChartAsync, type ChartSeries, type ValueFormat } from "./chartCard";
import { cartesianOption } from "./chartOptions";
import { useChartTheme } from "./useChartTheme";

const props = withDefaults(
  defineProps<{
    type: "line" | "bar";
    categories: string[];
    series: ChartSeries[];
    compare?: ChartSeries | null;
    valueFormat?: ValueFormat;
    currency?: Currency;
    xFormat?: "day" | "month" | "none";
    height?: string;
    legend?: boolean;
    target?: { value: number | string; label?: string } | null;
    /** The value axis runs 0…yMax in four steps (100: a percentage axis stops at 100 %). */
    yMax?: number;
    /** Whole-number ticks only (counts). */
    integer?: boolean;
    label?: string;
    area?: boolean;
    stacked?: boolean;
    horizontal?: boolean;
    normalize?: boolean;
    smooth?: boolean;
    /** The last category is still in progress (today so far): dashed into a hollow point, "so far" in the tooltip. */
    partial?: { label: string } | null;
  }>(),
  {
    compare: null,
    valueFormat: "number",
    currency: undefined,
    xFormat: "none",
    height: "240px",
    legend: undefined,
    target: null,
    yMax: undefined,
    integer: false,
    label: undefined,
    area: false,
    stacked: false,
    horizontal: false,
    normalize: false,
    smooth: false,
    partial: null,
  },
);

const fmt = useFormat();
const company = useCompanyStore();
const host = ref<HTMLElement | null>(null);
const theme = useChartTheme(host);

const option = computed(() =>
  cartesianOption(
    theme.value,
    {
      categories: props.categories,
      series: props.series,
      compare: props.compare,
      valueFormat: props.valueFormat,
      xFormat: props.xFormat,
      legend: props.legend,
      target: props.target,
      yMax: props.yMax,
      integer: props.integer,
      partial: props.partial,
    },
    { type: props.type, area: props.area, stacked: props.stacked, horizontal: props.horizontal, normalize: props.normalize, smooth: props.smooth },
    { lang: fmt.lang.value, currency: props.currency ?? company.currency },
  ),
);
</script>

<template>
  <div ref="host" class="min-w-0" :style="{ height }">
    <EChartAsync :option="option" height="100%" :label="label" />
  </div>
</template>
