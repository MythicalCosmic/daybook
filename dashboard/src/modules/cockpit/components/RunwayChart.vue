<script setup lang="ts">
/**
 * The cash line of the next 90 days (`finance.planning.forecast` as the cockpit returns it) with
 * the owner's buffer as a dashed line and the low point marked with its amount. Built on the
 * shared chart options (tokens, axes, tooltip), drawn by the one ECharts component.
 */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { EChartAsync, toNumber } from "@/components/chartCard";
import { cartesianOption, withAlpha } from "@/components/chartOptions";
import { useChartTheme } from "@/components/useChartTheme";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import type { CockpitCash } from "../api";
import { lowKind } from "../lib";

const props = withDefaults(defineProps<{ cash: CockpitCash; height?: string }>(), { height: "260px" });

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const host = ref<HTMLElement | null>(null);
const theme = useChartTheme(host);

const kind = computed(() => lowKind(props.cash));

const option = computed(() => {
  const palette = theme.value;
  const color = kind.value === "short" ? palette.danger : kind.value === "under" ? palette.warning : palette.series[1]!;
  const days = props.cash.points.map((point) => point.date);
  const balances = props.cash.points.map((point) => point.balance);
  const base = cartesianOption(
    palette,
    {
      categories: days,
      series: [{ name: t("cockpit.cash.series"), data: balances, color }],
      valueFormat: "money",
      xFormat: "day",
      target: { value: props.cash.buffer, label: t("cockpit.cash.bufferSeries") },
      legend: true,
    },
    { type: "line", area: true, smooth: true },
    { lang: fmt.lang.value, currency: company.currency },
  );
  const lowIndex = days.indexOf(props.cash.low.date);
  if (lowIndex < 0) return base;
  const low = toNumber(props.cash.low.balance);
  const marker = {
    type: "line",
    name: t("cockpit.cash.lowSeries"),
    data: days.map((_, index) => (index === lowIndex ? low : null)),
    showSymbol: true,
    symbol: "circle",
    symbolSize: 11,
    itemStyle: { color, borderColor: palette.surface, borderWidth: 3, shadowBlur: 0 },
    lineStyle: { width: 0 },
    label: {
      show: true,
      position: lowIndex > days.length * 0.85 ? "left" : "bottom",
      distance: 8,
      color: palette.text,
      fontFamily: palette.fontFamily,
      fontSize: 11,
      fontWeight: 600,
      backgroundColor: withAlpha(palette.surface, 0.9),
      padding: [3, 6],
      borderRadius: 6,
      formatter: () => fmt.money(props.cash.low.balance, undefined, { compact: true }),
    },
    markLine: {
      silent: true,
      symbol: "none",
      label: { show: false },
      lineStyle: { color: withAlpha(color, 0.55), type: [3, 3], width: 1 },
      data: [{ xAxis: lowIndex }],
    },
    tooltip: { show: false },
    emphasis: { disabled: true },
    z: 5,
  };
  return { ...base, series: [...(base.series as unknown[]), marker] };
});
</script>

<template>
  <div ref="host" :style="{ height }" class="min-w-0">
    <EChartAsync :option="option" :height="height" :label="t('cockpit.cash.title')" />
  </div>
</template>
