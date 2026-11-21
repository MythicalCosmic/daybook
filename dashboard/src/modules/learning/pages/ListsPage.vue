<script setup lang="ts">
/**
 * Unchangeable lists (O‘zgarmas ro‘yxatlar): study registers kept like a bound journal. Topics are
 * rows, students are columns, and every mark a teacher writes stays; a mistake is taken back by a
 * visible correction. Each list with its teacher and branch, its size, how much is studied, open or
 * sealed, and its dates. `?new=1` asks for a title and opens the new list.
 */
import { BookLock, Lock, NotebookPen, Plus } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import { useDataTable } from "@/components/useDataTable";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useStudyLists } from "../api";
import ListDialog from "../components/ListDialog.vue";
import { LIST_STATE_TONES, percentOf, stateCounts } from "../lists";
import type { StudyListDetail, StudyListRow } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const router = useRouter();

const STATES = ["open", "sealed", "all"] as const;
const search = useRouteState("q", rs.string(""));
const state = useRouteState("state", rs.enum(STATES, "all"));
const creating = useRouteState("new", rs.boolean(false));
const canManage = computed(() => company.can("learning.manage"));
// The state is picked here (the counts need every row); the words and the branch are the server's.
const params = computed(() => ({
  q: search.value || undefined,
  branch: company.branchFilter.length === 1 ? company.branchFilter[0] : undefined,
}));
const lists = useStudyLists(params);
const table = useDataTable({ id: "learning.lists", pageSize: 200 });

const all = computed(() => lists.data.value ?? []);
const counts = computed(() => stateCounts(all.value));
const rows = computed(() => (lists.data.value ? (state.value === "all" ? all.value : all.value.filter((row) => row.state === state.value)) : undefined));
const stateOptions = computed(() =>
  STATES.map((value) => ({
    value,
    label: value === "all" ? t("common.all") : t(`learning.lists.filter.${value}`),
    icon: value === "sealed" ? Lock : undefined,
    count: lists.data.value ? counts.value[value] : undefined,
  })),
);
const filtered = computed(() => Boolean(search.value || state.value !== "all"));
const nothingYet = computed(() => lists.data.value !== undefined && !all.value.length && !search.value);

const columns = computed<TableColumn<StudyListRow>[]>(() => [
  { id: "title", header: t("learning.lists.col.list"), minWidth: 280, sticky: true, csv: (row) => row.title },
  {
    id: "size",
    header: t("learning.lists.col.size"),
    width: 200,
    value: (row) => row.cells,
    csv: (row) => `${row.topics} × ${row.students}`,
  },
  { id: "progress", header: t("learning.lists.col.progress"), minWidth: 220, value: (row) => percentOf(row.studied, row.cells), csv: (row) => `${row.studied}/${row.cells}` },
  { id: "state", header: t("learning.lists.col.state"), width: 140, csv: (row) => t(`learning.lists.state.${row.state}`) },
  { id: "dates", header: t("learning.lists.col.dates"), width: 200, value: (row) => row.sealed_at ?? row.created_at },
]);

const subtitle = (row: Pick<StudyListRow, "teacher" | "branch">) => [row.teacher, row.branch?.name].filter(Boolean).join(" · ");

function open(row: Pick<StudyListRow, "id">): void {
  void router.push(`/c/${company.currentId}/learning/lists/${row.id}`);
}
async function created(list: StudyListDetail): Promise<void> {
  // Closing the dialog takes `?new=1` off the URL in a queued replace (useRouteState); going to
  // the list after it keeps that replace from cancelling the way there.
  await new Promise<void>((resolve) => queueMicrotask(resolve));
  open(list);
}
function clearFilters(): void {
  search.value = "";
  state.value = "all";
}
</script>

