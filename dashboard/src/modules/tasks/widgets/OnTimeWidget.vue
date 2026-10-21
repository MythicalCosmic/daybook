<script setup lang="ts">
/** Overview KPI `tasks.kpi.on_time`: the 7-day on-time rate of one-off tasks against the 7 days before. */
import { Timer } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { Range } from "@/api/types";
import KpiCard from "@/components/KpiCard.vue";

import { useSummary } from "../api";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();
const { t } = useI18n();
const query = useSummary({ routines: "without" });
const data = computed(() => query.data.value);
// Complete days only: today counts just what was due so far, and its dip would read as a fall.
const spark = computed(() => {
  const series = data.value?.series ?? [];
  return (series.at(-1)?.date === data.value?.today ? series.slice(0, -1) : series).map((point) => point.on_time_percent);
});
</script>

<template>
  <KpiCard
    :error="query.isError.value ? query.error.value : undefined"
    :retry="() => query.refetch()"
    class="h-full"
    :icon="Timer"
    :label="t('tasks.kpi.onTime')"
    :value="data?.on_time_percent ?? null"
    :previous="data?.on_time_previous ?? null"
    format="percent"
    points
    :delta-label="t('tasks.kpi.vsWeekBefore')"
    :hint="t('tasks.kpi.reviewHintOneOff')"
    :spark="spark"
    :loading="query.isPending.value"
    :to="`/c/${props.companyId}/reports/team?preset=week&compare=prev`"
  />
</template>
