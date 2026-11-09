<script setup lang="ts">
/**
 * Attendance reports (docs/DAVOMAT.md §1.6): any period by person, department and branch — the
 * attendance rate, punctuality, late arrivals and their minutes, absences, hours and overtime —
 * the day-by-day trend, who comes on time and who needs attention, and each report as Excel or
 * PDF. The period (this month by default), filters and table live in the URL.
 *
 * The figures are the server's (apps/attendance/analytics.py), one pass over the days, so the
 * strip, the chart, the ranking and every table agree. Only days up to today count; a day's
 * absences count once it is over; a day without a planned shift is never an absence.
 */
import { CalendarClock, CalendarX2, Network, Store, Users } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import BarChart from "@/components/BarChart.vue";
import BranchPicker from "@/components/BranchPicker.vue";
import ChartCard, { type ChartCsv } from "@/components/ChartCard.vue";
import DataTable from "@/components/DataTable.vue";
import DateRangePicker from "@/components/DateRangePicker.vue";
import EmptyState from "@/components/EmptyState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import MultiSelect from "@/components/MultiSelect.vue";
import PersonCell from "@/components/PersonCell.vue";
import { useScopedBranches } from "@/components/pickers";
import ProgressBar from "@/components/ProgressBar.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import { useChartTheme } from "@/components/useChartTheme";
import { useDataTable } from "@/components/useDataTable";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useFormat } from "@/lib/useFormat";
import { useRangeState } from "@/lib/useRangeState";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useReport, useReportDepartments } from "../api";
import AttendanceHeader from "../components/AttendanceHeader.vue";
import PunctualityCard from "../components/PunctualityCard.vue";
import ReportExport from "../components/ReportExport.vue";
import { onTime, rateTone, sortRows, TONE_TEXT } from "../reports";
import type { BranchRef, ReportEmployee, ReportFigures, ReportKind, ReportParams, Ref, TrendDay } from "../types";

type View = "people" | "departments" | "branches";
const VIEWS = ["people", "departments", "branches"] as const;
const KIND: Record<View, ReportKind> = { people: "summary", departments: "departments", branches: "branches" };

/** One table row, whichever view: a person, a department or a branch. */
interface Row extends ReportFigures {
  key: string;
  label: string;
  employee: ReportEmployee | null;
  group: Ref | BranchRef | null;
  people: number | null;
}

const { t } = useI18n();
const fmt = useFormat();
const chart = useChartTheme();
const company = useCompanyStore();
const { isPhone } = useBreakpoints();

// ─── Period and filters ─────────────────────────────────────────────────────

const period = useRangeState({ preset: "month" });
const branches = useRouteState("branch", rs.numberList());
const departments = useRouteState("department", rs.numberList());
const view = useRouteState<View>("view", rs.enum(VIEWS, "people"));

const params = computed<ReportParams>(() => ({
  from: period.value.range.from,
  to: period.value.range.to,
  branch: branches.value,
  department: departments.value,
}));

const scoped = useScopedBranches();
const canDepartments = computed(() => company.can(["members.view", "members.manage"]));
const departmentList = useReportDepartments(canDepartments);
const departmentOptions = computed(() => (departmentList.data.value ?? []).map((d) => ({ value: d.id, label: d.path.length ? d.path.join(" › ") : d.name })));
const filtered = computed(() => branches.value.length > 0 || departments.value.length > 0);

// ─── Reports ────────────────────────────────────────────────────────────────

const people = useReport("summary", params);
const trend = useReport("trend", params);
const ranking = useReport("punctuality", params);
const byDepartment = useReport("departments", params, () => view.value === "departments");
const byBranch = useReport("branches", params, () => view.value === "branches");

const totals = computed(() => people.data.value?.totals ?? null);
const countedUntil = computed(() => people.data.value?.counted_until ?? null);
const today = computed(() => people.data.value?.today ?? trend.data.value?.today ?? "");
const isEmpty = computed(() => !!totals.value && totals.value.people === 0);
const noShifts = computed(() => !!totals.value && totals.value.people > 0 && totals.value.days_scheduled === 0);

// ─── KPI strip ──────────────────────────────────────────────────────────────

const days = computed(() => trend.data.value?.days ?? []);
// Today is still running: its rates would dip, so the small trends stop at yesterday.
const past = computed(() => days.value.filter((day) => day.date !== today.value));

