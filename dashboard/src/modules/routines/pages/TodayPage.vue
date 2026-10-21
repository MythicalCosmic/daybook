<script setup lang="ts">
/**
 * Routines → Today, the home of routine work: every routine due today with its progress and each
 * person's run (done with the time and proof photo, waiting for confirmation, late, to do) and
 * who it skipped (time off, day off, suspended, joined later), so finished routine work is seen
 * right here. `?day=` shows another day (History drills in here), `?routine=` one routine;
 * filters by branch and position. Runs waiting for the viewer can be confirmed in place.
 */
import { CalendarCheck, ChevronLeft, ChevronRight, Plus, Repeat, Store, Users, X } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import DatePicker from "@/components/DatePicker.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FilterBar from "@/components/FilterBar.vue";
import { useUrlFilters, type FilterDef } from "@/components/filters";
import IconButton from "@/components/IconButton.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import { useScopedBranches } from "@/components/pickers";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { addDays, todayIn } from "@/lib/dates";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { usePermission } from "@/lib/usePermission";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useConfirmRuns, usePlanOptions, useRoutineDay, useSendBackRun } from "../api";
import DayRoutineCard from "../components/DayRoutineCard.vue";
import GiveTodayDialog from "../components/GiveTodayDialog.vue";
import RoutinesHeader from "../components/RoutinesHeader.vue";
import type { GiveTarget, RoutineRun } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const { can } = usePermission();
const ask = useConfirm();

const today = computed(() => todayIn(company.timezone));
const dayParam = useRouteState("day", rs.string(""));
const day = computed({
  get: () => dayParam.value || today.value,
  set: (value: string | null) => (dayParam.value = !value || value === today.value ? "" : value),
});
const isToday = computed(() => day.value === today.value);
const only = useRouteState("routine", rs.string(""));

const options = usePlanOptions();
const branches = useScopedBranches();
const defs = computed<FilterDef[]>(() => [
  { key: "branch", label: t("routines.filter.branch"), type: "multi", icon: Store, options: branches.value.map((b) => ({ value: String(b.id), label: b.name, description: b.code })) },
  { key: "position", label: t("routines.filter.position"), type: "multi", icon: Users, options: (options.data.value?.positions ?? []).map((p) => ({ value: String(p.id), label: p.name })) },
]);
const filters = useUrlFilters(defs);
const params = computed(() => ({
  day: dayParam.value || undefined,
  branch: (filters.params.value.branch as string[] | undefined) ?? undefined,
  position: (filters.params.value.position as string[] | undefined) ?? undefined,
}));

const query = useRoutineDay(params);
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const data = computed(() => query.data.value ?? null);
const rows = computed(() => (data.value?.routines ?? []).filter((row) => !only.value || String(row.routine.id) === only.value));
const focused = computed(() => (only.value ? (data.value?.routines.find((row) => String(row.routine.id) === only.value)?.routine ?? null) : null));

// The numbers count what the list shows: the whole day, or the one routine History opened.
const totalsShown = computed(() => {
  if (!data.value) return null;
  if (!only.value) return data.value.totals;
  const row = rows.value[0];
  return row ? { ...row.counts, total: row.progress.total, finished: row.progress.finished, routines: 1 } : null;
});
const kpis = computed(() => {
  const totals = totalsShown.value;
  const percent = totals && totals.total ? Math.round((100 * totals.finished) / totals.total) : null;
  return [
    {
      id: "finished",
      label: t("routines.today.kpi.finished"),
      value: totals ? totals.finished : null,
      format: (value: number) => (totals ? `${value} / ${totals.total}` : String(value)),
      hint: percent === null ? t("routines.today.kpi.finishedHint") : t("routines.today.kpi.finishedPercent", { percent: fmt.percent(percent, 0) }),
    },
    { id: "review", label: t("routines.today.kpi.review"), value: totals?.review ?? null, to: can("tasks.confirm") ? { name: "routines.confirm" } : undefined },
    { id: "late", label: t("routines.today.kpi.late"), value: totals ? totals.late + totals.missed : null, hint: t("routines.today.kpi.lateHint") },
    { id: "skipped", label: t("routines.today.kpi.skipped"), value: totals?.skipped ?? null, hint: t("routines.today.kpi.skippedHint") },
  ];
});

// Deciding runs in place ----------------------------------------------------------------------
const busy = ref(new Set<number>());
function mark(id: number, value: boolean): void {
  const next = new Set(busy.value);
  if (value) next.add(id);
  else next.delete(id);
  busy.value = next;
}
const confirmRuns = useConfirmRuns();
const sendBackRun = useSendBackRun();

async function confirmRun(run: RoutineRun): Promise<void> {
  mark(run.id, true);
  try {
    const result = await confirmRuns.mutateAsync([run.id]);
    if (result.done) toast.success(t("routines.confirm.done", { n: 1 }, 1), { description: run.member.name });
    else toast.error(result.results[0]?.error || t("routines.confirm.failed"));
  } catch {
    // the HTTP layer showed why
  } finally {
    mark(run.id, false);
  }
}

