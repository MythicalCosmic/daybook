<script setup lang="ts">
/**
 * The live "who's in" board (plan §6.2 Attendance): today's people in five columns (in, late, not
 * here yet, absent, off) per branch, with each check-in's distance and flags as trust signals, the
 * branches with their geofences on a map, and anything that needs a look. Any past day can be
 * opened (`?date=`); the branch filter is in the URL too. Live through the pulse and a minute tick.
 */
import { AlertTriangle, CalendarDays, MapPinned, Settings2, Store, Users } from "@lucide/vue";
import { computed, defineAsyncComponent, ref } from "vue";
import { useI18n } from "vue-i18n";

import DatePicker from "@/components/DatePicker.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ExportButton from "@/components/ExportButton.vue";
import IconButton from "@/components/IconButton.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { todayIn } from "@/lib/dates";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useBoard, useSummary } from "../api";
import AttendanceHeader from "../components/AttendanceHeader.vue";
import BoardTile from "../components/BoardTile.vue";
import BranchSwitch from "../components/BranchSwitch.vue";
import RecordDrawer from "../components/RecordDrawer.vue";
import { BOARD_STATES, clockOf, formatDistance, STATE_COLORS } from "../lib";
import type { BoardRow, BoardState } from "../types";

const GeoMap = defineAsyncComponent(() => import("../components/GeoMap.vue"));
const PersonMonth = defineAsyncComponent(() => import("../components/PersonMonth.vue"));
const SettingsForm = defineAsyncComponent(() => import("../components/SettingsForm.vue"));

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const { isPhone } = useBreakpoints();

const today = computed(() => todayIn(company.timezone));
const day = useRouteState("date", rs.day());
const branch = useRouteState("branch", rs.optionalNumber());
const recordId = useRouteState("record", rs.optionalNumber(), { push: true });
const personId = useRouteState("person", rs.optionalNumber(), { push: true });
const settingsOpen = ref(false);

const params = computed(() => ({ date: day.value, branch: branch.value ? [branch.value] : [] }));
const board = useBoard(params);
const skeleton = useDelayedPending(computed(() => board.isPending.value));
const data = computed(() => board.data.value);
const isToday = computed(() => !day.value || day.value === today.value);
const week = useSummary(() => ({ preset: "last_30", branch: branch.value ? [branch.value] : [] }));

const columns = computed(() =>
  BOARD_STATES.map((state) => ({
    state,
    rows: (data.value?.people ?? []).filter((row) => row.state === state),
  })),
);
const showBranch = computed(() => !branch.value && (data.value?.branches.length ?? 0) > 1);
/** Nobody works and nobody came: either nobody has a schedule yet, or it's a day off for all. */
const quiet = computed(() => !!data.value && data.value.totals.rostered === 0 && data.value.totals.in + data.value.totals.late === 0);
const unplanned = computed(() => quiet.value && (data.value?.people ?? []).every((row) => row.state === "off" && row.reason === "no_shift"));
const restDay = computed(() => quiet.value && !unplanned.value);
/** People not here yet whose shift has already started (past the grace minutes). */
const overdue = computed(() => (data.value?.people ?? []).filter((row) => row.state === "not_yet" && row.reason === "late").length);