const kpis = computed(() => {
  const sum = totals.value;
  // A failed summary: each tile keeps its label and offers Try again.
  const failed = { error: people.error.value ?? undefined, retry: () => people.refetch() };
  return [
    {
      id: "attendance",
      ...failed,
      label: t("attendance.reports.kpi.attendance"),
      value: sum?.attendance_percent ?? null,
      format: "percent" as const,
      hint: sum ? t("attendance.reports.kpi.attendanceHint", { n: sum.days_scheduled }, sum.days_scheduled) : undefined,
      spark: past.value.map((day) => {
        const due = day.scheduled - day.leave - day.excused;
        return due > 0 ? (day.expected_present / due) * 100 : null;
      }),
      sparkColor: "var(--c-success)",
    },
    {
      id: "punctuality",
      ...failed,
      label: t("attendance.reports.kpi.punctuality"),
      value: sum?.punctuality_percent ?? null,
      format: "percent" as const,
      hint: sum?.arrivals ? t("attendance.reports.kpi.punctualityHint", { on: sum.on_time, all: sum.arrivals }) : undefined,
      spark: past.value.map((day) => day.punctuality_percent),
    },
    {
      id: "late",
      ...failed,
      label: t("attendance.reports.kpi.late"),
      value: sum?.late_count ?? null,
      inverse: true,
      hint: sum?.late_minutes ? t("attendance.reports.kpi.lateHint", { d: fmt.duration(sum.late_minutes) }) : undefined,
      spark: past.value.map((day) => day.late),
      sparkColor: "var(--c-warning)",
    },
    {
      id: "absent",
      ...failed,
      label: t("attendance.reports.kpi.absent"),
      value: sum?.days_absent ?? null,
      inverse: true,
      hint: sum?.days_leave ? t("attendance.reports.kpi.absentHint", { n: sum.days_leave }, sum.days_leave) : undefined,
      spark: past.value.map((day) => day.absent),
      sparkColor: "var(--c-danger)",
    },
    {
      id: "hours",
      ...failed,
      label: t("attendance.reports.kpi.hours"),
      value: sum?.worked_minutes ?? null,
      format: "duration" as const,
      hint: sum?.overtime_minutes ? t("attendance.reports.kpi.overtimeHint", { d: fmt.duration(sum.overtime_minutes) }) : undefined,
      spark: past.value.map((day) => day.worked_minutes),
    },
  ];
});

// ─── The day-by-day chart ───────────────────────────────────────────────────

const categories = computed(() => days.value.map((day) => day.date));
const trendSeries = computed(() => [
  { name: t("attendance.reports.trend.onTime"), data: days.value.map(onTime), color: chart.value.success, stack: "day" },
  { name: t("attendance.reports.trend.late"), data: days.value.map((day) => day.late), color: chart.value.warning, stack: "day" },
  { name: t("attendance.reports.trend.absent"), data: days.value.map((day) => day.absent), color: chart.value.danger, stack: "day" },
  { name: t("attendance.reports.trend.leave"), data: days.value.map((day) => day.leave), color: chart.value.info, stack: "day" },
]);
const trendEmpty = computed(() => !days.value.some((day) => day.present || day.absent || day.leave));
const trendSubtitle = computed(() => {
  const range = trend.data.value?.range;
  if (!range) return undefined;
  const text = fmt.range(range);
  return days.value.some((day) => day.date === today.value) ? t("attendance.reports.trend.subtitle", { range: text }) : text;
});
const trendCsv = computed<ChartCsv<TrendDay>>(() => ({
  filename: t("attendance.reports.trend.title"),
  columns: [
    { key: "date", label: t("attendance.reports.col.day"), value: (day) => day.date },
    { key: "scheduled", label: t("attendance.reports.col.scheduled"), value: (day) => day.scheduled },
    { key: "present", label: t("attendance.reports.col.present"), value: (day) => day.present },
    { key: "late", label: t("attendance.reports.col.late"), value: (day) => day.late },
    { key: "absent", label: t("attendance.reports.col.absent"), value: (day) => day.absent },
    { key: "leave", label: t("attendance.reports.col.leave"), value: (day) => day.leave },
  ],
  rows: days.value,
}));