async function sendBack(run: RoutineRun, title: string): Promise<void> {
  const answer = await ask({
    title: t("routines.confirm.sendBackTitle"),
    message: `${run.member.name} · ${title}`,
    reason: "required",
    reasonLabel: t("routines.confirm.reason"),
    reasonPlaceholder: t("routines.confirm.reasonPlaceholder"),
    confirmLabel: t("routines.confirm.sendBack"),
    tone: "danger",
  });
  if (!answer) return;
  mark(run.id, true);
  try {
    await sendBackRun.mutateAsync({ id: run.id, reason: answer.reason });
    toast.success(t("routines.confirm.sentBack"), { description: run.member.name });
  } catch {
    // the HTTP layer showed why
  } finally {
    mark(run.id, false);
  }
}

const giving = ref<GiveTarget | null>(null);
const giveOpen = ref(false);
function give(target: GiveTarget): void {
  giving.value = target;
  giveOpen.value = true;
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <RoutinesHeader>
      <template #actions>
        <div class="flex items-center gap-1">
          <IconButton :icon="ChevronLeft" :label="t('routines.today.previousDay')" size="sm" variant="secondary" @click="day = addDays(day, -1)" />
          <DatePicker v-model="day" size="sm" format="weekday" class="w-[220px] max-sm:min-w-0 max-sm:flex-1" />
          <IconButton :icon="ChevronRight" :label="t('routines.today.nextDay')" size="sm" variant="secondary" @click="day = addDays(day, 1)" />
        </div>
        <UiButton v-if="!isToday" size="sm" :icon="CalendarCheck" @click="day = today">{{ t("routines.today.backToToday") }}</UiButton>
      </template>
    </RoutinesHeader>

    <KpiStrip :items="kpis" :loading="query.isPending.value" :columns="4" phone="compact" />

    <div class="flex min-w-0 flex-wrap items-center gap-2">
      <FilterBar v-model="filters.values.value" class="min-w-0 flex-1" :defs="defs" />
      <button
        v-if="only"
        type="button"
        class="inline-flex h-8 max-w-full items-center gap-1.5 rounded-button border border-line-strong bg-accent-soft px-2.5 text-sm font-medium text-accent-fg"
        @click="only = ''"
      >
        <Repeat :size="14" class="shrink-0" aria-hidden="true" /><span class="truncate">{{ focused ? t("routines.today.only", { title: focused.title }) : t("routines.today.onlyOne") }}</span><X :size="14" class="shrink-0" :aria-label="t('routines.today.showEvery')" />
      </button>
    </div>

    <div v-if="skeleton" class="flex flex-col gap-3">
      <div v-for="n in 3" :key="n" class="ui-card flex flex-col gap-3 p-4">
        <SkeletonBlock width="35%" height="18px" />
        <div class="grid gap-2 sm:grid-cols-2 2xl:grid-cols-3"><SkeletonBlock v-for="m in 3" :key="m" height="56px" radius="10px" /></div>
      </div>
    </div>
    <ErrorState v-else-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else-if="data">
      <div v-if="!rows.length" class="ui-card">
        <EmptyState
          v-if="!data.routines.length && !data.idle && !filters.active.value"
          :icon="Repeat"
          size="lg"
          :title="t('routines.emptyTitle')"
          :description="t('routines.emptyBody')"
        >
          <UiButton v-if="can('tasks.templates')" variant="primary" :icon="Plus" :to="{ name: 'routines.list', query: { new: '1' } }">{{ t("routines.new") }}</UiButton>
        </EmptyState>
        <EmptyState v-else-if="filters.active.value || only" size="sm" tone="neutral" :title="t('routines.today.noMatch')" />
        <EmptyState v-else :icon="CalendarCheck" :title="isToday ? t('routines.today.emptyToday') : t('routines.today.emptyDay')" :description="t('routines.today.idle', { n: data.idle }, data.idle)" />
      </div>
      <div v-else class="flex flex-col gap-3">
        <DayRoutineCard
          v-for="row in rows"
          :key="row.routine.id"
          :row="row"
          :day="data.day"
          :busy="busy"
          @give="give"
          @confirm="confirmRun"
          @send-back="(run) => sendBack(run, row.routine.title)"
        />
        <p v-if="data.idle && !only" class="px-1 text-sm text-muted">
          {{ t("routines.today.idle", { n: data.idle }, data.idle) }}
          <RouterLink v-if="can('tasks.templates')" :to="{ name: 'routines.list' }" class="font-medium text-accent-fg hover:underline">{{ t("routines.today.seeAll") }}</RouterLink>
        </p>
      </div>
    </template>

    <GiveTodayDialog v-model:open="giveOpen" :routine="giving" />
  </div>
</template>
