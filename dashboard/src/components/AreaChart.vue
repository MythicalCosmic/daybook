<script setup lang="ts">
/**
 * A trend with a soft wash under it (cash over time, sales today vs a usual day); `stacked` stacks
 * the series (income by category over time).
 *
 *   <AreaChart :categories="days" :series="[{ name: t('finance.cash'), data: cash }]" value-format="money" x-format="day" />
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
    stacked?: boolean;
    smooth?: boolean;
  }>(),
  { compare: null, valueFormat: "number", currency: undefined, xFormat: "none", height: "240px", legend: undefined, target: null, yMax: undefined, integer: false, label: undefined, stacked: false, smooth: true },
);
</script>

<template>
  <CartesianChart type="line" area v-bind="$props" />
</template>
