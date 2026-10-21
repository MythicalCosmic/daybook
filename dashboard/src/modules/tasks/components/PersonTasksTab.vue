<script setup lang="ts">
/**
 * The Person 360 "Tasks" tab (plan §6.2, registered in `personTabs`): the person's numbers, open
 * work and what they finished lately, with the drawer for any of it.
 */
import { ArrowUpRight, ListTodo } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { patchQuery } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useSummary, useTaskList } from "../api";
import type { TaskRow } from "../types";
import TaskCard from "./TaskCard.vue";
import TaskDrawer from "./TaskDrawer.vue";

const props = defineProps<{ memberId: number }>();

const { t } = useI18n();
const router = useRouter();
const company = useCompanyStore();

const summary = useSummary(computed(() => ({ assignee: props.memberId })));
const open = useTaskList(computed(() => ({ assignee: [String(props.memberId)], status: ["todo", "in_progress", "review", "returned"], ordering: "due_at", page_size: 20 })));
const recent = useTaskList(computed(() => ({ assignee: [String(props.memberId)], status: ["done"], ordering: "-completed_at", page_size: 8 })));

/** A change only when there is something to compare with: otherwise the badge would just say "—". */
function comparable(value: number | null | undefined, previous: number | null | undefined): number | undefined {
  return value === null || value === undefined || previous === null || previous === undefined || (previous === 0 && value === 0) ? undefined : previous;
}

const kpis = computed(() => {
  const data = summary.data.value;
  return [
    { id: "today", label: t("tasks.kpi.doneToday"), value: data?.done_today ?? null, format: (v: number) => (data ? `${v} / ${data.total_today}` : String(v)) },
    { id: "late", label: t("tasks.kpi.lateNow"), value: data?.late_now ?? null },
    { id: "on_time", label: t("tasks.kpi.onTime"), value: data?.on_time_percent ?? null, previous: comparable(data?.on_time_percent, data?.on_time_previous), format: "percent" as const, points: true, spark: data?.series.map((p) => p.on_time_percent) ?? [] },
    { id: "done", label: t("tasks.person.done7d"), value: data?.done_7d ?? null, previous: data?.done_prev_7d ? comparable(data.done_7d, data.done_prev_7d) : undefined },
  ];
});

function openTask(task: TaskRow): void {
  patchQuery(router, { task: String(task.id) }, true);
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <KpiStrip :items="kpis" :loading="summary.isPending.value" :columns="4" />
    <section class="flex flex-col gap-2">
      <div class="flex items-center gap-2">
        <h3 class="text-sm font-semibold text-fg">{{ t("tasks.person.open") }}</h3>
        <span class="text-xs font-medium text-subtle">{{ open.data.value?.count ?? "" }}</span>
        <span class="flex-1" />
        <UiButton size="sm" variant="ghost" :icon-right="ArrowUpRight" :to="`/c/${company.currentId}/tasks?assignee=${memberId}&sv=all`">{{ t("tasks.person.all") }}</UiButton>
      </div>
      <div v-if="open.isPending.value" class="grid gap-2 md:grid-cols-2"><SkeletonBlock v-for="n in 4" :key="n" height="76px" radius="12px" /></div>
      <ErrorState v-else-if="open.isError.value" compact :error="open.error.value" :retry="() => open.refetch()" />
      <div v-else-if="!open.data.value?.results.length" class="ui-card"><EmptyState size="sm" tone="success" :icon="ListTodo" :title="t('tasks.person.nothingOpen')" /></div>
      <div v-else class="grid gap-2 md:grid-cols-2">
        <button v-for="task in open.data.value.results" :key="task.id" type="button" class="ui-card p-3 text-left transition-colors hover:border-line-strong" @click="openTask(task)">
          <TaskCard :task="task" show-status :show-assignee="false" />
        </button>
      </div>
    </section>
    <section v-if="recent.data.value?.results.length" class="flex flex-col gap-2">
      <h3 class="text-sm font-semibold text-fg">{{ t("tasks.person.recent") }}</h3>
      <div class="grid gap-2 md:grid-cols-2">
        <button v-for="task in recent.data.value.results" :key="task.id" type="button" class="ui-card p-3 text-left transition-colors hover:border-line-strong" @click="openTask(task)">
          <TaskCard :task="task" :show-assignee="false" />
        </button>
      </div>
    </section>
    <TaskDrawer />
  </div>
</template>
