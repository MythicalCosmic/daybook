<script setup lang="ts">
/**
 * Routine compliance (plan §6.2): every routine with what it made over the range, how much was
 * done on time, late or missed, and the routines nobody does, worst first.
 */
import { ChevronRight, TriangleAlert } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import ChartCard from "@/components/ChartCard.vue";
import DataTable from "@/components/DataTable.vue";
import KpiCard from "@/components/KpiCard.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import type { TableColumn } from "@/components/table";
import { useChartTheme } from "@/components/useChartTheme";
import { useDataTable } from "@/components/useDataTable";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useFormat } from "@/lib/useFormat";
import { usePermission } from "@/lib/usePermission";
import { useRangeState } from "@/lib/useRangeState";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useRoutineReport } from "../api";
import ReportToolbar from "../components/ReportToolbar.vue";
import ScaledChart from "../components/ScaledChart.vue";
import type { RoutineRow } from "../types";

const { t } = useI18n();
const { isPhone } = useBreakpoints();
const chart = useChartTheme();
const fmt = useFormat();
const company = useCompanyStore();
const { can } = usePermission();

const period = useRangeState({ preset: "last_30", compare: "prev" });
const branches = useRouteState("branch", rs.list());
const query = useRoutineReport(period, branches);
const data = computed(() => query.data.value);

const tabs = computed(() => [
  { id: "team", label: t("reports.tabs.team"), to: { name: "reports.team" } },
  { id: "routines", label: t("reports.tabs.routines"), to: { name: "reports.routines" } },
]);

const kpis = computed(() => {
  const totals = data.value?.totals;
  const previous = data.value?.previous;
  return [
    { id: "on_time", label: t("reports.kpi.onTime"), value: totals?.on_time_percent ?? null, previous: previous?.on_time_percent ?? null, format: "percent" as const, points: true },
    { id: "completion", label: t("reports.kpi.completion"), value: totals?.completion_percent ?? null, previous: previous?.completion_percent ?? null, format: "percent" as const, points: true },
    { id: "made", label: t("reports.kpi.made"), value: totals?.made ?? null, previous: previous?.made ?? null },
    { id: "missed", label: t("reports.kpi.missed"), value: totals?.missed ?? null, previous: previous?.missed ?? null, inverse: true },
    { id: "idle", label: t("reports.kpi.idle"), value: totals?.idle ?? null, inverse: true, hint: t("reports.kpi.idleHint") },
  ];
});

const worst = computed(() => [...(data.value?.breakdown ?? [])].filter((row) => row.made > 0).sort((a, b) => (a.on_time_percent ?? 0) - (b.on_time_percent ?? 0)).slice(0, 10));
const chartSeries = computed(() => [
  { name: t("reports.kpi.onTimeShort"), data: worst.value.map((r) => r.on_time), color: chart.value.success, stack: "all" },
  { name: t("reports.kpi.late"), data: worst.value.map((r) => r.late), color: chart.value.warning, stack: "all" },
  { name: t("reports.kpi.missed"), data: worst.value.map((r) => r.missed), color: chart.value.danger, stack: "all" },
]);

