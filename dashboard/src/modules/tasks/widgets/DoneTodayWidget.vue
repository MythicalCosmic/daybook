<script setup lang="ts">
/** Overview KPI `tasks.kpi.done_today`: shared tasks finished today out of those due today. */
import { CircleCheck } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { Range } from "@/api/types";
import ErrorState from "@/components/ErrorState.vue";
import KpiCard from "@/components/KpiCard.vue";

import { useSummary } from "../api";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();
const { t } = useI18n();
const query = useSummary();
const data = computed(() => query.data.value);
</script>

<template>
  <ErrorState v-if="query.isError.value" class="ui-card h-full" compact :error="query.error.value" :retry="() => query.refetch()" />
  <KpiCard
    v-else
    class="h-full"
    :icon="CircleCheck"
    :label="t('tasks.kpi.doneToday')"
    :value="data?.done_today ?? null"
    :format="(value: number) => (data ? t('tasks.widget.ofTotal', { done: value, total: data.total_today }) : String(value))"
    :hint="t('tasks.widget.doneHint')"
    :loading="query.isPending.value"
    :to="`/c/${props.companyId}/tasks?sv=today`"
  />
</template>
