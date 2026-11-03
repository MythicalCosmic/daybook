<script setup lang="ts">
/**
 * An agent's internal log (its page's "Ichki jurnal"): its runs, newest first (when, how long, how
 * it went, how much it did, the tokens and the cost, the error), then the Claude calls it made
 * (model, tokens, cache, how long, why it stopped; never a prompt or an answer). Money and error
 * texts only for people who set up AI. Phones get a card per row.
 */
import { Cpu, History, KeyRound } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import { useDataTable } from "@/components/useDataTable";
import { useFormat } from "@/lib/useFormat";

import { durationText, isScheduled, RUN_TONE, tokensText, usdText } from "../agentPage";
import type { AgentCall, AgentDetail, AgentRun, ClaudeState } from "../types";

const props = defineProps<{ agent: AgentDetail; canConfigure: boolean; claude: ClaudeState | null }>();

const { t } = useI18n();
const fmt = useFormat();
const runTable = useDataTable({ id: "ai.agent.runs", pageSize: 30 });
const callTable = useDataTable({ id: "ai.agent.calls", pageSize: 30 });

const tokens = (input: number, output: number) => `${tokensText(input, fmt.lang.value)} / ${tokensText(output, fmt.lang.value)}`;
const cost = (value: string | null) => usdText(value, true) ?? "—";
const when = (iso: string) => fmt.instant(iso, "short");

const runColumns = computed<TableColumn<AgentRun>[]>(() => {
  const list: TableColumn<AgentRun>[] = [
    { id: "started_at", header: t("ai.agent.log.when"), width: 168, hideable: false, format: (value) => when(String(value)) },
    { id: "duration_ms", header: t("ai.agent.log.took"), width: 104, numeric: true, format: (value) => durationText(value as number | null, fmt.lang.value) },
    { id: "status", header: t("ai.agent.log.status"), width: 132 },
    { id: "done", header: t("ai.agent.log.done"), width: 92, numeric: true, format: (value) => fmt.number(value as number) },
    { id: "tokens", header: t("ai.agent.log.tokens"), hint: t("ai.agent.log.tokensHint"), minWidth: 140, numeric: true, value: (row) => tokens(row.input_tokens, row.output_tokens) },
  ];
  if (props.canConfigure) {
    list.push({ id: "cost_usd", header: t("ai.agent.log.cost"), width: 104, numeric: true, format: (value) => cost(value as string | null) });
    list.push({ id: "error", header: t("ai.agent.log.error"), minWidth: 200, format: (value) => (value ? String(value) : "") });
  }
  return list;
});

const callColumns = computed<TableColumn<AgentCall>[]>(() => {
  const list: TableColumn<AgentCall>[] = [
    { id: "at", header: t("ai.agent.log.when"), width: 168, hideable: false, format: (value) => when(String(value)) },
    { id: "model", header: t("ai.agent.log.model"), minWidth: 170 },
    { id: "tokens", header: t("ai.agent.log.tokens"), hint: t("ai.agent.log.tokensHint"), minWidth: 140, numeric: true, value: (row) => tokens(row.input_tokens, row.output_tokens) },
    { id: "cache_read_tokens", header: t("ai.agent.log.cache"), width: 104, numeric: true, format: (value) => tokensText(value as number, fmt.lang.value) },
    { id: "latency_ms", header: t("ai.agent.log.took"), width: 96, numeric: true, format: (value) => durationText(value as number | null, fmt.lang.value) },
    { id: "stop_reason", header: t("ai.agent.log.stop"), width: 124 },
  ];
  if (props.canConfigure) list.push({ id: "cost_usd", header: t("ai.agent.log.cost"), width: 104, numeric: true, format: (value) => cost(value as string | null) });
  return list;
});

/** Why there is no run to show: an agent that works as things arrive never runs on a schedule. */
const noRuns = computed(() =>
  isScheduled(props.agent)
    ? { title: t("ai.agent.log.neverRan"), body: t("ai.agent.log.neverRanBody") }
    : { title: t("ai.agent.log.noSchedule"), body: t("ai.agent.log.noScheduleBody", { when: props.agent.schedule }) },
);
const noCalls = computed(() => (props.claude === "not_configured" ? t("ai.agent.log.noCallsKey") : props.agent.needs_claude ? t("ai.agent.log.noCallsBody") : t("ai.agent.log.noCallsRules")));
</script>

