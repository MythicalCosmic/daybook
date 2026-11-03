<script setup lang="ts">
/**
 * An agent's tokens (its page's "Tokenlar"): the last 30 days as stacked bars of input and output
 * tokens, the month's totals (calls, input, output, read from the cache, the cost) and, for people
 * who set up AI, this agent's share of the company's AI spending this month and the company's
 * spending against its budget. Cost is "hidden" for the others, never 0.
 */
import { KeyRound, Lock } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import BarChart from "@/components/BarChart.vue";
import ChartCard, { type ChartCsv } from "@/components/ChartCard.vue";
import { shareText } from "@/components/chartCard";
import InlineAlert from "@/components/InlineAlert.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import { useFormat } from "@/lib/useFormat";

import { monthShare, tokensText, usdText } from "../agentPage";
import type { AgentDetail, AgentUsageDay, ClaudeState } from "../types";

const props = defineProps<{ agent: AgentDetail; claude: ClaudeState | null }>();

const { t } = useI18n();
const fmt = useFormat();

const days = computed(() => props.agent.usage.days);
const month = computed(() => props.agent.usage.month);
const hasTokens = computed(() => days.value.some((day) => day.input_tokens > 0 || day.output_tokens > 0));
const series = computed(() => [
  // The chart theme's validated palette, in its fixed order (no colours of our own).
  { name: t("ai.agent.tokens.input"), data: days.value.map((day) => day.input_tokens) },
  { name: t("ai.agent.tokens.output"), data: days.value.map((day) => day.output_tokens) },
]);
const share = computed(() => monthShare(props.agent.usage));
const hidden = computed(() => month.value.cost_usd === null);

const totals = computed(() => [
  { id: "calls", label: t("ai.agent.tokens.calls"), value: fmt.number(month.value.calls) },
  { id: "input", label: t("ai.agent.tokens.input"), value: tokensText(month.value.input_tokens, fmt.lang.value) },
  { id: "output", label: t("ai.agent.tokens.output"), value: tokensText(month.value.output_tokens, fmt.lang.value) },
  { id: "cache", label: t("ai.agent.tokens.cache"), value: tokensText(month.value.cache_read_tokens, fmt.lang.value) },
  { id: "cost", label: t("ai.agent.tokens.cost"), value: usdText(month.value.cost_usd) ?? t("ai.agent.hidden") },
]);

const csv = computed<ChartCsv<AgentUsageDay>>(() => ({
  filename: `${props.agent.key}-tokens`,
  columns: [
    { key: "date", label: t("ai.agent.tokens.day"), value: (row) => row.date },
    { key: "calls", label: t("ai.agent.tokens.calls"), value: (row) => row.calls },
    { key: "input", label: t("ai.agent.tokens.input"), value: (row) => row.input_tokens },
    { key: "output", label: t("ai.agent.tokens.output"), value: (row) => row.output_tokens },
    ...(hidden.value ? [] : [{ key: "cost", label: t("ai.agent.tokens.cost"), value: (row: AgentUsageDay) => row.cost_usd ?? "" }]),
  ],
  rows: days.value,
}));
</script>

<template>
  <div class="flex flex-col gap-4" data-testid="agent-usage">
    <InlineAlert v-if="claude === 'not_configured'" tone="info" :icon="KeyRound" :title="t('ai.key.title')" :description="t('ai.agent.tokens.noKey')" />

    <ChartCard
      :title="t('ai.agent.tokens.chart')"
      :subtitle="t('ai.agent.tokens.chartHint')"
      :empty="!hasTokens"
      :empty-text="t('ai.agent.tokens.empty')"
      :csv="csv as ChartCsv<never>"
      height="240px"
    >
      <BarChart :categories="days.map((day) => day.date)" :series="series" stacked integer x-format="day" height="240px" :label="t('ai.agent.tokens.chart')" />
    </ChartCard>

    <div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <section class="ui-card p-4 md:p-5" :aria-label="t('ai.agent.tokens.month')">
        <h3 class="text-sm font-semibold text-fg">{{ t("ai.agent.tokens.month") }}</h3>
        <dl class="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 lg:grid-cols-2 xl:grid-cols-3">
          <div v-for="item in totals" :key="item.id" class="min-w-0" :data-total="item.id">
            <dt class="truncate text-xs font-medium text-muted">{{ item.label }}</dt>
            <dd :class="['num mt-0.5 flex items-center gap-1.5 text-lg font-semibold', item.id === 'cost' && hidden ? 'text-muted' : 'text-fg']">
              <Lock v-if="item.id === 'cost' && hidden" :size="14" aria-hidden="true" />{{ item.value }}
            </dd>
          </div>
        </dl>
        <p v-if="hidden" class="mt-3 text-xs text-muted">{{ t("ai.agent.kpi.costHidden") }}</p>
      </section>

      <section v-if="share" class="ui-card flex flex-col gap-4 p-4 md:p-5" :aria-label="t('ai.agent.tokens.share')" data-testid="agent-share">
        <h3 class="text-sm font-semibold text-fg">{{ t("ai.agent.tokens.share") }}</h3>
        <div class="flex flex-col gap-1">
          <ProgressBar :value="share.share ?? 0" :max="100" size="md" :label="t('ai.agent.tokens.ofCompany')" :value-text="share.share === null ? '—' : shareText(share.share, fmt.lang.value)" />
          <p class="num text-xs text-muted">{{ t("ai.agent.tokens.ofCompanyHint", { agent: usdText(share.agent), company: usdText(share.company) }) }}</p>
        </div>
        <div class="flex flex-col gap-1">
          <ProgressBar
            :value="share.company"
            :max="share.budget || 1"
            size="md"
            tone="auto"
            :label="t('ai.agent.tokens.budget')"
            :value-text="share.budgetShare === null ? '—' : shareText(share.budgetShare, fmt.lang.value)"
          />
          <p class="num text-xs text-muted">{{ t("ai.agent.tokens.budgetHint", { spent: usdText(share.company), budget: usdText(share.budget) }) }}</p>
        </div>
      </section>
    </div>
  </div>
</template>
