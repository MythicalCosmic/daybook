<script setup lang="ts">
/**
 * The Person 360 "Tasks and routines" tab (plan §6.2, registered in `personTabs`). Routine work is
 * not a task (§15.2), so the tab has two blocks that never mix:
 *
 * - Tasks: one-off work (`routines=without`): today, late, on time and done over 7 days, what is
 *   open and what they finished lately;
 * - Routine work (`routines=only`): today's runs, late now, completion and missed runs over the 7
 *   days before today, and today's runs with their state.
 *
 * Any card opens the task drawer.
 */
import { ArrowUpRight, ListTodo, Repeat } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { todayIn } from "@/lib/dates";
import { patchQuery } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useSummary, useTaskList } from "../api";
import type { SeriesPoint, TaskRow, TaskSummary } from "../types";
import TaskCard from "./TaskCard.vue";
import TaskDrawer from "./TaskDrawer.vue";

const props = defineProps<{ memberId: number }>();

const { t } = useI18n();
const router = useRouter();
const company = useCompanyStore();

const OPEN = ["todo", "in_progress", "review", "returned"];
const person = computed(() => [String(props.memberId)]);

// One-off tasks.
const summary = useSummary(computed(() => ({ assignee: props.memberId, routines: "without" })));
const open = useTaskList(computed(() => ({ assignee: person.value, routines: "without", status: OPEN, ordering: "due_at", page_size: 20 })));
const recent = useTaskList(computed(() => ({ assignee: person.value, routines: "without", status: ["done"], ordering: "-completed_at", page_size: 4 })));
/** The soonest open tasks; the rest are one click away on the Tasks page, so routine work stays in view. */
const OPEN_SHOWN = 6;
const openShown = computed(() => open.data.value?.results.slice(0, OPEN_SHOWN) ?? []);

// Routine work.
const today = computed(() => todayIn(company.timezone));
const routineSummary = useSummary(computed(() => ({ assignee: props.memberId, routines: "only" })));
const runs = useTaskList(
  computed(() => ({ assignee: person.value, routines: "only", status: [...OPEN, "done"], due_from: today.value, due_to: today.value, ordering: "due_at", page_size: 20 })),
);

/** A change only when there is something to compare with: otherwise the badge would just say "—". */
function comparable(value: number | null | undefined, previous: number | null | undefined): number | undefined {
  return value === null || value === undefined || previous === null || previous === undefined || (previous === 0 && value === 0) ? undefined : previous;
}

/** Days with nothing due have no rate: the sparkline joins the days that had some. */
function rates(points: number[]): number[] {
  return points.length > 1 ? points : [];
}

function doneToday(data: TaskSummary | undefined) {
  return { id: "today", label: t("tasks.kpi.doneToday"), value: data?.done_today ?? null, format: (v: number) => (data ? `${v} / ${data.total_today}` : String(v)) };
}

const kpis = computed(() => {
  const data = summary.data.value;
  return [
    doneToday(data),
    { id: "late", label: t("tasks.kpi.lateNow"), value: data?.late_now ?? null },
    {
      id: "on_time",
      label: t("tasks.kpi.onTime"),
      value: data?.on_time_percent ?? null,
      previous: comparable(data?.on_time_percent, data?.on_time_previous),
      format: "percent" as const,
      points: true,
      spark: rates((data?.series ?? []).flatMap((p) => (p.on_time_percent === null ? [] : [p.on_time_percent]))),
    },
    { id: "done", label: t("tasks.person.done7d"), value: data?.done_7d ?? null, previous: data?.done_prev_7d ? comparable(data.done_7d, data.done_prev_7d) : undefined },
  ];
});

/** The 7 whole days before today: today's runs may still be done, so they count from tomorrow. */
function lastWeek(series: SeriesPoint[] | undefined): SeriesPoint[] {
  return (series ?? []).slice(-8, -1);
}

const routineKpis = computed(() => {
  const data = routineSummary.data.value;
  const week = lastWeek(data?.series);
  const due = week.reduce((sum, day) => sum + day.total, 0);
  const done = week.reduce((sum, day) => sum + day.done, 0);
  const missed = week.reduce((sum, day) => sum + day.missed, 0);
  return [
    doneToday(data),
    { id: "late", label: t("tasks.kpi.lateNow"), value: data?.late_now ?? null, hint: t("tasks.person.lateHint") },
    {
      id: "completion",
      label: t("tasks.person.completion7d"),
      value: data ? (due ? Math.round((1000 * done) / due) / 10 : null) : null,
      format: "percent" as const,
      hint: t("tasks.person.completionHint"),
    },
    { id: "missed", label: t("tasks.person.missed7d"), value: data ? missed : null, hint: t("tasks.person.missedHint") },
  ];
});

/** Nothing of that kind in the last two weeks: one quiet line instead of zeros and an empty list. */
const tasksQuiet = computed(() => {
  const data = summary.data.value;
  return (
    !!data &&
    !data.total_today &&
    !data.late_now &&
    !data.done_7d &&
    !data.done_prev_7d &&
    data.series.every((day) => !day.total) &&
    open.data.value?.count === 0 &&
    recent.data.value?.count === 0
  );
});
const routinesQuiet = computed(() => {
  const data = routineSummary.data.value;
  return !!data && !data.total_today && !data.late_now && data.series.every((day) => !day.total) && runs.data.value?.count === 0;
});

const tasksLink = computed(() => `/c/${company.currentId}/tasks?assignee=${props.memberId}&sv=all`);
const routinesLink = computed(() => `/c/${company.currentId}/routines`);