// ─── The table ──────────────────────────────────────────────────────────────

const viewOptions = computed(() => [
  { value: "people" as const, label: t("attendance.reports.view.people"), icon: Users, iconOnly: isPhone.value },
  { value: "departments" as const, label: t("attendance.reports.view.departments"), icon: Network, iconOnly: isPhone.value },
  { value: "branches" as const, label: t("attendance.reports.view.branches"), icon: Store, iconOnly: isPhone.value },
]);

const tables = {
  people: useDataTable({ id: "attendance.reports.people", pageSize: 500 }),
  departments: useDataTable({ id: "attendance.reports.departments", pageSize: 500 }),
  branches: useDataTable({ id: "attendance.reports.branches", pageSize: 500 }),
};
const table = computed(() => tables[view.value]);

const current = computed(() => (view.value === "departments" ? byDepartment : view.value === "branches" ? byBranch : people));

function figures<T extends ReportFigures>(row: T): ReportFigures {
  return {
    days_scheduled: row.days_scheduled,
    days_present: row.days_present,
    days_absent: row.days_absent,
    days_leave: row.days_leave,
    days_excused: row.days_excused,
    worked_minutes: row.worked_minutes,
    late_count: row.late_count,
    late_minutes: row.late_minutes,
    early_leave_count: row.early_leave_count,
    early_leave_minutes: row.early_leave_minutes,
    overtime_minutes: row.overtime_minutes,
    arrivals: row.arrivals,
    on_time: row.on_time,
    punctuality_percent: row.punctuality_percent,
    attendance_percent: row.attendance_percent,
  };
}

const unsorted = computed<Row[]>(() => {
  if (view.value === "departments") {
    return (byDepartment.data.value?.rows ?? []).map((row) => ({
      ...figures(row),
      key: `d${row.department?.id ?? 0}`,
      label: row.department?.name ?? t("attendance.reports.noDepartment"),
      employee: null,
      group: row.department,
      people: row.people,
    }));
  }
  if (view.value === "branches") {
    return (byBranch.data.value?.rows ?? []).map((row) => ({
      ...figures(row),
      key: `b${row.branch?.id ?? 0}`,
      label: row.branch?.name ?? t("attendance.reports.noBranch"),
      employee: null,
      group: row.branch,
      people: row.people,
    }));
  }
  return (people.data.value?.rows ?? []).map((row) => ({
    ...figures(row),
    key: `p${row.employee.id}`,
    label: row.employee.name,
    employee: row.employee,
    group: null,
    people: null,
  }));
});

const rows = computed(() => {
  const ordering = table.value.ordering.value;
  if (!ordering) return unsorted.value;
  return sortRows(unsorted.value, ordering, (row, field) => {
    if (field === "label") return row.label.toLowerCase();
    const value = (row as unknown as Record<string, unknown>)[field];
    return typeof value === "number" ? value : null;
  });
});

const labelHeader = computed(() =>
  view.value === "departments" ? t("attendance.reports.col.department") : view.value === "branches" ? t("attendance.reports.col.branch") : t("attendance.reports.col.person"),
);

// Short headers (the full words are in the KPI strip and the hints); long ones clip in uz and ru.
// The rates first, then the days and the minutes; the rarer figures last (they scroll in on a
// narrow screen).
const columns = computed<TableColumn<Row>[]>(() => [
  { id: "label", header: labelHeader.value, sortable: true, minWidth: 220, sticky: true, hideable: false },
  ...(view.value === "people" ? [] : [{ id: "people", header: t("attendance.reports.col.people"), sortable: true, numeric: true, width: 112 } as TableColumn<Row>]),
  { id: "punctuality_percent", header: t("attendance.reports.col.punctuality"), hint: t("attendance.reports.col.punctualityHint"), sortable: true, width: 180 },
  { id: "attendance_percent", header: t("attendance.reports.col.attendance"), hint: t("attendance.reports.col.attendanceHint"), sortable: true, numeric: true, width: 124, format: (value) => fmt.percent(value as number | null, 1) },
  { id: "days_present", header: t("attendance.reports.col.present"), sortable: true, numeric: true, width: 84 },
  { id: "days_scheduled", header: t("attendance.reports.col.scheduled"), hint: t("attendance.reports.col.scheduledHint"), sortable: true, numeric: true, width: 108 },
  { id: "days_absent", header: t("attendance.reports.col.absent"), sortable: true, numeric: true, width: 108 },
  { id: "late_count", header: t("attendance.reports.col.late"), sortable: true, numeric: true, width: 130 },
  { id: "worked_minutes", header: t("attendance.reports.col.hours"), sortable: true, numeric: true, width: 130, format: (value) => fmt.duration(value as number), csv: (row) => Math.round((row.worked_minutes / 60) * 10) / 10 },
  { id: "overtime_minutes", header: t("attendance.reports.col.overtime"), sortable: true, numeric: true, width: 120, format: (value) => (value ? fmt.duration(value as number) : "—") },
  { id: "early_leave_count", header: t("attendance.reports.col.early"), sortable: true, numeric: true, width: 110 },
  { id: "days_leave", header: t("attendance.reports.col.leave"), sortable: true, numeric: true, width: 84 },
]);