const table = useDataTable({ id: "reports.routines", ordering: "on_time_percent", url: true, pageSize: 200 });
const rows = computed(() => {
  const ordering = table.ordering.value || "on_time_percent";
  const field = ordering.replace(/^-/, "") as keyof RoutineRow;
  const direction = ordering.startsWith("-") ? -1 : 1;
  const value = (row: RoutineRow) => (field === "title" ? row.title.toLowerCase() : ((row[field] as number | null) ?? (direction > 0 ? 1e9 : -1)));
  return [...(data.value?.breakdown ?? [])].sort((a, b) => {
    if ((a.made === 0) !== (b.made === 0)) return a.made === 0 ? -1 : 1; // routines nobody does first
    const left = value(a);
    const right = value(b);
    return (left < right ? -1 : left > right ? 1 : 0) * direction;
  });
});
const columns = computed<TableColumn<RoutineRow>[]>(() => [
  { id: "title", header: t("reports.col.routine"), sortable: true, minWidth: 240, sticky: true, hideable: false },
  { id: "branch", header: t("reports.col.branch"), width: 130, value: (row) => row.branch ?? "" },
  { id: "made", header: t("reports.kpi.made"), sortable: true, numeric: true, width: 90 },
  { id: "on_time", header: t("reports.kpi.onTimeShort"), sortable: true, numeric: true, width: 100 },
  { id: "late", header: t("reports.kpi.late"), sortable: true, numeric: true, width: 90 },
  { id: "missed", header: t("reports.kpi.missed"), sortable: true, numeric: true, width: 100 },
  { id: "on_time_percent", header: t("reports.kpi.onTime"), sortable: true, width: 230, value: (row) => row.on_time_percent },
  { id: "completion_percent", header: t("reports.kpi.completion"), sortable: true, numeric: true, width: 120, value: (row) => row.completion_percent },
  { id: "people", header: t("reports.col.people"), sortable: true, numeric: true, width: 90 },
]);
const tone = (value: number | null) => (value === null ? "neutral" : value >= 90 ? "success" : value >= 75 ? "warning" : "danger");
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <PageHeader :title="t('reports.title')" :description="t('reports.routinesDescription')" :tabs="tabs" />
    <ReportToolbar v-model:period="period" v-model:branches="branches" />
    <div v-if="isPhone" class="grid grid-cols-2 gap-2">
      <KpiCard v-for="(item, index) in kpis" :key="index" v-bind="{ ...item, spark: undefined, hint: undefined }" :loading="query.isPending.value" />
    </div>
    <KpiStrip v-else :items="kpis" :loading="query.isPending.value" :columns="5" />

    <ChartCard
      :title="t('reports.chart.worstRoutines')"
      :subtitle="data ? fmt.range(data.range) : undefined"
      :loading="query.isPending.value"
      :error="query.error.value"
      :retry="() => query.refetch()"
      :empty="!worst.length"
      :empty-text="t('reports.chart.empty')"
    >
      <ScaledChart type="bar" :categories="worst.map((r) => r.title)" :series="chartSeries" stacked horizontal integer :height="`${Math.max(200, worst.length * 30 + 40)}px`" />
    </ChartCard>

    <DataTable
      :state="table"
      :columns="columns"
      :rows="rows"
      :total="rows.length"
      row-key="id"
      :loading="query.isPending.value"
      :fetching="query.isFetching.value"
      :error="query.error.value"
      :retry="() => query.refetch()"
      :empty-title="t('reports.routinesEmptyTitle')"
      :empty-description="t('reports.routinesEmptyBody')"
      :csv-name="t('reports.tabs.routines')"
      hide-pagination
    >
      <template #cell-title="{ row }">
        <div class="flex min-w-0 items-center gap-2">
          <TriangleAlert v-if="row.made === 0" :size="14" class="shrink-0 text-warning" :title="t('reports.idle')" />
          <RouterLink v-if="can('tasks.templates')" :to="`/c/${company.currentId}/routines/${row.id}`" class="min-w-0 truncate font-medium text-fg hover:underline">{{ row.title }}</RouterLink>
          <span v-else class="min-w-0 truncate font-medium text-fg">{{ row.title }}</span>
          <span v-if="!row.is_active" class="shrink-0 rounded-full bg-surface-2 px-1.5 text-[11px] text-muted">{{ t("reports.paused") }}</span>
        </div>
      </template>
      <template #cell-branch="{ row }"><span class="text-sm text-muted">{{ row.branch ?? t("reports.everyBranch") }}</span></template>
      <template #cell-on_time="{ row }"><span class="tabular-nums text-success">{{ row.on_time }}</span></template>
      <template #cell-late="{ row }"><span :class="['tabular-nums', row.late ? 'text-warning' : 'text-subtle']">{{ row.late }}</span></template>
      <template #cell-missed="{ row }"><span :class="['tabular-nums', row.missed ? 'text-danger' : 'text-subtle']">{{ row.missed }}</span></template>
      <template #cell-on_time_percent="{ row }">
        <span v-if="row.made === 0" class="text-sm font-medium text-warning">{{ t("reports.idle") }}</span>
        <span v-else class="flex min-w-0 items-center gap-2">
          <ProgressBar class="flex-1" :value="row.on_time_percent ?? 0" :tone="tone(row.on_time_percent)" />
          <span class="w-11 text-right text-sm font-semibold tabular-nums text-fg">{{ fmt.percent(row.on_time_percent, 0) }}</span>
        </span>
      </template>
      <template #cell-completion_percent="{ row }"><span class="tabular-nums text-muted">{{ fmt.percent(row.completion_percent, 0) }}</span></template>
      <template #card="{ row }">
        <RouterLink :to="`/c/${company.currentId}/routines/${row.id}`" class="flex min-w-0 items-center gap-3">
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-semibold text-fg">{{ row.title }}</p>
            <p class="mt-0.5 text-xs text-muted">{{ row.made === 0 ? t("reports.idle") : t("reports.card", { total: row.made, late: row.late, missed: row.missed }) }}</p>
          </div>
          <span class="text-md font-semibold tabular-nums text-fg">{{ row.made ? fmt.percent(row.on_time_percent, 0) : "—" }}</span>
          <ChevronRight :size="16" class="text-subtle" />
        </RouterLink>
      </template>
    </DataTable>
  </div>
</template>
