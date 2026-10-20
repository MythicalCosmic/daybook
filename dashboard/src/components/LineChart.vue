<script setup lang="ts">
/**
 * Trends over time: one or a few series, a dashed previous period (`compare`), a target line.
 * Values may be decimal strings from the API (plotted only). Put it in a ChartCard.
 *
 *   <LineChart :categories="days" :series="[{ name: t('sales.net'), data: net }]" :compare="previous" value-format="money" x-format="day" />
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
    smooth?: boolean;
  }>(),
  { compare: null, valueFormat: "number", currency: undefined, xFormat: "none", height: "240px", legend: undefined, target: null, label: undefined, smooth: false },
);
</script>

<template>
  <CartesianChart type="line" v-bind="$props" />
</template>
