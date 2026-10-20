<script setup lang="ts">
/**
 * Time off (plan §6.2): the month as a calendar of leave bars and holidays, requests waiting for a
 * decision beside it (approve or reject in place), every request as a table, "Record time off" for
 * someone (past days allowed), and a drawer per request (`?request=`) with revoke. Month, view,
 * branch and filters live in the URL.
 */
import { CalendarDays, CalendarPlus, Check, ChevronLeft, ChevronRight, CircleDot, List, PartyPopper, Rows3, TreePalm, X } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import BranchPicker from "@/components/BranchPicker.vue";
import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FilterBar from "@/components/FilterBar.vue";
import { useUrlFilters, type FilterDef } from "@/components/filters";
import IconButton from "@/components/IconButton.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import PageHeader from "@/components/PageHeader.vue";
import PersonCell from "@/components/PersonCell.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill, { type StatusTone } from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { addMonths, startOfMonth, todayIn } from "@/lib/dates";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { patchQuery, rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useCalendar, useDecide, useStats, useTimeOffList } from "../api";
import LeaveMonthGrid from "../components/LeaveMonthGrid.vue";
import RecordDialog from "../components/RecordDialog.vue";
import RequestDrawer from "../components/RequestDrawer.vue";
import type { TimeOffRow, TimeOffStatus } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();

const today = computed(() => todayIn(company.timezone));
const view = useRouteState<"calendar" | "list">("view", rs.enum(["calendar", "list"] as const, "calendar"));
const month = useRouteState("month", rs.string(""));
const monthStart = computed(() => (/^\d{4}-\d{2}$/.test(month.value) ? `${month.value}-01` : startOfMonth(today.value)));
const everyone = useRouteState("everyone", rs.boolean(false));
const who = computed<"off" | "all">({ get: () => (everyone.value ? "all" : "off"), set: (value) => (everyone.value = value === "all") });
const branchParam = useRouteState("branch", rs.string(""));
const branchIds = computed<number[]>({
  get: () => branchParam.value.split(",").filter(Boolean).map(Number),
  set: (ids) => (branchParam.value = ids.join(",")),
});
const requestId = useRouteState("request", rs.optionalNumber());
const recordParam = useRouteState("record", rs.string(""));

function shiftMonth(step: number): void {
  month.value = addMonths(monthStart.value, step).slice(0, 7);
}

const stats = useStats();
const kpis = computed(() => {
  const s = stats.data.value;
  return [
    { id: "pending", label: t("timeoff.kpi.pending"), value: s?.pending, hint: t("timeoff.kpi.pendingHint") },
    { id: "today", label: t("timeoff.kpi.today"), value: s?.off_today, hint: t("timeoff.kpi.todayHint") },
    { id: "week", label: t("timeoff.kpi.week"), value: s?.off_this_week, hint: t("timeoff.kpi.weekHint") },
    { id: "month", label: t("timeoff.kpi.month"), value: s?.days_this_month, hint: t("timeoff.kpi.monthHint") },
  ];
});

// Calendar --------------------------------------------------------------------------------
const calendar = useCalendar(computed(() => ({ month: monthStart.value.slice(0, 7), branch: branchIds.value, everyone: everyone.value })));
const calendarSkeleton = useDelayedPending(computed(() => calendar.isPending.value));
const calendarEmpty = computed(() => !!calendar.data.value && calendar.data.value.rows.length === 0);

// Waiting for a decision -------------------------------------------------------------------
const waiting = useTimeOffList(computed(() => ({ status: ["pending"] as TimeOffStatus[], ordering: "created_at", page_size: 30, branch: branchIds.value.length ? branchIds.value : undefined })));
const waitingRows = computed(() => (waiting.data.value?.results ?? []).filter((row) => row.status === "pending"));
const decide = useDecide();
const deciding = ref<string | null>(null);
async function decideRow(row: TimeOffRow, approve: boolean): Promise<void> {
  deciding.value = `${row.id}:${approve}`;
  try {
    await decide.mutateAsync({ id: row.id, approve });
    toast.success(approve ? t("timeoff.approvedToast", { name: row.member.name }) : t("timeoff.rejectedToast", { name: row.member.name }));
  } catch {
    // Back in the list.
  } finally {
    deciding.value = null;
  }
}

