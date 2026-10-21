<script setup lang="ts">
/**
 * Team results (plan §6.2 "Reports (B)"): on time, late and missed over any range with a
 * comparison, grouped by person, position, routine, branch or day, with the trend, the spread and
 * an export. Personal tasks never count.
 */
import { CalendarDays, Repeat, Store, UserRound, Users } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import BarChart from "@/components/BarChart.vue";
import ChartCard from "@/components/ChartCard.vue";
import DataTable from "@/components/DataTable.vue";
import KpiCard from "@/components/KpiCard.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import LineChart from "@/components/LineChart.vue";
import PageHeader from "@/components/PageHeader.vue";
import PersonCell from "@/components/PersonCell.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import type { TableColumn } from "@/components/table";
import { useChartTheme } from "@/components/useChartTheme";
import { useDataTable } from "@/components/useDataTable";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useFormat } from "@/lib/useFormat";
import { useRangeState } from "@/lib/useRangeState";
import { rs, useRouteState } from "@/lib/useRouteState";

import { periodParams, useTeamReport } from "../api";
import ReportToolbar from "../components/ReportToolbar.vue";
import type { GroupBy, TeamRow } from "../types";

const { t } = useI18n();
const chart = useChartTheme();
const fmt = useFormat();
const { isPhone } = useBreakpoints();

const period = useRangeState({ preset: "last_30", compare: "prev" });
const groupBy = useRouteState<GroupBy>("group_by", rs.enum(["member", "position", "routine", "branch", "day"] as const, "member"));
const branches = useRouteState("branch", rs.list());
const query = useTeamReport(period, groupBy, branches);
const data = computed(() => query.data.value);

const tabs = computed(() => [
  { id: "team", label: t("reports.tabs.team"), to: { name: "reports.team" } },
  { id: "routines", label: t("reports.tabs.routines"), to: { name: "reports.routines" } },
]);

const kpis = computed(() => {
  const totals = data.value?.totals;
  const previous = data.value?.previous;
  return [
    { id: "on_time", label: t("reports.kpi.onTime"), value: totals?.on_time_percent ?? null, previous: previous?.on_time_percent ?? null, format: "percent" as const, points: true, spark: data.value?.series.map((p) => p.on_time_percent) ?? [] },
    { id: "done", label: t("reports.kpi.done"), value: totals?.done ?? null, previous: previous?.done ?? null },
    { id: "late", label: t("reports.kpi.late"), value: totals?.late ?? null, previous: previous?.late ?? null, inverse: true },
    { id: "missed", label: t("reports.kpi.missed"), value: totals?.missed ?? null, previous: previous?.missed ?? null, inverse: true },
    { id: "delay", label: t("reports.kpi.delay"), value: totals?.avg_delay_minutes ?? null, previous: previous?.avg_delay_minutes ?? null, format: "duration" as const, inverse: true },
  ];
});

// Trend
const series = computed(() => data.value?.series ?? []);
const trendCategories = computed(() => series.value.map((p) => p.date));

// Spread per group (top 12 by volume)
const spread = computed(() => [...(data.value?.breakdown ?? [])].filter((row) => row.total > 0).sort((a, b) => (groupBy.value === "day" ? a.key.localeCompare(b.key) : b.total - a.total)).slice(0, groupBy.value === "day" ? 62 : 12));
const label = (row: TeamRow) => (groupBy.value === "day" ? row.key : row.label || (groupBy.value === "member" ? t("reports.none") : t(`reports.noneBy.${groupBy.value}`)));
const spreadSeries = computed(() => [
  { name: t("reports.kpi.onTimeShort"), data: spread.value.map((r) => r.on_time), color: chart.value.success, stack: "all" },
  { name: t("reports.kpi.late"), data: spread.value.map((r) => r.late), color: chart.value.warning, stack: "all" },
  { name: t("reports.kpi.missed"), data: spread.value.map((r) => r.missed), color: chart.value.danger, stack: "all" },
]);

