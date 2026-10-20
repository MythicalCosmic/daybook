<script setup lang="ts">
/**
 * Comparisons: branches side by side, sales by day, expenses by category. `stacked` stacks the
 * series, `normalize` makes 100% bars (payment mix per branch), `horizontal` lays bars sideways
 * (long labels, rankings).
 *
 *   <BarChart :categories="branchNames" :series="[{ name: t('sales.net'), data: net }]" horizontal value-format="money" />
 */
import type { Currency } from "@/api/types";

import CartesianChart from "./CartesianChart.vue";
import type { ChartSeries, ValueFormat } from "./chartCard";

withDefaults(
  defineProps<{
    categories: string[];
    series: ChartSeries[];
    compare?: ChartSeries | null;
    valueFormat?: ValueFormat;
    currency?: Currency;
    xFormat?: "day" | "month" | "none";
    height?: string;
    legend?: boolean;
    target?: { value: number | string; label?: string } | null;
    label?: string;
    stacked?: boolean;
    horizontal?: boolean;
    normalize?: boolean;
  }>(),
  {
    compare: null,
    valueFormat: "number",
    currency: undefined,
    xFormat: "none",
    height: "240px",
    legend: undefined,
    target: null,
    label: undefined,
    stacked: false,
    horizontal: false,
    normalize: false,
  },
);
</script>

<template>
  <CartesianChart type="bar" v-bind="$props" />
</template>
