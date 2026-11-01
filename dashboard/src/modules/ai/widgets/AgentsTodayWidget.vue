<script setup lang="ts">
/** Overview KPI `ai.kpi.today`: what the AI agents did today, all agents together; opens their activity. */
import { Bot } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { Range } from "@/api/types";
import KpiCard from "@/components/KpiCard.vue";

import { useAgents, useAiStatus } from "../api";
import { isMissingEndpoint } from "../lib";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();
const { t } = useI18n();
const status = useAiStatus();
const agents = useAgents();
const today = computed(() => (agents.data.value ? agents.data.value.reduce((sum, agent) => sum + agent.stats.today, 0) : null));
const week = computed(() => agents.data.value?.reduce((sum, agent) => sum + agent.stats.week, 0) ?? 0);
const missing = computed(() => agents.isError.value && isMissingEndpoint(agents.error.value));
const hint = computed(() => {
  if (status.data.value && !status.data.value.enabled) return t("ai.kpi.off");
  if (missing.value) return t("ai.kpi.soon");
  return t("ai.kpi.week", { n: week.value }, week.value);
});
</script>

<template>
  <KpiCard
    :error="agents.isError.value && !missing ? agents.error.value : undefined"
    :retry="() => agents.refetch()"
    class="h-full"
    :icon="Bot"
    :label="t('ai.kpi.today')"
    :value="today"
    :format="(value: number) => t('ai.kpi.actions', { n: value }, value)"
    :hint="hint"
    :loading="agents.isPending.value"
    :to="`/c/${props.companyId}/ai/activity`"
  />
</template>