const kpis = computed(() => {
  const totals = data.value?.totals;
  if (!totals) return [];
  const present = totals.in + totals.late;
  // On a phone the KPI is half the width: the number and its line of context need the room.
  const spark = isPhone.value ? undefined : (week.data.value?.series ?? []).slice(-14).map((point) => point.present);
  return [
    {
      id: "present",
      label: isToday.value ? t("attendance.kpi.presentNow") : t("attendance.kpi.present"),
      value: present,
      hint: t("attendance.kpi.ofRostered", { n: totals.rostered }),
      icon: Users,
      spark,
      sparkColor: "var(--c-chart-2)",
    },
    { id: "late", label: t("attendance.kpi.late"), value: totals.late, hint: totals.late ? t("attendance.kpi.lateHint") : undefined, sparkColor: "var(--c-chart-4)" },
    // The same people as the "Not here yet" column, so the numbers and the columns always agree.
    {
      id: "missing",
      label: t("attendance.state.not_yet"),
      value: totals.not_yet,
      hint: !totals.not_yet ? undefined : overdue.value ? t("attendance.kpi.notYetHint", { n: overdue.value }) : t("attendance.kpi.notYetSoon"),
    },
    { id: "absent", label: t("attendance.kpi.absent"), value: totals.absent, hint: totals.absent && isToday.value ? t("attendance.kpi.absentHint") : undefined },
    {
      id: "ontime",
      label: t("attendance.kpi.onTime30"),
      value: week.data.value?.totals.on_time_percent !== null && week.data.value ? Number(week.data.value.totals.on_time_percent) : null,
      format: "percent" as const,
      previous: undefined,
      hint: t("attendance.kpi.onTimeHint"),
    },
  ];
});

/** Check-ins that deserve a second look: outside the geofence, imprecise, without location, forgotten check-outs. */
const flagged = computed(() =>
  (data.value?.people ?? []).filter((row) => row.record && row.record.flags.some((flag) => ["outside_geofence", "low_accuracy", "no_location", "auto_closed"].includes(flag))),
);
const units = computed(() => ({ m: t("attendance.unit.m"), km: t("attendance.unit.km") }));

const mapBranches = computed(() => data.value?.branches ?? []);
const mapPoints = computed(() =>
  (data.value?.people ?? [])
    .filter((row) => row.record?.in_lat && row.record.in_lng)
    .map((row) => ({
      id: row.record!.id,
      lat: row.record!.in_lat!,
      lng: row.record!.in_lng!,
      tone: row.record!.flags.includes("outside_geofence") ? ("bad" as const) : row.record!.flags.includes("low_accuracy") ? ("warn" as const) : ("ok" as const),
      label: `${row.member.name} · ${clockOf(row.record!.check_in_at)}`,
    })),
);

function open(row: BoardRow): void {
  if (row.record) recordId.value = row.record.id;
  else personId.value = row.member.id;
}

const personName = computed(() => data.value?.people.find((row) => row.member.id === personId.value)?.member.name ?? "");
const description = computed(() => {
  const label = fmt.day(day.value ?? today.value, "weekday");
  if (data.value?.holiday) return `${label} · ${data.value.holiday}`;
  return label;
});
const columnLabel = (state: BoardState) => t(`attendance.state.${state}`);
</script>

