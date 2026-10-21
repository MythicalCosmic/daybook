<script setup lang="ts">
/** Overview KPI `tasks.kpi.on_time`: the 7-day on-time rate against the 7 days before. */
import { Timer } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { Range } from "@/api/types";
import KpiCard from "@/components/KpiCard.vue";

import { useSummary } from "../api";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();
const { t } = useI18n();
const query = useSummary();
const data = computed(() => query.data.value);
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
    :spark="data?.series.map((point) => point.on_time_percent) ?? []"
    :loading="query.isPending.value"
    :to="`/c/${props.companyId}/reports/team?preset=week&compare=prev`"
  />
</template>
