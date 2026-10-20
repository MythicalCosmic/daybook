<script setup lang="ts">
/**
 * Projects (plan §13.3 "Index"): every project the person may see, as cards or a table, with a
 * KPI strip (live, at risk, off track, overdue cards, hours this week, budget used), filters in the
 * URL (status, health, lead, branch, mine, archived, search) and "New project" (`N`, or `?new=1`).
 */
import { FolderKanban, FolderPlus, GanttChart, LayoutGrid, Rows3, SearchX } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FilterBar from "@/components/FilterBar.vue";
import { useUrlFilters, type FilterDef } from "@/components/filters";
import KpiStrip from "@/components/KpiStrip.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import PersonCell from "@/components/PersonCell.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import { useDataTable } from "@/components/useDataTable";
import { useHotkey } from "@/core/hotkeys";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useOptions, usePeople, useProjects, useSummary } from "../api";
import HealthDot from "../components/HealthDot.vue";
import ProjectBadge from "../components/ProjectBadge.vue";
import ProjectCard from "../components/ProjectCard.vue";
import ProjectFormDialog from "../components/ProjectFormDialog.vue";
import { burnTone, STATUS_TONE } from "../lib";
import { HEALTHS, PROJECT_STATUSES, type ProjectItem } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const { isPhone } = useBreakpoints();

const view = useRouteState("view", rs.enum(["cards", "table"] as const, "cards"));
const search = useRouteState("q", rs.string());
const people = usePeople();
const options = useOptions();
const summary = useSummary();

const filterDefs = computed<FilterDef[]>(() => [
  { key: "status", label: t("projects.filter.status"), type: "multi", options: PROJECT_STATUSES.map((s) => ({ value: s, label: t(`projects.status.${s}`) })) },
  { key: "health", label: t("projects.filter.health"), type: "multi", options: HEALTHS.map((h) => ({ value: h, label: t(`projects.health.${h}`) })) },
  {
    key: "lead",
    label: t("projects.filter.lead"),
    type: "select",
    options: (people.data.value ?? []).map((p) => ({ value: String(p.id), label: p.name, avatar: { name: p.name, src: p.photo_url } })),
  },
  ...((options.data.value?.branches.length ?? 0) > 1
    ? [{ key: "branch", label: t("projects.filter.branch"), type: "select" as const, options: (options.data.value?.branches ?? []).map((b) => ({ value: String(b.id), label: b.name })) }]
    : []),
  { key: "mine", label: t("projects.filter.mine"), type: "boolean", trueLabel: t("common.yes"), falseLabel: t("common.no") },
  { key: "archived", label: t("projects.filter.archived"), type: "boolean", trueLabel: t("projects.filter.archivedOnly"), falseLabel: t("projects.filter.liveOnly") },
]);
const filters = useUrlFilters(filterDefs);

const table = useDataTable({ id: "projects.index", url: true, pageSize: 200, pageSizes: [200] });
const params = computed(() => {
  const v = filters.values.value;
  const list = (value: unknown) => (Array.isArray(value) ? (value as string[]) : value ? [String(value)] : undefined);
  return {
    status: list(v.status),
    health: list(v.health),
    lead: list(v.lead),
    branch: list(v.branch),
    mine: v.mine === true,
    archived: v.archived === true,
    q: search.value || undefined,
    ordering: table.ordering.value || undefined,
  };
});
const query = useProjects(params);
const skeleton = useDelayedPending(computed(() => query.isPending.value));

const RANK: Record<ProjectItem["status"], number> = { active: 0, planning: 1, on_hold: 2, completed: 3, cancelled: 4 };
const rows = computed(() => {
  const list = [...(query.data.value?.results ?? [])];
  if (table.ordering.value) return list;
  return list.sort((a, b) => RANK[a.status] - RANK[b.status] || (a.due_on ?? "9999").localeCompare(b.due_on ?? "9999") || a.name.localeCompare(b.name));
});
const filtered = computed(() => filters.active.value > 0 || !!search.value);
const canCreate = computed(() => options.data.value?.can_create ?? company.can("projects.manage"));

const creating = ref(false);
watch(
  () => route.query.new,
  (value) => {
    if (value === "1") {
      creating.value = true;
      const { new: _drop, ...rest } = route.query;
      void router.replace({ query: rest });
    }
  },
  { immediate: true },
);
useHotkey("n", () => (creating.value = true), { description: "projects.keys.new", group: "page", enabled: () => canCreate.value });

