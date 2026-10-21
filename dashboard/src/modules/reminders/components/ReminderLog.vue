<script setup lang="ts">
/**
 * The reminder log (plan §1.3): every heads-up, reminder, escalation and "blocked the bot" notice,
 * newest first, with who got it, for which task, and whether it arrived. Filters in the URL.
 */
import { AlarmClock, BellRing, CircleCheck, CircleX, Siren, UserX } from "@lucide/vue";
import { computed, watch } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import FilterBar from "@/components/FilterBar.vue";
import { useUrlFilters, type FilterDef } from "@/components/filters";
import PersonCell from "@/components/PersonCell.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import { useDataTable } from "@/components/useDataTable";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useReminderLog } from "../api";
import type { LogKind, LogRow } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();

const defs = computed<FilterDef[]>(() => [
  {
    key: "kind",
    label: t("reminders.log.kind"),
    type: "select",
    icon: BellRing,
    options: (["reminder", "escalation", "heads_up", "blocked"] as LogKind[]).map((kind) => ({ value: kind, label: t(`reminders.log.kinds.${kind}`) })),
  },
  { key: "delivered", label: t("reminders.log.delivered"), type: "boolean", icon: CircleCheck, trueLabel: t("reminders.log.arrived"), falseLabel: t("reminders.log.failed") },
  { key: "sent", label: t("reminders.log.when"), type: "date-range", params: ["from", "to"] },
]);
const filters = useUrlFilters(defs);
const search = useRouteState("q", rs.string(""));
const table = useDataTable({ id: "reminders.log", url: "log_", pageSize: 50 });
const params = computed(() => ({ ...filters.params.value, ...(search.value ? { q: search.value } : {}), page: table.page.value, page_size: table.pageSize.value }));
watch(() => JSON.stringify([filters.params.value, search.value]), () => table.resetPage());
const query = useReminderLog(params);

const icons = { heads_up: AlarmClock, reminder: BellRing, escalation: Siren, blocked: UserX } as const;
const tones = { heads_up: "info", reminder: "warning", escalation: "danger", blocked: "neutral" } as const;

const columns = computed<TableColumn<LogRow>[]>(() => [
  { id: "sent_at", header: t("reminders.log.when"), width: 170, value: (row) => row.sent_at, csv: (row) => fmt.instant(row.sent_at) },
  { id: "kind", header: t("reminders.log.kind"), width: 170, value: (row) => t(`reminders.log.kinds.${row.kind}`) },
  { id: "recipient", header: t("reminders.log.to"), width: 210, value: (row) => row.recipient?.name ?? "" },
  { id: "task", header: t("reminders.log.task"), minWidth: 240, value: (row) => row.task.title },
  { id: "branch", header: t("reminders.log.branch"), width: 130, value: (row) => row.branch?.name ?? "" },
  { id: "delivered", header: t("reminders.log.delivered"), width: 150, value: (row) => (row.delivered ? t("reminders.log.arrived") : row.error || t("reminders.log.failed")) },
]);
</script>

<template>
  <div class="flex flex-col gap-3">
    <FilterBar v-model="filters.values.value" v-model:search="search" :defs="defs" searchable :search-placeholder="t('reminders.log.search')" />
    <DataTable
      :state="table"
      :columns="columns"
      :rows="query.data.value?.results"
      :total="query.data.value?.count"
      row-key="id"
      :loading="query.isPending.value"
      :fetching="query.isFetching.value"
      :error="query.error.value"
      :retry="() => query.refetch()"
      :filtered="filters.active.value > 0 || !!search"
      :empty-title="t('reminders.log.emptyTitle')"
      :empty-description="t('reminders.log.emptyBody')"
      :csv-name="t('reminders.log.title')"
      hide-toolbar
      @clear-filters="filters.clear(), (search = '')"
    >
      <template #cell-sent_at="{ row }"><span class="text-sm tabular-nums text-muted">{{ fmt.instant(row.sent_at, "short") }}</span></template>
      <template #cell-kind="{ row }">
        <StatusPill :tone="tones[row.kind]" size="sm" :icon="icons[row.kind]" :dot="false" :label="row.step && row.kind !== 'heads_up' ? `${t(`reminders.log.kinds.${row.kind}`)} #${row.step}` : t(`reminders.log.kinds.${row.kind}`)" />
      </template>
      <template #cell-recipient="{ row }"><PersonCell :person="row.recipient" :subtitle="row.recipient?.position" size="sm" link /></template>
      <template #cell-task="{ row }">
        <RouterLink :to="`/c/${company.currentId}/tasks?task=${row.task.id}`" class="block truncate text-sm font-medium text-fg hover:underline" @click.stop>{{ row.task.title }}</RouterLink>
      </template>
      <template #cell-branch="{ row }"><span class="text-sm text-muted">{{ row.branch?.name ?? "—" }}</span></template>
      <template #cell-delivered="{ row }">
        <span v-if="row.delivered" class="inline-flex items-center gap-1 text-sm text-success"><CircleCheck :size="14" />{{ t("reminders.log.arrived") }}</span>
        <span v-else class="inline-flex min-w-0 items-center gap-1 text-sm text-danger" :title="row.error"><CircleX :size="14" class="shrink-0" /><span class="truncate">{{ row.error === "blocked the bot" ? t("reminders.log.blockedError") : row.error || t("reminders.log.failed") }}</span></span>
      </template>
      <template #card="{ row }">
        <div class="flex min-w-0 items-start gap-3">
          <component :is="icons[row.kind]" :size="16" :class="['mt-0.5 shrink-0', row.kind === 'escalation' ? 'text-danger' : row.kind === 'heads_up' ? 'text-info' : 'text-warning']" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-semibold text-fg">{{ row.task.title }}</p>
            <p class="truncate text-xs text-muted">{{ t(`reminders.log.kinds.${row.kind}`) }}<template v-if="row.step && row.kind !== 'heads_up'"> #{{ row.step }}</template> · {{ row.recipient?.name }} · {{ fmt.instant(row.sent_at, "short") }}</p>
          </div>
          <CircleCheck v-if="row.delivered" :size="15" class="shrink-0 text-success" />
          <CircleX v-else :size="15" class="shrink-0 text-danger" />
        </div>
      </template>
    </DataTable>
  </div>
</template>