// List view --------------------------------------------------------------------------------
const STATUS_OPTIONS = computed(() => [
  { value: "pending", label: t("timeoff.state.pending"), color: "var(--c-warning)" },
  { value: "approved", label: t("timeoff.state.approved"), color: "var(--c-success)" },
  { value: "rejected", label: t("timeoff.state.rejected"), color: "var(--c-danger)" },
  { value: "cancelled", label: t("timeoff.state.cancelled"), color: "var(--c-subtle)" },
]);
const defs = computed<FilterDef[]>(() => [
  { key: "status", label: t("timeoff.col.status"), type: "multi", icon: CircleDot, options: STATUS_OPTIONS.value },
  { key: "dates", label: t("timeoff.col.dates"), type: "date-range", params: ["from", "to"] },
]);
const filters = useUrlFilters(defs);
const search = useRouteState("q", rs.string(""));
const table = useDataTable({ id: "timeoff.list", url: true, pageSize: 50, ordering: "-first_day" });
watch([() => filters.params.value, search, branchIds], () => table.resetPage(), { deep: true });
const listParams = computed(() => ({
  ...(filters.params.value as Record<string, unknown>),
  q: search.value || undefined,
  branch: branchIds.value.length ? branchIds.value : undefined,
  ...table.params.value,
}));
const list = useTimeOffList(listParams as never, computed(() => view.value === "list"));
const TONES: Record<TimeOffStatus, StatusTone> = { pending: "warning", approved: "success", rejected: "danger", cancelled: "neutral" };
const columns = computed<TableColumn<TimeOffRow>[]>(() => [
  { id: "member", header: t("timeoff.col.person"), minWidth: 220, sticky: true, hideable: false, value: (row) => row.member.name },
  {
    id: "dates",
    header: t("timeoff.col.dates"),
    width: 190,
    sortable: "first_day",
    value: (row) => row.first_day,
    format: (_v, row) => (row.first_day === row.last_day ? fmt.day(row.first_day, "medium") : fmt.range({ from: row.first_day, to: row.last_day })),
  },
  { id: "days", header: t("timeoff.col.days"), width: 80, numeric: true },
  { id: "reason", header: t("timeoff.col.reason"), minWidth: 200 },
  { id: "status", header: t("timeoff.col.status"), width: 150, value: (row) => t(`timeoff.state.${row.status}`) },
  { id: "decided", header: t("timeoff.col.decided"), width: 170, value: (row) => row.recorded_by?.name ?? row.decided_by ?? "" },
  { id: "created_at", header: t("timeoff.col.asked"), width: 130, sortable: true, value: (row) => row.created_at, format: (v) => fmt.instant(String(v), "short") },
]);

function openRequest(id: number): void {
  requestId.value = id;
}
function openPerson(id: number): void {
  void router.push(`/c/${company.currentId}/people/${id}`);
}

// Record dialog (`?record=1` or `?record=<member id>` from Person 360) ----------------------
const recording = computed({
  get: () => recordParam.value !== "",
  set: (value: boolean) => {
    if (!value) patchQuery(router, { record: undefined });
  },
});
const recordFor = computed(() => (/^\d+$/.test(recordParam.value) && recordParam.value !== "1" ? Number(recordParam.value) : null));

const nextHoliday = computed(() => stats.data.value?.next_holiday ?? null);
</script>