const kpis = computed(() => {
  const s = summary.data.value;
  const items: Array<{ id: string; label: string; value: number | string | null; format?: "number" | "money"; hint?: string; currency?: "UZS" | "USD"; compact?: boolean; inverse?: boolean }> = [
    { id: "active", label: t("projects.kpi.active"), value: s?.active ?? null, hint: s ? t("projects.kpi.planning", { n: s.planning }) : undefined },
    { id: "risk", label: t("projects.kpi.atRisk"), value: s ? s.at_risk + s.off_track : null, hint: s ? t("projects.kpi.offTrack", { n: s.off_track }) : undefined },
    { id: "overdue", label: t("projects.kpi.overdueCards"), value: s?.overdue_cards ?? null, hint: s ? t("projects.kpi.dueThisWeek", { n: s.due_this_week }) : undefined },
    { id: "hours", label: t("projects.kpi.hours"), value: s?.hours_this_week ?? null, hint: t("projects.kpi.hoursHint") },
  ];
  if (s?.spent !== null && s?.spent !== undefined) {
    items.push({ id: "spent", label: t("projects.kpi.spent"), value: s.spent, format: "money", currency: s.currency, compact: true, hint: s.budget ? t("projects.kpi.ofBudget", { budget: fmt.money(s.budget, s.currency, { compact: true }) }) : undefined });
  }
  return items;
});

const viewOptions = computed(() => [
  { value: "cards" as const, label: t("projects.view.cards"), icon: LayoutGrid, iconOnly: true },
  { value: "table" as const, label: t("projects.view.table"), icon: Rows3, iconOnly: true },
]);

const columns = computed<TableColumn<ProjectItem>[]>(() => [
  { id: "name", header: t("projects.col.project"), minWidth: 280, hideable: false, sortable: true, sticky: true, value: (r) => `${r.key} ${r.name}` },
  { id: "status", header: t("projects.col.status"), width: 130, value: (r) => t(`projects.status.${r.status}`) },
  { id: "health", header: t("projects.col.health"), width: 130, value: (r) => (r.health ? t(`projects.health.${r.health}`) : "") },
  { id: "progress", header: t("projects.col.progress"), width: 170, value: (r) => r.progress.percent },
  { id: "lead", header: t("projects.col.lead"), width: 200, value: (r) => r.lead?.name ?? "" },
  { id: "due_on", header: t("projects.col.due"), width: 120, sortable: true, value: (r) => r.due_on },
  { id: "budget", header: t("projects.col.budget"), width: 190, numeric: true, value: (r) => r.spent ?? null },
]);

function open(row: ProjectItem): void {
  void router.push(`/c/${company.currentId}/projects/${row.id}`);
}
</script>

