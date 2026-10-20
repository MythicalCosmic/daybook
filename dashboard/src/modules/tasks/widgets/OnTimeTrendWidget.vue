<script setup lang="ts">
/** Overview chart `tasks.chart.on_time_trend`: on-time % and finished tasks over 14 days. */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { Range } from "@/api/types";
import ChartCard from "@/components/ChartCard.vue";
import LineChart from "@/components/LineChart.vue";
import { useFormat } from "@/lib/useFormat";

import { useSummary } from "../api";

defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();
const { t } = useI18n();
const fmt = useFormat();
const query = useSummary();
const series = computed(() => query.data.value?.series ?? []);
const categories = computed(() => series.value.map((point) => point.date));
// The headline covers the same 14 days as the line (the KPI tile shows the last 7).
const value = computed(() => {
  const due = series.value.reduce((sum, point) => sum + point.total, 0);
  if (!due) return undefined;
  const onTime = series.value.reduce((sum, point) => sum + point.on_time, 0);
  return fmt.percent(Math.round((1000 * onTime) / due) / 10, 1);
});
const csv = computed(() => ({
  filename: "on-time",
  columns: [
    { key: "date", label: t("tasks.chart.day"), value: (row: (typeof series.value)[number]) => row.date },
    { key: "on_time_percent", label: t("tasks.kpi.onTime"), value: (row: (typeof series.value)[number]) => row.on_time_percent },
    { key: "done", label: t("tasks.chart.done"), value: (row: (typeof series.value)[number]) => row.done },
  ],
  rows: series.value,
}));
</script>

<template>
  <ChartCard
    class="h-full"
    :title="t('tasks.chart.onTimeTrend')"
    :subtitle="t('tasks.chart.last14')"
    :value="value"
    :loading="query.isPending.value"
    :error="query.error.value"
    :retry="() => query.refetch()"
    :empty="!series.some((point) => point.total > 0)"
    :empty-text="t('tasks.chart.empty')"
    :csv="csv as never"
  >
    <LineChart
      :categories="categories"
      :series="[{ name: t('tasks.kpi.onTime'), data: series.map((point) => point.on_time_percent) }]"
      value-format="percent"
      x-format="day"
      height="220px"
      smooth
    />
  </ChartCard>
</template>