function personLine(employee: ReportEmployee): string | null {
  return [employee.position?.name, employee.department?.name].filter(Boolean).join(" · ") || null;
}

function cardLine(row: Row): string {
  const line = t("attendance.reports.card", { present: row.days_present, scheduled: row.days_scheduled, late: row.late_count, absent: row.days_absent });
  return row.people === null ? line : `${t("attendance.reports.groupPeople", { n: row.people }, row.people)} · ${line}`;
}

const emptyIcon = computed(() => (view.value === "departments" ? Network : view.value === "branches" ? Store : Users));
const schedulesLink = computed(() => (company.can("attendance.manage") ? `/c/${company.currentId}/attendance/schedules` : null));
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <AttendanceHeader :title="t('attendance.reports.title')" :description="t('attendance.reports.description')">
      <template #actions>
        <ReportExport :kind="KIND[view]" :params="params" />
      </template>
    </AttendanceHeader>

    <div class="flex flex-wrap items-center gap-2" data-report-filters>
      <DateRangePicker v-model="period" :compare="false" class="max-sm:w-full" />
      <div v-if="scoped.length > 1" class="w-full sm:w-[240px]">
        <BranchPicker v-model="branches" multiple :placeholder="t('attendance.allBranches')" />
      </div>
      <div v-if="departmentOptions.length" class="w-full sm:w-[260px]">
        <MultiSelect v-model="departments" :options="departmentOptions" display="count" :placeholder="t('attendance.reports.allDepartments')" />
      </div>
    </div>

    <KpiStrip :items="kpis" :loading="people.isPending.value" :columns="5" phone="grid" />

    <InlineAlert v-if="noShifts" tone="info" :icon="CalendarClock" :title="t('attendance.reports.noShiftsTitle')" :description="t('attendance.reports.noShiftsBody')" data-report-no-shifts>
      <template v-if="schedulesLink" #actions>
        <UiButton size="sm" variant="secondary" :to="schedulesLink">{{ t("attendance.reports.setSchedules") }}</UiButton>
      </template>
    </InlineAlert>

    <EmptyState
      v-if="isEmpty"
      class="ui-card py-12"
      size="lg"
      :icon="CalendarX2"
      :title="filtered ? t('attendance.reports.emptyFilteredTitle') : t('attendance.reports.emptyTitle')"
      :description="filtered ? t('attendance.reports.emptyFilteredBody') : t('attendance.reports.emptyBody')"
      data-report-empty
    >
      <UiButton v-if="filtered" variant="secondary" size="sm" @click="(branches = []), (departments = [])">{{ t("attendance.reports.clearFilters") }}</UiButton>
      <UiButton v-else-if="schedulesLink" variant="primary" size="sm" :icon="CalendarClock" :to="schedulesLink">{{ t("attendance.reports.setSchedules") }}</UiButton>
    </EmptyState>

    <template v-else>
      <div class="grid min-w-0 gap-4 xl:grid-cols-2">
        <ChartCard
          :title="t('attendance.reports.trend.title')"
          :subtitle="trendSubtitle"
          :loading="trend.isPending.value"
          :error="trend.error.value"
          :retry="() => trend.refetch()"
          :empty="trendEmpty"
          :empty-text="t('attendance.reports.trend.empty')"
          :csv="trendCsv as ChartCsv<never>"
          height="320px"
        >
          <BarChart :categories="categories" :series="trendSeries" stacked integer :x-format="days.length > 62 ? 'month' : 'day'" height="320px" />
        </ChartCard>
        <PunctualityCard :report="ranking.data.value" :loading="ranking.isPending.value" :error="ranking.error.value" :retry="() => ranking.refetch()" />
      </div>

      <DataTable
        :state="table"
        :columns="columns"
        :rows="rows"
        :total="rows.length"
        row-key="key"
        :loading="current.isPending.value"
        :fetching="current.isFetching.value"
        :error="current.error.value"
        :retry="() => current.refetch()"
        :empty-icon="emptyIcon"
        :empty-title="t('attendance.reports.tableEmptyTitle')"
        :empty-description="t('attendance.reports.tableEmptyBody')"
        :caption="t('attendance.reports.title')"
        hide-pagination
        virtual="auto"
      >
        <template #toolbar>
          <SegmentedControl v-model="view" size="sm" :options="viewOptions" :aria-label="t('attendance.reports.viewBy')" />
        </template>
        <template #cell-label="{ row }">
          <PersonCell v-if="row.employee" :person="row.employee" :subtitle="personLine(row.employee)" size="sm" link />
          <span v-else :class="['truncate font-medium', row.group ? 'text-fg' : 'text-muted']">{{ row.label }}</span>
        </template>
        <template #cell-days_absent="{ row }">
          <span :class="['tabular-nums', row.days_absent ? 'font-semibold text-danger' : 'text-subtle']">{{ row.days_absent }}</span>
        </template>
        <template #cell-days_leave="{ row }">
          <span :class="['tabular-nums', row.days_leave ? 'text-info' : 'text-subtle']">{{ row.days_leave }}</span>
        </template>
        <template #cell-late_count="{ row }">
          <span v-if="row.late_count" class="tabular-nums">
            <span class="font-semibold text-warning">{{ row.late_count }}</span>
            <span class="text-xs text-muted"> · {{ fmt.duration(row.late_minutes) }}</span>
          </span>
          <span v-else class="tabular-nums text-subtle">0</span>
        </template>
        <template #cell-early_leave_count="{ row }">
          <span :class="['tabular-nums', row.early_leave_count ? 'text-fg' : 'text-subtle']" :title="row.early_leave_count ? fmt.duration(row.early_leave_minutes) : undefined">{{ row.early_leave_count }}</span>
        </template>
        <template #cell-punctuality_percent="{ row }">
          <span v-if="row.punctuality_percent !== null" class="flex w-full min-w-0 items-center gap-2">
            <ProgressBar class="flex-1" :value="row.punctuality_percent" :tone="rateTone(row.punctuality_percent)" />
            <span :class="['w-12 text-right text-sm font-semibold tabular-nums', TONE_TEXT[rateTone(row.punctuality_percent)]]">{{ fmt.percent(row.punctuality_percent, 0) }}</span>
          </span>
          <span v-else class="text-subtle">—</span>
        </template>
        <template #card="{ row }">
          <div class="flex min-w-0 items-center gap-3">
            <div class="min-w-0 flex-1">
              <PersonCell v-if="row.employee" :person="row.employee" :subtitle="personLine(row.employee)" size="sm" />
              <p v-else class="truncate text-sm font-semibold text-fg">{{ row.label }}</p>
              <p class="mt-1 text-xs text-muted">{{ cardLine(row) }}</p>
              <p class="mt-0.5 text-xs text-muted">{{ t("attendance.reports.cardHours", { d: fmt.duration(row.worked_minutes) }) }}</p>
            </div>
            <span :class="['shrink-0 text-md font-semibold tabular-nums', TONE_TEXT[rateTone(row.punctuality_percent)]]">{{ fmt.percent(row.punctuality_percent, 0) }}</span>
          </div>
        </template>
      </DataTable>
    </template>

    <p v-if="countedUntil" class="text-xs leading-relaxed text-subtle" data-report-footnote>
      {{ t("attendance.reports.footnote", { day: fmt.day(countedUntil, "medium") }) }}
    </p>
    <p v-else-if="totals" class="text-xs text-subtle" data-report-footnote>{{ t("attendance.reports.notStarted") }}</p>
  </div>
</template>
