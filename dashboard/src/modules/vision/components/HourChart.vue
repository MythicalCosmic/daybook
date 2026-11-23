<script setup lang="ts">
/**
 * Hour by hour: visitors (bars) against receipts (the line), the longest wait as a heat strip and
 * who stood at the counter against who was checked in, on the same hours, with a key under it.
 * Draws through the shared ECharts loader, themed from the tokens.
 */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { EChartAsync } from "@/components/chartCard";
import { useChartTheme } from "@/components/useChartTheme";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useFormat } from "@/lib/useFormat";

import { formatSeconds } from "../lib/format";
import { hourChartOption } from "../lib/hourChart";
import type { HourRow } from "../types";

const props = defineProps<{ hours: HourRow[]; queueWaitS: number; partialHour: number | null; height?: string }>();

const { t } = useI18n();
const fmt = useFormat();
const { isPhone } = useBreakpoints();
const host = ref<HTMLElement | null>(null);
const theme = useChartTheme(host);

const option = computed(() =>
  hourChartOption(
    theme.value,
    { hours: props.hours, queueWaitS: props.queueWaitS, partialHour: props.partialHour, narrow: isPhone.value },
    {
      visitors: t("vision.hours.visitors"),
      receipts: t("vision.hours.receipts"),
      left: t("vision.hours.left"),
      conversion: t("vision.hours.conversion"),
      queue: t("vision.hours.queue"),
      wait: t("vision.hours.wait"),
      waitRow: t("vision.hours.waitRow"),
      staffRow: t("vision.hours.staffRow"),
      atCounter: t("vision.hours.atCounter"),
      onShift: t("vision.hours.onShift"),
      unattended: t("vision.hours.unattended"),
      partial: t("vision.hours.partial"),
      number: (value, decimals = 0) => fmt.number(value, decimals),
      percent: (value) => fmt.percent(value),
      seconds: (value) => formatSeconds(value, fmt.lang.value),
      minutes: (value) => t("vision.hours.minutes", { n: value }),
    },
  ),
);
const label = computed(() => `${t("vision.hours.title")}: ${props.hours.map((row) => `${row.hour}:00 ${row.visitors ?? 0}/${row.receipts ?? 0}`).join(", ")}`);
</script>

<template>
  <div ref="host" class="flex flex-col gap-2">
    <EChartAsync :option="option" :height="height ?? (isPhone ? '300px' : '320px')" :label="label" />
    <ul class="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-1 text-xs text-muted">
      <li class="inline-flex items-center gap-1.5"><span class="koz-swatch bg-[color-mix(in_srgb,var(--c-success)_22%,transparent)]" />{{ t("vision.hours.calm") }}</li>
      <li class="inline-flex items-center gap-1.5"><span class="koz-swatch bg-[color-mix(in_srgb,var(--c-warning)_60%,transparent)]" />{{ t("vision.hours.long") }}</li>
      <li class="inline-flex items-center gap-1.5"><span class="koz-swatch bg-[color-mix(in_srgb,var(--c-danger)_82%,transparent)]" />{{ t("vision.hours.over") }}</li>
      <li class="inline-flex items-center gap-1.5"><span class="koz-swatch bg-[color-mix(in_srgb,var(--c-warning)_65%,transparent)]" />{{ t("vision.hours.staffGap") }}</li>
    </ul>
  </div>
</template>

<style scoped>
.koz-swatch {
  width: 14px;
  height: 10px;
  border-radius: 3px;
}
</style>