// Table (sorted here: every row is on the page)
const table = useDataTable({ id: "reports.team", ordering: "-on_time_percent", url: true, pageSize: 200, hidden: ["reminders"] });
const rows = computed(() => {
  const ordering = table.ordering.value || "-on_time_percent";
  const field = ordering.replace(/^-/, "") as keyof TeamRow;
  const direction = ordering.startsWith("-") ? -1 : 1;
  const value = (row: TeamRow) => (field === "label" ? label(row).toLowerCase() : ((row[field] as number | null) ?? -1));
  return [...(data.value?.breakdown ?? [])].sort((a, b) => {
    const left = value(a);
    const right = value(b);
    return (left < right ? -1 : left > right ? 1 : 0) * direction;
  });
});
const columns = computed<TableColumn<TeamRow>[]>(() => [
  { id: "label", header: t(`reports.group.${groupBy.value}`), sortable: true, minWidth: 220, sticky: true, hideable: false, value: label },
  // Short headers: the full words are in the KPI strip above, and long ones clip in uz/ru.
  { id: "total", header: t("reports.th.due"), sortable: true, numeric: true, width: 90 },
  { id: "on_time", header: t("reports.th.onTime"), sortable: true, numeric: true, width: 120 },
  { id: "late", header: t("reports.th.late"), sortable: true, numeric: true, width: 100 },
  { id: "missed", header: t("reports.th.missed"), sortable: true, numeric: true, width: 130 },
  { id: "on_time_percent", header: t("reports.kpi.onTime"), sortable: true, width: 180, value: (row) => row.on_time_percent },
  { id: "late_now", header: t("reports.th.lateNow"), sortable: true, numeric: true, width: 130 },
  { id: "avg_delay_minutes", header: t("reports.th.delay"), sortable: true, numeric: true, width: 140, value: (row) => row.avg_delay_minutes },
  { id: "reminders", header: t("reports.col.reminders"), sortable: true, numeric: true, width: 120 },
]);
const tone = (value: number | null) => (value === null ? "neutral" : value >= 90 ? "success" : value >= 75 ? "warning" : "danger");
const TONE_TEXT = { neutral: "text-muted", success: "text-success", warning: "text-warning", danger: "text-danger" } as const;
const delta = (row: TeamRow) => (row.on_time_percent !== null && row.previous_on_time_percent !== null ? row.on_time_percent - row.previous_on_time_percent : null);
const exportParams = computed(() => ({ ...periodParams(period.value), group_by: groupBy.value }));

