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
    /** The value axis runs 0…yMax in four steps (100: a percentage axis stops at 100 %). */
    yMax?: number;
    /** Whole-number ticks only (counts). */
    integer?: boolean;
    label?: string;
    smooth?: boolean;
    /** The last category is still in progress (today so far): dashed into a hollow point, `label` ("so far") in the tooltip. */
    partial?: { label: string } | null;
  }>(),
  { compare: null, valueFormat: "number", currency: undefined, xFormat: "none", height: "240px", legend: undefined, target: null, yMax: undefined, integer: false, label: undefined, smooth: false, partial: null },
);
</script>

<template>
  <CartesianChart type="line" v-bind="$props" />
</template>