<template>
  <div class="flex flex-col gap-5">
    <AttendanceHeader :title="t('attendance.today.title')" :description="description">
      <template #actions>
        <ExportButton kind="attendance.timesheet" :params="{ start: day ?? today, end: day ?? today, branch: branch ?? undefined }" variant="ghost" />
        <IconButton v-if="company.can('attendance.manage')" :icon="Settings2" :label="t('attendance.settings.title')" variant="secondary" @click="settingsOpen = true" />
      </template>
      <template #meta>
        <StatusPill v-if="isToday" tone="success" live :label="t('attendance.today.live')" size="sm" />
        <StatusPill v-else tone="neutral" :icon="CalendarDays" :label="t('attendance.today.past')" size="sm" />
      </template>
    </AttendanceHeader>

    <div class="flex flex-wrap items-center gap-2">
      <BranchSwitch v-model="branch" />
      <span class="flex-1" />
      <UiButton v-if="!isToday" size="sm" variant="ghost" @click="day = null">{{ t("common.today") }}</UiButton>
      <DatePicker v-model="day" size="sm" :max="today" :placeholder="t('common.today')" format="weekday" class="w-56" />
    </div>

    <div v-if="skeleton" class="flex flex-col gap-4">
      <SkeletonBlock height="92px" radius="12px" />
      <div class="grid gap-3 md:grid-cols-3 xl:grid-cols-5">
        <div v-for="n in 5" :key="n" class="flex flex-col gap-2 rounded-[12px] border border-line p-3">
          <SkeletonBlock width="50%" />
          <SkeletonBlock v-for="m in 3" :key="m" height="62px" radius="10px" />
        </div>
      </div>
    </div>
    <ErrorState v-else-if="board.isError.value" :error="board.error.value" :retry="() => board.refetch()" />
    <template v-else-if="data">
      <KpiStrip class="att-kpis" :items="kpis" :columns="5" />

      <EmptyState
        v-if="!data.people.length || unplanned"
        :icon="Users"
        :title="t('attendance.today.emptyTitle')"
        :description="t('attendance.today.emptyBody')"
      >
        <UiButton v-if="company.can('attendance.manage')" variant="primary" :to="`/c/${company.currentId}/attendance/schedules`">{{ t("attendance.today.emptyAction") }}</UiButton>
      </EmptyState>

      <EmptyState
        v-else-if="restDay"
        :icon="CalendarDays"
        tone="neutral"
        :title="data.holiday ? t('attendance.today.holidayTitle', { name: data.holiday }) : t('attendance.today.restTitle')"
        :description="t('attendance.today.restBody')"
      >
        <UiButton variant="secondary" :to="`/c/${company.currentId}/attendance/roster`">{{ t("attendance.today.restAction") }}</UiButton>
      </EmptyState>

      <div v-else class="grid items-start gap-3 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        <section
          v-for="column in columns"
          :key="column.state"
          class="flex min-w-0 flex-col rounded-[12px] border border-line bg-surface-2/50 dark:bg-surface-2/30"
          :aria-label="columnLabel(column.state)"
        >
          <header class="flex items-center gap-2 px-3 pb-2 pt-3">
            <span class="size-2 rounded-full" :style="{ background: STATE_COLORS[column.state] }" aria-hidden="true" />
            <h2 class="text-sm font-semibold text-fg">{{ columnLabel(column.state) }}</h2>
            <span class="rounded-full bg-surface px-1.5 text-xs font-semibold tabular-nums text-muted">{{ column.rows.length }}</span>
          </header>
          <TransitionGroup tag="div" name="att-list" class="flex flex-col gap-2 px-2 pb-2">
            <BoardTile v-for="row in column.rows" :key="row.member.id" :row="row" :show-branch="showBranch" :now="data.is_today ? data.now : null" @open="open" />
          </TransitionGroup>
          <p v-if="!column.rows.length" class="px-3 pb-4 pt-1 text-xs text-subtle">{{ t(`attendance.state.${column.state}Empty`) }}</p>
        </section>
      </div>

      <!-- The map and branch cards say nothing until people have shifts. -->
      <div v-if="data.people.length && !unplanned" class="grid gap-3 lg:grid-cols-3">
        <section class="ui-card flex min-w-0 flex-col gap-3 p-4 lg:col-span-2" :aria-label="t('attendance.map.title')">
          <header class="flex items-center gap-2">
            <MapPinned :size="16" class="text-subtle" aria-hidden="true" />
            <h2 class="text-sm font-semibold text-fg">{{ t("attendance.map.title") }}</h2>
            <span class="text-xs text-subtle">{{ t("attendance.map.hint") }}</span>
          </header>
          <GeoMap v-if="mapBranches.some((b) => b.latitude)" :branches="mapBranches" :points="mapPoints" height="300px" @select="(id) => (recordId = Number(id))" />
          <EmptyState v-else size="sm" tone="neutral" :icon="MapPinned" :title="t('attendance.map.noCoordinates')" :description="t('attendance.map.noCoordinatesBody')" />
          <div class="flex flex-wrap items-center gap-3 text-xs text-muted">
            <span class="inline-flex items-center gap-1.5"><span class="size-2.5 rounded-full bg-success" />{{ t("attendance.map.inside") }}</span>
            <span class="inline-flex items-center gap-1.5"><span class="size-2.5 rounded-full bg-warning" />{{ t("attendance.map.imprecise") }}</span>
            <span class="inline-flex items-center gap-1.5"><span class="size-2.5 rounded-full bg-danger" />{{ t("attendance.map.outside") }}</span>
          </div>
        </section>

        <div class="flex min-w-0 flex-col gap-3">
          <section class="ui-card p-4" :aria-label="t('attendance.branches.title')">
            <header class="mb-3 flex items-center gap-2">
              <Store :size="16" class="text-subtle" aria-hidden="true" />
              <h2 class="text-sm font-semibold text-fg">{{ t("attendance.branches.title") }}</h2>
            </header>
            <ul class="flex flex-col gap-2.5">
              <li v-for="item in data.branches" :key="item.id" class="flex items-center gap-3">
                <div class="min-w-0 flex-1">
                  <p class="truncate text-sm font-medium text-fg">{{ item.name }}</p>
                  <p class="truncate text-xs text-muted">
                    {{ item.first_check_in ? t("attendance.branches.firstIn", { time: clockOf(item.first_check_in) }) : t("attendance.branches.nobodyYet") }}
                  </p>
                </div>
                <span class="text-sm font-semibold tabular-nums text-fg">{{ item.checked_in }}<span class="font-normal text-subtle">/{{ item.rostered }}</span></span>
                <div class="h-1.5 w-16 overflow-hidden rounded-full bg-surface-2">
                  <div class="h-full rounded-full bg-success transition-[width] duration-500" :style="{ width: `${item.rostered ? Math.min(100, (item.checked_in / item.rostered) * 100) : 0}%` }" />
                </div>
              </li>
            </ul>
          </section>

          <section class="ui-card p-4" :aria-label="t('attendance.flags.title')">
            <header class="mb-2 flex items-center gap-2">
              <AlertTriangle :size="16" class="text-subtle" aria-hidden="true" />
              <h2 class="text-sm font-semibold text-fg">{{ t("attendance.flags.title") }}</h2>
              <span v-if="flagged.length" class="rounded-full bg-warning-soft px-1.5 text-xs font-semibold tabular-nums text-warning">{{ flagged.length }}</span>
            </header>
            <ul v-if="flagged.length" class="flex flex-col">
              <li v-for="row in flagged" :key="row.member.id">
                <button type="button" class="flex w-full items-center gap-2 rounded-[8px] px-1.5 py-1.5 text-left hover:bg-highlight" @click="open(row)">
                  <span class="min-w-0 flex-1 truncate text-sm text-fg">{{ row.member.name }}</span>
                  <span class="shrink-0 text-xs text-muted">
                    <template v-if="row.record!.flags.includes('outside_geofence')">{{ t("attendance.flags.away", { d: formatDistance(row.record!.in_distance_m, units) }) }}</template>
                    <template v-else-if="row.record!.flags.includes('auto_closed')">{{ t("attendance.flag.auto_closed") }}</template>
                    <template v-else-if="row.record!.flags.includes('no_location')">{{ t("attendance.flag.no_location") }}</template>
                    <template v-else>{{ t("attendance.flag.low_accuracy") }}</template>
                  </span>
                </button>
              </li>
            </ul>
            <p v-else class="py-2 text-xs text-subtle">{{ t("attendance.flags.none") }}</p>
          </section>
        </div>
      </div>
    </template>

    <RecordDrawer />
    <UiDrawer query-key="person" size="lg" :title="personName || t('attendance.person.title')">
      <template #default="{ value }">
        <PersonMonth v-if="value" class="p-5" :member-id="Number(value)" />
      </template>
    </UiDrawer>
    <UiDrawer v-model:open="settingsOpen" size="lg" :title="t('attendance.settings.title')" :description="t('attendance.settings.description')">
      <SettingsForm v-if="settingsOpen" class="p-5" />
    </UiDrawer>
  </div>
</template>

<style scoped>
.att-list-move,
.att-list-enter-active,
.att-list-leave-active {
  transition:
    transform 240ms var(--ease-out),
    opacity 180ms var(--ease-out);
}
.att-list-enter-from,
.att-list-leave-to {
  opacity: 0;
  transform: translateY(6px);
}
.att-list-leave-active {
  position: absolute;
}
</style>
