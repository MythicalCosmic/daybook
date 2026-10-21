<script setup lang="ts">
/** Overview KPI `tasks.kpi.done_today`: one-off tasks finished today out of those due today (routines have their own tile). */
import { CircleCheck } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { Range } from "@/api/types";
import KpiCard from "@/components/KpiCard.vue";

import { useSummary } from "../api";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();
const { t } = useI18n();
const query = useSummary({ routines: "without" });
const data = computed(() => query.data.value);
</script>

<template>
  <KpiCard
    :error="query.isError.value ? query.error.value : undefined"
    :retry="() => query.refetch()"
    class="h-full"
    :icon="CircleCheck"
    :label="t('tasks.kpi.doneToday')"
    :value="data?.done_today ?? null"
    :format="(value: number) => (data ? t('tasks.widget.ofTotal', { done: value, total: data.total_today }) : String(value))"
    :hint="t('tasks.kpi.doneTodayHintOneOff')"
    :loading="query.isPending.value"
    :to="`/c/${props.companyId}/tasks?sv=today`"
  />
</template>
