<script setup lang="ts">
/**
 * Tasks (plan §6.1 `tasks?view=table|board|calendar&task=:id`): every task the person may see,
 * as a table, a board or a calendar. Saved views as tabs, filter chips in the URL, the KPI strip,
 * the drawer (`?task=`) and "New task" (`N`). Other modules add tools through `tasks.toolbar`.
 */
import { CalendarDays, Columns3, Plus, Rows3 } from "@lucide/vue";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import ExtensionSlot from "@/components/ExtensionSlot.vue";
import FilterBar from "@/components/FilterBar.vue";
import { useUrlFilters } from "@/components/filters";
import KpiCard from "@/components/KpiCard.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import PageHeader from "@/components/PageHeader.vue";
import SavedViewsTabs from "@/components/SavedViewsTabs.vue";
import { useScopedBranches } from "@/components/pickers";
import SegmentedControl from "@/components/SegmentedControl.vue";
import UiButton from "@/components/UiButton.vue";
import { useDataTable } from "@/components/useDataTable";
import { useHotkey } from "@/core/hotkeys";
import { todayIn } from "@/lib/dates";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { usePermission } from "@/lib/usePermission";
import { patchQuery, rs, useRouteState } from "@/lib/useRouteState";
import { paramsDiffer, useSavedViews } from "@/lib/useSavedViews";
import { useCompanyStore } from "@/stores/company";

import { useSummary, useTaskOptions } from "../api";
import CreateTaskDialog from "../components/CreateTaskDialog.vue";
import TaskDrawer from "../components/TaskDrawer.vue";
import TasksBoard from "../components/TasksBoard.vue";
import TasksCalendar from "../components/TasksCalendar.vue";
import TasksTable from "../components/TasksTable.vue";
import { builtinTabs, builtinViews, filterDefs, viewParams } from "../filters";
import type { TaskRow, TaskView } from "../types";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const { can, isOwner } = usePermission();
const { isPhone } = useBreakpoints();

const options = useTaskOptions();
const branches = useScopedBranches();
const today = computed(() => todayIn(company.timezone));
const owner = computed(() => isOwner.value && !!company.current);

const view = useRouteState<TaskView>("view", rs.enum(["table", "board", "calendar"] as const, "table"));
const search = useRouteState("q", rs.string(""));
const viewId = useRouteState("sv", rs.string("open"));

const defs = computed(() => filterDefs(t, options.data.value, branches.value, owner.value));
const filters = useUrlFilters(defs);
const params = computed<Record<string, string | string[]>>(() => (search.value ? { ...filters.params.value, q: search.value } : filters.params.value));
const filtered = computed(() => filters.active.value > 0 || !!search.value);

const table = useDataTable({ id: "tasks.list", ordering: "due_at", url: true, hidden: ["routine", "created_by", "reward", "completed_at"] });

// Saved views ---------------------------------------------------------------------------------
const builtins = computed(() => builtinViews(today.value));
const saved = useSavedViews("tasks");
const tabs = computed(() => [...builtinTabs(t, builtins.value, owner.value), ...saved.tabs.value]);

function paramsOfView(id: string | number): { params: Record<string, string | string[]>; ordering?: string } | null {
  const builtin = builtins.value.find((v) => v.id === String(id));
  if (builtin) return { params: builtin.params, ordering: builtin.ordering };
  const found = saved.find(Number(id));
  if (!found) return null;
  return { params: viewParams(found.state), ordering: typeof found.state.ordering === "string" ? found.state.ordering : undefined };
}

const dirty = computed(() => {
  const current = paramsOfView(viewId.value);
  return !!current && paramsDiffer(filters.params.value, current.params);
});

function applyView(id: string | number): void {
  const target = paramsOfView(id);
  if (!target) return;
  const keys = [...defs.value.flatMap((def) => (def.type === "date-range" ? (def.params ?? [`${def.key}_from`, `${def.key}_to`]) : [def.key])), "q", "page"];
  const patch: Record<string, string | string[] | undefined> = Object.fromEntries(keys.map((key) => [key, undefined]));
  Object.assign(patch, target.params);
  patch.sv = String(id) === "open" ? undefined : String(id);
  patch.ordering = target.ordering && target.ordering !== "due_at" ? target.ordering : undefined;
  patchQuery(router, patch);
}

const activeView = computed({
  get: () => (tabs.value.some((tab) => String(tab.id) === viewId.value) ? (tabs.value.find((tab) => String(tab.id) === viewId.value)!.id) : "open"),
  set: (id: string | number) => applyView(id),
});

function stateToSave() {
  return { params: { ...filters.params.value }, view: view.value, ordering: table.ordering.value };
}

async function saveView(input: { name: string; shared: boolean }): Promise<void> {
  const created = await saved.create.mutateAsync({ name: input.name, is_shared: input.shared, state: stateToSave() });
  patchQuery(router, { sv: String(created.id) });
}