<template>
  <div>
    <PageHeader :title="t('projects.title')" :description="t('projects.description')">
      <template #actions>
        <SegmentedControl v-model="view" :options="viewOptions" size="sm" :aria-label="t('projects.view.label')" />
        <UiButton variant="ghost" :icon="GanttChart" :to="`/c/${company.currentId}/projects/roadmap`">{{ t("projects.nav.roadmap") }}</UiButton>
        <UiButton v-if="canCreate" variant="primary" :icon="FolderPlus" :kbd="isPhone ? undefined : 'N'" @click="creating = true">{{ t("projects.new") }}</UiButton>
      </template>
    </PageHeader>

    <KpiStrip :items="kpis" :loading="summary.isPending.value" class="mb-5 max-md:hidden" />
    <div v-if="summary.data.value" class="no-scrollbar -mx-4 mb-4 flex gap-2 overflow-x-auto px-4 md:hidden" role="list" :aria-label="t('projects.title')">
      <span v-for="item in kpis" :key="item.id" role="listitem" class="flex shrink-0 flex-col rounded-[12px] border border-line bg-surface px-3 py-2">
        <span class="text-[11px] font-medium text-muted">{{ item.label }}</span>
        <span class="text-md font-semibold tabular-nums text-fg">{{ item.format === "money" ? fmt.money(String(item.value ?? "0"), item.currency, { compact: true }) : item.value }}</span>
      </span>
    </div>

    <FilterBar v-model="filters.values.value" v-model:search="search" :defs="filterDefs" searchable :search-placeholder="t('projects.filter.search')" class="mb-4" />

    <ErrorState v-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />

    <template v-else-if="view === 'cards'">
      <div v-if="skeleton" class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <div v-for="n in 6" :key="n" class="ui-card flex flex-col gap-4 p-4">
          <div class="flex gap-3"><SkeletonBlock width="40px" height="40px" radius="11px" /><div class="flex flex-1 flex-col gap-2"><SkeletonBlock width="30%" height="11px" /><SkeletonBlock width="80%" height="16px" /></div></div>
          <div class="flex items-center gap-3"><SkeletonBlock circle height="48px" /><div class="flex flex-1 flex-col gap-2"><SkeletonBlock width="60%" /><SkeletonBlock width="45%" height="11px" /></div></div>
          <SkeletonBlock height="6px" />
          <SkeletonBlock width="50%" height="24px" />
        </div>
      </div>
      <EmptyState
        v-else-if="query.data.value && !rows.length && filtered"
        :icon="SearchX"
        tone="neutral"
        :title="t('projects.empty.filteredTitle')"
        :description="t('projects.empty.filteredBody')"
      >
        <UiButton @click="filters.clear(); search = ''">{{ t("common.filter.clearAll") }}</UiButton>
      </EmptyState>
      <EmptyState v-else-if="query.data.value && !rows.length" :icon="FolderKanban" size="lg" :title="t('projects.empty.title')" :description="t('projects.empty.body')">
        <UiButton v-if="canCreate" variant="primary" :icon="FolderPlus" @click="creating = true">{{ t("projects.empty.action") }}</UiButton>
      </EmptyState>
      <TransitionGroup v-else tag="div" name="cards" class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <ProjectCard v-for="project in rows" :key="project.id" :project="project" :company-id="company.currentId ?? 0" />
      </TransitionGroup>
    </template>

    <DataTable
      v-else
      :state="table"
      :columns="columns"
      :rows="rows"
      row-key="id"
      clickable
      hide-pagination
      :loading="query.isPending.value"
      :fetching="query.isFetching.value"
      :error="query.error.value"
      :retry="() => query.refetch()"
      :filtered="filtered"
      :empty-title="filtered ? t('projects.empty.filteredTitle') : t('projects.empty.title')"
      :empty-description="filtered ? t('projects.empty.filteredBody') : t('projects.empty.body')"
      :empty-icon="FolderKanban"
      csv-name="projects"
      :caption="t('projects.title')"
      @row-click="open"
      @clear-filters="filters.clear(); search = ''"
    >
      <template #cell-name="{ row }">
        <div class="flex min-w-0 items-center gap-3 py-1">
          <ProjectBadge :color="row.color" :icon="row.icon" :size="30" />
          <div class="min-w-0">
            <p class="truncate font-semibold text-fg">{{ row.name }}</p>
            <p class="truncate font-mono text-xs text-muted">{{ row.key }}<span v-if="row.branch" class="font-sans"> · {{ row.branch.name }}</span></p>
          </div>
        </div>
      </template>
      <template #cell-status="{ row }"><StatusPill size="sm" :tone="STATUS_TONE[row.status]" :label="t(`projects.status.${row.status}`)" /></template>
      <template #cell-health="{ row }"><HealthDot :health="row.health" :reported="row.reported?.health ?? null" label /></template>
      <template #cell-progress="{ row }">
        <div class="flex items-center gap-2">
          <ProgressBar :value="row.progress.percent" size="xs" class="flex-1" :tone="row.status === 'completed' ? 'success' : 'primary'" />
          <span class="w-9 text-right text-xs tabular-nums text-muted">{{ row.progress.percent }}%</span>
        </div>
      </template>
      <template #cell-lead="{ row }"><PersonCell :person="row.lead" size="sm" /></template>
      <template #cell-due_on="{ row }"><span class="tabular-nums text-muted">{{ row.due_on ? fmt.day(row.due_on, "medium") : "—" }}</span></template>
      <template #cell-budget="{ row }">
        <div v-if="row.budget && row.spent !== undefined" class="flex flex-col items-end gap-1">
          <span class="text-sm tabular-nums"><MoneyText :value="row.spent" :currency="row.currency" compact /> <span class="text-subtle">/ <MoneyText :value="row.budget" :currency="row.budget_currency" compact /></span></span>
          <ProgressBar :value="Math.min(row.burn ?? 0, 100)" size="xs" :tone="burnTone(row.burn)" class="w-24" />
        </div>
        <span v-else class="text-subtle">—</span>
      </template>
      <template #card="{ row }">
        <div class="flex items-start gap-3">
          <ProjectBadge :color="row.color" :icon="row.icon" :size="36" />
          <div class="min-w-0 flex-1">
            <p class="flex items-center gap-2"><span class="truncate font-semibold text-fg">{{ row.name }}</span><HealthDot :health="row.health" /></p>
            <p class="font-mono text-xs text-muted">{{ row.key }}</p>
            <div class="mt-2 flex items-center gap-2">
              <ProgressBar :value="row.progress.percent" size="xs" class="flex-1" />
              <span class="text-xs tabular-nums text-muted">{{ row.progress.done }}/{{ row.progress.total }}</span>
            </div>
          </div>
        </div>
      </template>
    </DataTable>

    <ProjectFormDialog v-model:open="creating" />
  </div>
</template>

<style scoped>
.cards-move,
.cards-enter-active {
  transition:
    transform var(--dur-drawer, 240ms) var(--ease-out),
    opacity var(--dur-drawer, 240ms) var(--ease-out);
}
.cards-enter-from {
  opacity: 0;
  transform: translate3d(0, 6px, 0);
}
.cards-leave-active {
  display: none;
}
</style>
