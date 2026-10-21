<script setup lang="ts">
/**
 * Parts of a whole (expenses by category, payment methods, where cash sits): a ring with the total
 * in the middle and a legend with each part's value and share. More than `maxSlices` parts fold into
 * "Other" (never a ninth color).
 *
 *   <DonutChart :slices="[{ name: 'Rent', value: '12000000' }, …]" value-format="money" :center-label="t('finance.expenses')" />
 */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import type { Currency } from "@/api/types";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { EChartAsync, shareText, toNumber, type ValueFormat } from "./chartCard";
import { reducedMotion, tooltipHtml, valueText } from "./chartOptions";
import { tooltipStyle, useChartTheme } from "./useChartTheme";

export interface DonutSlice {
  name: string;
  value: number | string | null;
  color?: string;
}

const props = withDefaults(
  defineProps<{
    slices: DonutSlice[];
    valueFormat?: ValueFormat;
    currency?: Currency;
    height?: string;
    centerLabel?: string;
    /** Text in the middle; default the total. */
    centerValue?: string;
    maxSlices?: number;
    legend?: "right" | "bottom" | "none";
    label?: string;
  }>(),
  { valueFormat: "number", currency: undefined, height: "220px", centerLabel: undefined, centerValue: undefined, maxSlices: 6, legend: "right", label: undefined },
);

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const host = ref<HTMLElement | null>(null);
const theme = useChartTheme(host);
const ctx = computed(() => ({ lang: fmt.lang.value, currency: props.currency ?? company.currency }));

const parts = computed(() => {
  const list = props.slices.map((slice) => ({ ...slice, number: Math.max(0, toNumber(slice.value) ?? 0) })).sort((a, b) => b.number - a.number);
  if (list.length <= props.maxSlices) return list;
  const head = list.slice(0, props.maxSlices - 1);
  const rest = list.slice(props.maxSlices - 1);
  return [...head, { name: t("common.chart.other"), value: null, number: rest.reduce((sum, item) => sum + item.number, 0), color: undefined, other: true }];
});
const total = computed(() => parts.value.reduce((sum, part) => sum + part.number, 0));
const colored = computed(() =>
  parts.value.map((part, index) => ({ ...part, fill: part.color ?? ("other" in part ? theme.value.compare : theme.value.series[index % (theme.value.series.length - 1)]!) })),
);
const share = (value: number) => (total.value > 0 ? (value / total.value) * 100 : 0);

const option = computed(() => ({
  animation: !reducedMotion(),
  animationDuration: 400,
  tooltip: {
    trigger: "item",
    confine: true,
    ...tooltipStyle(theme.value),
    formatter: (param: { dataIndex: number }) => {
      const part = colored.value[param.dataIndex];
      if (!part) return "";
      return tooltipHtml(`${fmt.percent(share(part.number), 1)}`, [{ name: part.name, color: part.fill, value: part.number }], props.valueFormat, ctx.value, theme.value);
    },
  },
  series: [
    {
      type: "pie",
      radius: ["64%", "90%"],
      center: ["50%", "50%"],
      avoidLabelOverlap: true,
      padAngle: 1.5,
      itemStyle: { borderRadius: 4, borderColor: theme.value.surface, borderWidth: 2 },
      label: { show: false },
      labelLine: { show: false },
      emphasis: { scale: true, scaleSize: 4 },
      data: colored.value.map((part) => ({ name: part.name, value: part.number, itemStyle: { color: part.fill } })),
    },
  ],
}));
</script>

<template>
  <div ref="host" :class="['flex min-w-0 gap-5', legend === 'bottom' ? 'flex-col items-stretch' : 'flex-col items-center sm:flex-row']">
    <div class="relative shrink-0" :style="{ height, width: height }">
      <EChartAsync :option="option" height="100%" :label="label" />
      <div class="pointer-events-none absolute inset-0 grid place-items-center text-center">
        <div class="max-w-[60%]">
          <p v-if="centerLabel" class="truncate text-xs text-muted">{{ centerLabel }}</p>
          <p class="truncate text-lg font-semibold tabular-nums text-fg">{{ centerValue ?? valueText(total, valueFormat === "money" ? "compact" : valueFormat, ctx) }}</p>
        </div>
      </div>
    </div>
    <ul v-if="legend !== 'none'" class="flex w-full min-w-0 flex-1 flex-col gap-1.5">
      <li v-for="part in colored" :key="part.name" class="flex min-w-0 items-center gap-2.5 text-sm">
        <span class="size-2.5 shrink-0 rounded-[3px]" :style="{ background: part.fill }" aria-hidden="true" />
        <span class="min-w-0 flex-1 truncate text-fg">{{ part.name }}</span>
        <span class="shrink-0 tabular-nums text-muted">{{ valueText(part.number, valueFormat, ctx) }}</span>
        <span class="w-12 shrink-0 text-right font-semibold tabular-nums text-fg">{{ shareText(share(part.number), fmt.lang.value) }}</span>
      </li>
    </ul>
  </div>
</template>