<template>
  <div>
    <PageHeader :title="t('learning.nav.lists')" :description="t('learning.lists.description')" clamp-description>
      <template #actions>
        <UiButton v-if="canManage" variant="primary" :icon="Plus" data-testid="lists-new" @click="creating = true">{{ t("learning.lists.new") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="nothingYet" class="ui-card">
      <EmptyState :icon="NotebookPen" :title="t('learning.lists.emptyTitle')" :description="t('learning.lists.emptyBody')">
        <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="creating = true">{{ t("learning.lists.new") }}</UiButton>
      </EmptyState>
    </div>
    <DataTable
      v-else
      :state="table"
      :columns="columns"
      :rows="rows"
      :total="rows?.length"
      row-key="id"
      :loading="lists.isPending.value"
      :fetching="lists.isFetching.value"
      :error="lists.error.value"
      :retry="() => lists.refetch()"
      clickable
      hide-pagination
      :filtered="filtered"
      csv-name="unchangeable-lists"
      @row-click="open"
      @clear-filters="clearFilters"
    >
      <template #toolbar>
        <div class="flex flex-wrap items-center gap-2">
          <TextInput v-model="search" :debounce="300" type="search" size="sm" class="w-full sm:w-64" :placeholder="t('learning.lists.search')" clearable />
          <SegmentedControl v-model="state" :options="stateOptions" size="sm" :aria-label="t('learning.lists.col.state')" />
        </div>
      </template>
      <template #cell-title="{ row }">
        <div class="flex min-w-0 items-center gap-2.5">
          <span
            :class="['grid size-8 shrink-0 place-items-center rounded-[8px]', row.state === 'sealed' ? 'bg-accent-soft text-accent-fg' : 'bg-surface-2 text-muted']"
            aria-hidden="true"
          >
            <component :is="row.state === 'sealed' ? BookLock : NotebookPen" :size="16" />
          </span>
          <span class="min-w-0">
            <span class="block truncate font-medium text-fg">{{ row.title }}</span>
            <span v-if="subtitle(row)" class="block truncate text-xs text-muted">{{ subtitle(row) }}</span>
          </span>
        </div>
      </template>
      <template #cell-size="{ row }">
        <span class="text-sm text-fg tabular-nums">
          {{ t("learning.lists.topicsCount", { n: row.topics }, row.topics) }}
          <span class="text-subtle" aria-hidden="true">×</span>
          {{ t("learning.lists.studentsCount", { n: row.students }, row.students) }}
        </span>
      </template>
      <template #cell-progress="{ row }">
        <div class="flex items-center gap-2">
          <ProgressBar class="flex-1" size="sm" :value="row.studied" :max="row.cells || 1" tone="success" />
          <span class="w-20 text-right text-xs text-muted tabular-nums">{{ row.cells ? `${row.studied}/${row.cells}` : "—" }}</span>
        </div>
      </template>
      <template #cell-state="{ row }">
        <StatusPill :tone="LIST_STATE_TONES[row.state]" :icon="row.state === 'sealed' ? Lock : undefined" :label="t(`learning.lists.state.${row.state}`)" size="sm" />
      </template>
      <template #cell-dates="{ row }">
        <span class="flex flex-col text-xs leading-5 text-muted">
          <span>{{ t("learning.lists.createdOn", { day: fmt.instant(row.created_at, "date") }) }}</span>
          <span v-if="row.sealed_at" class="text-fg">{{ t("learning.lists.sealedOn", { day: fmt.instant(row.sealed_at, "date") }) }}</span>
        </span>
      </template>
      <template #card="{ row }">
        <div class="flex flex-col gap-2.5">
          <div class="flex items-start justify-between gap-3">
            <span class="min-w-0">
              <span class="block truncate font-medium text-fg">{{ row.title }}</span>
              <span v-if="subtitle(row)" class="block truncate text-xs text-muted">{{ subtitle(row) }}</span>
            </span>
            <StatusPill :tone="LIST_STATE_TONES[row.state]" :icon="row.state === 'sealed' ? Lock : undefined" :label="t(`learning.lists.state.${row.state}`)" size="sm" />
          </div>
          <div class="flex items-center gap-2">
            <ProgressBar class="flex-1" size="sm" :value="row.studied" :max="row.cells || 1" tone="success" />
            <span class="text-xs text-muted tabular-nums">{{ row.cells ? `${row.studied}/${row.cells}` : "—" }}</span>
          </div>
          <p class="text-xs text-muted tabular-nums">
            {{ t("learning.lists.topicsCount", { n: row.topics }, row.topics) }} × {{ t("learning.lists.studentsCount", { n: row.students }, row.students) }}
            · {{ row.sealed_at ? t("learning.lists.sealedOn", { day: fmt.instant(row.sealed_at, "date") }) : t("learning.lists.createdOn", { day: fmt.instant(row.created_at, "date") }) }}
          </p>
        </div>
      </template>
    </DataTable>

    <ListDialog v-model:open="creating" @saved="created" />
  </div>
</template>
