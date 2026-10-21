<script setup lang="ts">
/** Overview KPI `tasks.kpi.late_now`: open one-off tasks past their deadline right now (routines have their own tile). */
import { AlarmClock } from "@lucide/vue";
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
    :icon="AlarmClock"
    :label="t('tasks.kpi.lateNow')"
    :value="data?.late_now ?? null"
    :hint="t('tasks.kpi.lateNowHintOneOff')"
    :loading="query.isPending.value"
    :to="`/c/${props.companyId}/tasks?sv=late&overdue=true`"
  />
</template>