const groupOptions = computed(() => [
  { value: "member" as const, label: t("reports.group.member"), icon: UserRound, iconOnly: isPhone.value },
  { value: "position" as const, label: t("reports.group.position"), icon: Users, iconOnly: isPhone.value },
  { value: "routine" as const, label: t("reports.group.routine"), icon: Repeat, iconOnly: isPhone.value },
  { value: "branch" as const, label: t("reports.group.branch"), icon: Store, iconOnly: isPhone.value },
  { value: "day" as const, label: t("reports.group.day"), icon: CalendarDays, iconOnly: isPhone.value },
]);
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <PageHeader :title="t('reports.title')" :description="t('reports.teamDescription')" :tabs="tabs" />

    <ReportToolbar v-model:period="period" v-model:branches="branches">
      <SegmentedControl v-model="groupBy" size="sm" :options="groupOptions" :aria-label="t('reports.groupBy')" />
    </ReportToolbar>

    <div v-if="isPhone" class="grid grid-cols-2 gap-2">
      <KpiCard v-for="(item, index) in kpis" :key="index" v-bind="{ ...item, spark: undefined, hint: undefined }" :loading="query.isPending.value" />
    </div>
    <KpiStrip v-else :items="kpis" :loading="query.isPending.value" :columns="5" />

    <div class="grid gap-4 xl:grid-cols-2">
      <ChartCard
        :title="t('reports.chart.trend')"
        :subtitle="data ? `${fmt.range(data.range)} · ${t('reports.kpi.onTimeHint')}` : undefined"
        :loading="query.isPending.value"
        :error="query.error.value"
        :retry="() => query.refetch()"
        :empty="!series.some((p) => p.total > 0)"
        :empty-text="t('reports.chart.empty')"
      >
        <LineChart :categories="trendCategories" :series="[{ name: t('reports.kpi.onTime'), data: series.map((p) => p.on_time_percent) }]" value-format="percent" :x-format="series.length > 62 ? 'month' : 'day'" :y-max="100" smooth />
      </ChartCard>
      <ChartCard
        :title="t('reports.chart.spread')"
        :subtitle="t(`reports.chart.by.${groupBy}`)"
        :loading="query.isPending.value"
        :error="query.error.value"
        :retry="() => query.refetch()"
        :empty="!spread.length"
        :empty-text="t('reports.chart.empty')"
      >
        <BarChart :categories="spread.map(label)" :series="spreadSeries" stacked integer :horizontal="groupBy !== 'day'" :x-format="groupBy === 'day' ? 'day' : 'none'" :height="groupBy === 'day' ? '240px' : `${Math.max(200, spread.length * 30 + 40)}px`" />
      </ChartCard>
    </div>

    <DataTable
      :state="table"
      :columns="columns"
      :rows="rows"
      :total="rows.length"
      row-key="key"
      :loading="query.isPending.value"
      :fetching="query.isFetching.value"
      :error="query.error.value"
      :retry="() => query.refetch()"
      :empty-title="t('reports.emptyTitle')"
      :empty-description="t('reports.emptyBody')"
      :csv-name="t('reports.title')"
      export-kind="reports.team"
      :export-params="exportParams"
      hide-pagination
      virtual="auto"
    >
      <template #cell-label="{ row }">
        <PersonCell v-if="row.member" :person="row.member" :subtitle="row.position" size="sm" link />
        <span v-else-if="groupBy === 'day'" class="font-medium text-fg">{{ fmt.day(row.key, "weekday") }}</span>
        <span v-else class="truncate font-medium text-fg">{{ label(row) }}</span>
      </template>
      <template #cell-on_time="{ row }"><span class="tabular-nums text-success">{{ row.on_time }}</span></template>
      <template #cell-late="{ row }"><span :class="['tabular-nums', row.late ? 'text-warning' : 'text-subtle']">{{ row.late }}</span></template>
      <template #cell-missed="{ row }"><span :class="['tabular-nums', row.missed ? 'text-danger' : 'text-subtle']">{{ row.missed }}</span></template>
      <template #cell-on_time_percent="{ row }">
        <span class="flex min-w-0 items-center gap-2">
          <ProgressBar class="flex-1" :value="row.on_time_percent ?? 0" :tone="tone(row.on_time_percent)" />
          <span class="w-11 text-right text-sm font-semibold tabular-nums text-fg">{{ fmt.percent(row.on_time_percent, 0) }}</span>
          <span v-if="delta(row) !== null" :class="['w-12 text-right text-xs tabular-nums', delta(row)! >= 0 ? 'text-success' : 'text-danger']">{{ delta(row)! >= 0 ? "+" : "" }}{{ fmt.number(delta(row), 1) }}</span>
        </span>
      </template>
      <template #cell-late_now="{ row }"><span :class="['tabular-nums', row.late_now ? 'font-semibold text-danger' : 'text-subtle']">{{ row.late_now }}</span></template>
      <template #cell-avg_delay_minutes="{ row }"><span class="tabular-nums text-muted">{{ row.avg_delay_minutes === null ? "—" : fmt.duration(row.avg_delay_minutes) }}</span></template>
      <template #card="{ row }">
        <div class="flex min-w-0 items-center gap-3">
          <div class="min-w-0 flex-1">
            <PersonCell v-if="row.member" :person="row.member" :subtitle="row.position" size="sm" />
            <p v-else class="truncate text-sm font-semibold text-fg">{{ groupBy === "day" ? fmt.day(row.key, "weekday") : label(row) }}</p>
            <p class="mt-1 text-xs text-muted">{{ t("reports.card", { total: row.total, late: row.late, missed: row.missed }) }}</p>
          </div>
          <span :class="['text-md font-semibold tabular-nums', TONE_TEXT[tone(row.on_time_percent)]]">{{ fmt.percent(row.on_time_percent, 0) }}</span>
        </div>
      </template>
    </DataTable>
  </div>
</template>