function openTask(task: TaskRow): void {
  patchQuery(router, { task: String(task.id) }, true);
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-10">
    <!-- One-off tasks -->
    <section class="flex min-w-0 flex-col gap-4" data-block="tasks" :aria-labelledby="`person-tasks-${memberId}`">
      <header class="flex flex-wrap items-end gap-x-3 gap-y-1">
        <div class="min-w-0 flex-1">
          <h2 :id="`person-tasks-${memberId}`" class="flex items-center gap-2 text-md font-semibold text-fg"><ListTodo :size="16" class="text-subtle" aria-hidden="true" />{{ t("tasks.person.tasksTitle") }}</h2>
          <p class="mt-0.5 text-sm text-muted">{{ t("tasks.person.tasksHint") }}</p>
        </div>
        <UiButton size="sm" variant="ghost" :icon-right="ArrowUpRight" :to="tasksLink">{{ t("tasks.person.all") }}</UiButton>
      </header>
      <p v-if="tasksQuiet" class="ui-card px-5 py-4 text-sm text-muted" data-quiet>{{ t("tasks.person.noTasks") }}</p>
      <KpiStrip v-else :items="kpis" :loading="summary.isPending.value" :columns="4" phone="compact" />
      <div v-if="!tasksQuiet" class="flex flex-col gap-2">
        <h3 class="flex items-center gap-2 text-sm font-semibold text-fg">
          {{ t("tasks.person.open") }}<span class="text-xs font-medium text-subtle">{{ open.data.value?.count ?? "" }}</span>
        </h3>
        <div v-if="open.isPending.value" class="grid gap-2 md:grid-cols-2"><SkeletonBlock v-for="n in 4" :key="n" height="76px" radius="12px" /></div>
        <ErrorState v-else-if="open.isError.value" compact :error="open.error.value" :retry="() => open.refetch()" />
        <div v-else-if="!open.data.value?.results.length" class="ui-card"><EmptyState size="sm" tone="success" :icon="ListTodo" :title="t('tasks.person.nothingOpen')" /></div>
        <div v-else class="grid gap-2 md:grid-cols-2">
          <button v-for="task in openShown" :key="task.id" type="button" class="ui-card p-3 text-left transition-colors hover:border-line-strong" @click="openTask(task)">
            <TaskCard :task="task" show-status :show-assignee="false" />
          </button>
        </div>
        <UiButton v-if="(open.data.value?.count ?? 0) > OPEN_SHOWN" size="sm" variant="ghost" class="self-start" :icon-right="ArrowUpRight" :to="tasksLink" data-view-all>{{
          t("common.viewAll")
        }}</UiButton>
      </div>
      <div v-if="recent.data.value?.results.length" class="flex flex-col gap-2">
        <h3 class="text-sm font-semibold text-fg">{{ t("tasks.person.recent") }}</h3>
        <div class="grid gap-2 md:grid-cols-2">
          <button v-for="task in recent.data.value.results" :key="task.id" type="button" class="ui-card p-3 text-left transition-colors hover:border-line-strong" @click="openTask(task)">
            <TaskCard :task="task" :show-assignee="false" />
          </button>
        </div>
      </div>
    </section>

    <!-- Routine work -->
    <section class="flex min-w-0 flex-col gap-4" data-block="routines" :aria-labelledby="`person-routines-${memberId}`">
      <header class="flex flex-wrap items-end gap-x-3 gap-y-1">
        <div class="min-w-0 flex-1">
          <h2 :id="`person-routines-${memberId}`" class="flex items-center gap-2 text-md font-semibold text-fg"><Repeat :size="16" class="text-subtle" aria-hidden="true" />{{ t("tasks.person.routinesTitle") }}</h2>
          <p class="mt-0.5 text-sm text-muted">{{ t("tasks.person.routinesHint") }}</p>
        </div>
        <UiButton size="sm" variant="ghost" :icon-right="ArrowUpRight" :to="routinesLink">{{ t("tasks.person.routinesLink") }}</UiButton>
      </header>
      <p v-if="routinesQuiet" class="ui-card px-5 py-4 text-sm text-muted" data-quiet>{{ t("tasks.person.noRoutines") }}</p>
      <KpiStrip v-else :items="routineKpis" :loading="routineSummary.isPending.value" :columns="4" phone="compact" />
      <div v-if="!routinesQuiet" class="flex flex-col gap-2">
        <h3 class="flex items-center gap-2 text-sm font-semibold text-fg">
          {{ t("tasks.person.runsToday") }}<span class="text-xs font-medium text-subtle">{{ runs.data.value?.count ?? "" }}</span>
        </h3>
        <div v-if="runs.isPending.value" class="grid gap-2 md:grid-cols-2"><SkeletonBlock v-for="n in 2" :key="n" height="76px" radius="12px" /></div>
        <ErrorState v-else-if="runs.isError.value" compact :error="runs.error.value" :retry="() => runs.refetch()" />
        <div v-else-if="!runs.data.value?.results.length" class="ui-card"><EmptyState size="sm" :icon="Repeat" :title="t('tasks.person.noRunsToday')" /></div>
        <div v-else class="grid gap-2 md:grid-cols-2">
          <button v-for="task in runs.data.value.results" :key="task.id" type="button" class="ui-card p-3 text-left transition-colors hover:border-line-strong" @click="openTask(task)">
            <TaskCard :task="task" show-status :show-assignee="false" />
          </button>
        </div>
      </div>
    </section>
    <TaskDrawer />
  </div>
</template>