// The first visit opens "All open" with its chips showing.
onMounted(() => {
  const filterKeys = defs.value.flatMap((def) => (def.type === "date-range" ? (def.params ?? []) : [def.key]));
  const hasAny = filterKeys.some((key) => route.query[key] !== undefined) || route.query.sv !== undefined || route.query.q !== undefined;
  if (!hasAny) patchQuery(router, builtins.value[0]!.params);
});

// KPIs ---------------------------------------------------------------------------------------
const summary = useSummary();
const kpis = computed(() => {
  const data = summary.data.value;
  const cid = company.currentId;
  return [
    {
      id: "done",
      label: t("tasks.kpi.doneToday"),
      value: data?.done_today ?? null,
      format: (value: number) => (data ? `${value} / ${data.total_today}` : String(value)),
      hint: t("tasks.kpi.doneTodayHint"),
    },
    { id: "late", label: t("tasks.kpi.lateNow"), value: data?.late_now ?? null, to: `/c/${cid}/tasks?sv=late&overdue=true`, hint: t("tasks.kpi.lateNowHint") },
    { id: "review", label: t("tasks.kpi.review"), value: data?.review ?? null, to: `/c/${cid}/tasks/reviews` },
    {
      id: "on_time",
      label: t("tasks.kpi.onTime"),
      value: data?.on_time_percent ?? null,
      previous: data?.on_time_previous ?? null,
      format: "percent" as const,
      points: true,
      deltaLabel: t("tasks.kpi.vsWeekBefore"),
      spark: data?.series.map((point) => point.on_time_percent) ?? [],
    },
  ];
});

// Drawer and creating --------------------------------------------------------------------------
const openId = computed(() => {
  const value = Number(route.query.task);
  return Number.isInteger(value) && value > 0 ? value : null;
});
function open(task: TaskRow): void {
  patchQuery(router, { task: String(task.id) }, true);
}
const createOpen = ref(false);
// The palette's "New task" lands here with `?new=1`.
const newParam = useRouteState("new", rs.boolean(false));
watch(
  newParam,
  (value) => {
    if (!value) return;
    if (can("tasks.assign")) createOpen.value = true;
    newParam.value = false;
  },
  { immediate: true },
);
function onCreated(ids: number[]): void {
  if (ids.length === 1) patchQuery(router, { task: String(ids[0]) }, true);
}
useHotkey("n", () => can("tasks.assign") && (createOpen.value = true), { description: "tasks.keys.new", group: "page" });
useHotkey("v", () => (view.value = view.value === "table" ? "board" : view.value === "board" ? "calendar" : "table"), { description: "tasks.keys.view", group: "page" });

const viewOptions = computed(() => [
  { value: "table" as const, label: t("tasks.view.table"), icon: Rows3, iconOnly: isPhone.value },
  { value: "board" as const, label: t("tasks.view.board"), icon: Columns3, iconOnly: isPhone.value },
  { value: "calendar" as const, label: t("tasks.view.calendar"), icon: CalendarDays, iconOnly: isPhone.value },
]);
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <PageHeader :title="t('tasks.title')" :description="t('tasks.description')">
      <template #actions>
        <ExtensionSlot name="tasks.toolbar" as="none" :context="{ companyId: company.currentId, filters: params }" />
        <UiButton v-if="can('tasks.assign')" variant="primary" :icon="Plus" :kbd="isPhone ? undefined : 'N'" @click="createOpen = true">{{ t("tasks.create.button") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="isPhone" class="grid grid-cols-2 gap-2">
      <KpiCard v-for="(item, index) in kpis" :key="index" v-bind="{ ...item, spark: undefined, hint: undefined }" :loading="summary.isPending.value" />
    </div>
    <KpiStrip v-else :items="kpis" :loading="summary.isPending.value" :columns="4" />

    <div class="flex min-w-0 flex-col gap-3">
      <SavedViewsTabs
        v-model="activeView"
        :views="tabs"
        :dirty="dirty"
        @save="saveView"
        @update="(target) => saved.update.mutate({ id: Number(target.id), state: stateToSave() })"
        @rename="(target, name) => saved.update.mutate({ id: Number(target.id), name })"
        @share="(target, shared) => saved.update.mutate({ id: Number(target.id), is_shared: shared })"
        @delete="(target) => (saved.remove.mutate(Number(target.id)), applyView('open'))"
      />
      <div class="flex min-w-0 flex-wrap items-start gap-2">
        <FilterBar v-model="filters.values.value" v-model:search="search" class="min-w-0 flex-1" :defs="defs" searchable :search-placeholder="t('tasks.searchPlaceholder')" />
        <SegmentedControl v-model="view" :options="viewOptions" :aria-label="t('tasks.view.label')" />
      </div>

      <TasksTable v-if="view === 'table'" :state="table" :params="params" :filtered="filtered" :active-id="openId" @open="open" @clear-filters="filters.clear(), (search = '')" />
      <TasksBoard v-else-if="view === 'board'" :params="params" @open="open" />
      <TasksCalendar v-else :params="params" @open="open" />
    </div>

    <TaskDrawer />
    <CreateTaskDialog v-model:open="createOpen" @created="onCreated" />
  </div>
</template>