<template>
  <div class="flex flex-col gap-5">
    <PageHeader :title="t('timeoff.page.title')" :description="t('timeoff.page.description')">
      <template #actions>
        <UiButton :to="`/c/${company.currentId}/time-off/holidays`" :icon="PartyPopper">{{ t("timeoff.nav.holidays") }}</UiButton>
        <UiButton variant="primary" :icon="CalendarPlus" @click="recordParam = '1'">{{ t("timeoff.cmd.record") }}</UiButton>
      </template>
      <template v-if="nextHoliday" #meta>
        <StatusPill :icon="PartyPopper" tone="primary" :label="t('timeoff.page.nextHoliday', { name: nextHoliday.name, date: fmt.day(nextHoliday.date, 'medium') })" />
      </template>
    </PageHeader>

    <KpiStrip :items="kpis" :loading="stats.isPending.value" :columns="4" />

    <div class="flex flex-wrap items-center gap-2">
      <SegmentedControl
        v-model="view"
        :options="[
          { value: 'calendar', label: t('timeoff.view.calendar'), icon: CalendarDays },
          { value: 'list', label: t('timeoff.view.list'), icon: List },
        ]"
      />
      <template v-if="view === 'calendar'">
        <div class="flex items-center gap-1">
          <IconButton :icon="ChevronLeft" :label="t('timeoff.calendar.prev')" variant="secondary" @click="shiftMonth(-1)" />
          <span class="min-w-[150px] px-1 text-center text-md font-semibold text-fg">{{ fmt.day(monthStart, "monthYear") }}</span>
          <IconButton :icon="ChevronRight" :label="t('timeoff.calendar.next')" variant="secondary" @click="shiftMonth(1)" />
        </div>
        <UiButton v-if="monthStart !== startOfMonth(today)" size="sm" variant="ghost" @click="month = ''">{{ t("common.today") }}</UiButton>
      </template>
      <span class="flex-1" />
      <BranchPicker v-if="company.current && company.current.branches.length > 1" v-model="branchIds" multiple class="w-full sm:w-[220px]" :placeholder="t('timeoff.allBranches')" />
      <SegmentedControl
        v-if="view === 'calendar'"
        v-model="who"
        size="sm"
        :options="[
          { value: 'off', label: t('timeoff.calendar.onlyOff') },
          { value: 'all', label: t('timeoff.calendar.everyone'), icon: Rows3 },
        ]"
      />
    </div>

    <div v-if="view === 'calendar'" class="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div class="min-w-0">
        <div v-if="calendarSkeleton && !calendar.data.value" class="ui-card flex flex-col gap-2 p-4">
          <SkeletonBlock height="44px" radius="8px" />
          <SkeletonBlock v-for="n in 6" :key="n" height="36px" radius="8px" />
        </div>
        <ErrorState v-else-if="calendar.isError.value" class="ui-card" :error="calendar.error.value" :retry="() => calendar.refetch()" />
        <div v-else-if="calendarEmpty" class="ui-card">
          <EmptyState :icon="TreePalm" :title="t('timeoff.calendar.emptyTitle')" :description="t('timeoff.calendar.emptyBody')">
            <UiButton variant="primary" :icon="CalendarPlus" @click="recordParam = '1'">{{ t("timeoff.cmd.record") }}</UiButton>
            <UiButton @click="everyone = true">{{ t("timeoff.calendar.showEveryone") }}</UiButton>
          </EmptyState>
        </div>
        <template v-else-if="calendar.data.value">
          <LeaveMonthGrid :month="calendar.data.value" :active-id="requestId" @open="openRequest" @person="openPerson" />
          <ul class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted" :aria-label="t('timeoff.legend.label')">
            <li class="flex items-center gap-1.5"><span class="legend is-approved" />{{ t("timeoff.status.approved") }}</li>
            <li class="flex items-center gap-1.5"><span class="legend is-recorded" />{{ t("timeoff.status.recorded") }}</li>
            <li class="flex items-center gap-1.5"><span class="legend is-pending" />{{ t("timeoff.status.pending") }}</li>
            <li class="flex items-center gap-1.5"><span class="legend is-holiday" />{{ t("timeoff.legend.holiday") }}</li>
            <li class="flex items-center gap-1.5"><span class="legend is-off" />{{ t("timeoff.legend.dayOff") }}</li>
          </ul>
        </template>
      </div>

      <aside class="ui-card flex h-fit min-w-0 flex-col" :aria-label="t('timeoff.waiting.title')">
        <header class="flex items-center gap-2 border-b border-line px-4 py-3">
          <h2 class="text-md font-semibold text-fg">{{ t("timeoff.waiting.title") }}</h2>
          <span v-if="waitingRows.length" class="rounded-full bg-warning-soft px-2 text-xs font-semibold tabular-nums text-warning">{{ waitingRows.length }}</span>
        </header>
        <div v-if="waiting.isPending.value" class="flex flex-col gap-3 p-4"><SkeletonBlock v-for="n in 3" :key="n" height="64px" radius="10px" /></div>
        <ErrorState v-else-if="waiting.isError.value" compact class="m-3" :error="waiting.error.value" :retry="() => waiting.refetch()" />
        <EmptyState v-else-if="!waitingRows.length" size="sm" tone="success" :title="t('timeoff.waiting.emptyTitle')" :description="t('timeoff.waiting.emptyBody')" />
        <TransitionGroup v-else name="list" tag="ul" class="relative flex flex-col divide-y divide-[var(--c-border)]">
          <li v-for="row in waitingRows" :key="row.id" class="flex flex-col gap-2 px-4 py-3">
            <button type="button" class="flex items-start gap-2.5 text-left" @click="openRequest(row.id)">
              <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="32" />
              <span class="min-w-0 flex-1">
                <span class="flex items-baseline gap-2">
                  <span class="min-w-0 flex-1 truncate text-base font-semibold text-fg">{{ row.member.name }}</span>
                  <RelativeTime :value="row.created_at" class="shrink-0 text-xs text-subtle" />
                </span>
                <span class="block text-sm text-fg">
                  {{ row.first_day === row.last_day ? fmt.day(row.first_day, "weekdayShort") : fmt.range({ from: row.first_day, to: row.last_day }) }}
                  <span class="text-muted">· {{ t("timeoff.days", { n: row.days }, row.days) }}</span>
                </span>
                <span v-if="row.reason" class="block truncate text-xs text-muted">{{ row.reason }}</span>
              </span>
            </button>
            <div class="flex items-center gap-2 pl-[42px]">
              <UiButton size="sm" variant="primary" :icon="Check" :loading="deciding === `${row.id}:true`" :disabled="!!deciding" @click="decideRow(row, true)">{{ t("common.approve") }}</UiButton>
              <UiButton size="sm" :icon="X" class="hover:!text-danger" :loading="deciding === `${row.id}:false`" :disabled="!!deciding" @click="decideRow(row, false)">{{ t("common.reject") }}</UiButton>
            </div>
          </li>
        </TransitionGroup>
      </aside>
    </div>

    <DataTable
      v-else
      :state="table"
      :columns="columns"
      :rows="list.data.value?.results"
      :total="list.data.value?.count"
      row-key="id"
      clickable
      :active-key="requestId"
      :loading="list.isPending.value"
      :fetching="list.isFetching.value"
      :error="list.error.value"
      :retry="() => list.refetch()"
      :filtered="filters.active.value > 0 || !!search"
      export-kind="timeoff.time_off"
      :export-params="filters.params.value"
      csv-name="Time off"
      :empty-title="t('timeoff.list.emptyTitle')"
      :empty-description="t('timeoff.list.emptyBody')"
      :empty-icon="TreePalm"
      @row-click="(row) => openRequest(row.id)"
      @clear-filters="
        filters.clear();
        search = '';
      "
    >
      <template #toolbar>
        <FilterBar v-model="filters.values.value" v-model:search="search" :defs="defs" searchable :search-placeholder="t('timeoff.list.search')" />
      </template>
      <template #cell-member="{ row }">
        <PersonCell :person="row.member" :subtitle="row.position" size="sm" />
      </template>
      <template #cell-status="{ row }">
        <StatusPill size="sm" :tone="TONES[row.status]" :label="t(`timeoff.state.${row.status}`)" />
      </template>
      <template #cell-decided="{ row }">
        <span v-if="row.recorded_by" class="text-sm text-fg">{{ t("timeoff.list.recordedBy", { name: row.recorded_by.name }) }}</span>
        <span v-else-if="row.decided_by" class="text-sm text-fg">{{ row.decided_by }}</span>
        <span v-else class="text-subtle">—</span>
      </template>
      <template #card="{ row }">
        <div class="flex items-start justify-between gap-3">
          <PersonCell :person="row.member" :subtitle="row.first_day === row.last_day ? fmt.day(row.first_day, 'medium') : fmt.range({ from: row.first_day, to: row.last_day })" />
          <StatusPill size="sm" :tone="TONES[row.status]" :label="t(`timeoff.state.${row.status}`)" />
        </div>
        <p v-if="row.reason" class="mt-1.5 truncate pl-[38px] text-xs text-muted">{{ row.reason }}</p>
      </template>
    </DataTable>

    <RequestDrawer />
    <RecordDialog v-if="recording" v-model:open="recording" :member-id="recordFor" @recorded="(row) => (requestId = row.id)" />
  </div>
</template>

<style scoped>
.legend {
  display: inline-block;
  width: 18px;
  height: 10px;
  border-radius: 4px;
  border: 1px solid transparent;
}
.legend.is-approved {
  background: color-mix(in srgb, var(--c-success) 16%, var(--c-surface));
  border-color: color-mix(in srgb, var(--c-success) 38%, transparent);
}
.legend.is-recorded {
  background: color-mix(in srgb, var(--c-info) 16%, var(--c-surface));
  border-color: color-mix(in srgb, var(--c-info) 38%, transparent);
}
.legend.is-pending {
  background: color-mix(in srgb, var(--c-warning) 10%, var(--c-surface));
  border: 1px dashed color-mix(in srgb, var(--c-warning) 65%, transparent);
}
.legend.is-holiday {
  background: repeating-linear-gradient(-45deg, color-mix(in srgb, var(--c-warning) 22%, transparent) 0 3px, transparent 3px 6px);
  border-color: var(--c-border);
}
.legend.is-off {
  background: color-mix(in srgb, var(--c-text) 6%, transparent);
  border-color: var(--c-border);
}
</style>