<template>
  <div class="flex flex-col gap-6" data-testid="agent-log">
    <section class="flex flex-col gap-3" :aria-label="t('ai.agent.log.runs')">
      <div class="flex items-baseline justify-between gap-3 px-1">
        <h3 class="text-md font-semibold text-fg">{{ t("ai.agent.log.runs") }}</h3>
        <span v-if="agent.runs.length" class="text-sm text-muted">{{ t("ai.agent.log.newest", { n: agent.runs.length }) }}</span>
      </div>
      <EmptyState v-if="!agent.runs.length" class="ui-card" size="sm" tone="neutral" :icon="History" :title="noRuns.title" :description="noRuns.body" data-testid="agent-no-runs" />
      <DataTable v-else :state="runTable" :columns="runColumns" :rows="agent.runs" row-key="id" hide-toolbar hide-pagination max-height="560px" :caption="t('ai.agent.log.runs')">
        <template #cell-started_at="{ row }">
          <span class="flex min-w-0 items-center gap-1.5">
            <span class="num truncate">{{ when(row.started_at) }}</span>
            <span v-if="row.forced" class="shrink-0 rounded-full bg-surface-2 px-1.5 py-px text-[11px] font-medium text-muted dark:bg-surface-3">{{ t("ai.agent.log.forced") }}</span>
          </span>
        </template>
        <template #cell-status="{ row }">
          <StatusPill :tone="RUN_TONE[row.status]" size="sm" :live="row.status === 'running'" :label="t(`ai.agent.run.${row.status}`)" />
        </template>
        <template #cell-error="{ row }">
          <span v-if="row.error" class="block truncate text-sm text-danger" :title="row.error">{{ row.error }}</span>
          <span v-else class="text-subtle">—</span>
        </template>
        <template #card="{ row }">
          <div class="flex flex-col gap-1.5" data-testid="agent-run-card">
            <div class="flex items-center justify-between gap-3">
              <span class="num text-sm font-semibold text-fg">{{ when(row.started_at) }}</span>
              <StatusPill :tone="RUN_TONE[row.status]" size="sm" :live="row.status === 'running'" :label="t(`ai.agent.run.${row.status}`)" />
            </div>
            <p class="num flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted">
              <span>{{ t("ai.agent.log.took") }}: {{ durationText(row.duration_ms, fmt.lang.value) }}</span>
              <span>{{ t("ai.agent.log.done") }}: {{ fmt.number(row.done) }}</span>
              <span>{{ t("ai.agent.log.tokens") }}: {{ tokens(row.input_tokens, row.output_tokens) }}</span>
              <span v-if="canConfigure">{{ t("ai.agent.log.cost") }}: {{ cost(row.cost_usd) }}</span>
              <span v-if="row.forced">{{ t("ai.agent.log.forced") }}</span>
            </p>
            <p v-if="row.error" class="text-xs text-danger">{{ row.error }}</p>
          </div>
        </template>
      </DataTable>
    </section>

    <section class="flex flex-col gap-3" :aria-label="t('ai.agent.log.calls')">
      <div class="flex flex-col gap-0.5 px-1">
        <h3 class="text-md font-semibold text-fg">{{ t("ai.agent.log.calls") }}</h3>
        <p class="text-sm text-muted">{{ t("ai.agent.log.callsHint") }}</p>
      </div>
      <InlineAlert v-if="claude === 'not_configured' && agent.calls.length" tone="info" :icon="KeyRound" :description="t('ai.agent.log.noCallsKey')" />
      <EmptyState v-if="!agent.calls.length" class="ui-card" size="sm" tone="neutral" :icon="Cpu" :title="t('ai.agent.log.noCalls')" :description="noCalls" data-testid="agent-no-calls" />
      <DataTable v-else :state="callTable" :columns="callColumns" :rows="agent.calls" :row-key="(row) => `${row.at}:${row.model}:${row.input_tokens}:${row.output_tokens}`" hide-toolbar hide-pagination max-height="560px" :caption="t('ai.agent.log.calls')">
        <template #cell-model="{ row }"><span class="block truncate font-mono text-sm text-fg" :title="row.model">{{ row.model }}</span></template>
        <template #cell-stop_reason="{ row }"><span class="block truncate font-mono text-xs text-muted" :title="row.stop_reason">{{ row.stop_reason || "—" }}</span></template>
        <template #card="{ row }">
          <div class="flex flex-col gap-1.5">
            <div class="flex items-center justify-between gap-3">
              <span class="num text-sm font-semibold text-fg">{{ when(row.at) }}</span>
              <span class="truncate font-mono text-xs text-muted">{{ row.model }}</span>
            </div>
            <p class="num flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted">
              <span>{{ t("ai.agent.log.tokens") }}: {{ tokens(row.input_tokens, row.output_tokens) }}</span>
              <span>{{ t("ai.agent.log.cache") }}: {{ tokensText(row.cache_read_tokens, fmt.lang.value) }}</span>
              <span>{{ t("ai.agent.log.took") }}: {{ durationText(row.latency_ms, fmt.lang.value) }}</span>
              <span v-if="canConfigure">{{ t("ai.agent.log.cost") }}: {{ cost(row.cost_usd) }}</span>
            </p>
          </div>
        </template>
      </DataTable>
    </section>
  </div>
</template>
