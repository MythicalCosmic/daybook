<script setup lang="ts">
/**
 * The List tab: every card of the board in one sortable table (key, title, list, status, who,
 * deadline, priority, milestone, labels, time), with a search; a row opens the card. On phones the
 * rows become cards.
 */
import { Rows3, Search } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import PersonCell from "@/components/PersonCell.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TextInput from "@/components/TextInput.vue";
import { useDataTable } from "@/components/useDataTable";
import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";
import { rs, useRouteState } from "@/lib/useRouteState";

import { useCards } from "../api";
import { colorVar, DUE_CLASS, dueState, hhmm, TASK_TONE, tint } from "../lib";
import type { Card, ProjectDetail } from "../types";

const props = defineProps<{ project: ProjectDetail }>();

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const now = useNow();
const q = useRouteState("q", rs.string());
const table = useDataTable({ id: "projects.cards", url: true, pageSize: 500, pageSizes: [500], ordering: "" });
const query = useCards(() => props.project.id);

const listName = (id: number | null) => props.project.lists.find((l) => l.id === id)?.name ?? "—";
const listOrder = (id: number | null) => props.project.lists.findIndex((l) => l.id === id);
const milestoneName = (id: number | null) => props.project.milestones.find((m) => m.id === id)?.name ?? "";
const PRIORITY = { urgent: 0, high: 1, normal: 2, low: 3 } as const;

const rows = computed(() => {
  const needle = q.value.trim().toLowerCase();
  const list = (query.data.value ?? []).filter((c) => !needle || `${c.key} ${c.title} ${c.assignee?.name ?? ""}`.toLowerCase().includes(needle));
  const ordering = table.ordering.value;
  const desc = ordering.startsWith("-");
  const field = ordering.replace(/^-/, "");
  const value = (c: Card): string | number => {
    switch (field) {
      case "title":
        return c.title.toLowerCase();
      case "list":
        return listOrder(c.list_id);
      case "assignee":
        return c.assignee?.name.toLowerCase() ?? "~";
      case "due_at":
        return c.due_at ?? "9999";
      case "priority":
        return PRIORITY[c.priority];
      case "minutes":
        return c.minutes;
      default:
        return listOrder(c.list_id) * 1e9 + c.position;
    }
  };
  return list.sort((a, b) => {
    const x = value(a);
    const y = value(b);
    const result = x < y ? -1 : x > y ? 1 : a.id - b.id;
    return desc ? -result : result;
  });
});

const columns = computed<TableColumn<Card>[]>(() => [
  { id: "title", header: t("projects.col.card"), minWidth: 300, sortable: true, hideable: false, sticky: true },
  { id: "list", header: t("projects.col.list"), width: 140, sortable: true, value: (c) => listName(c.list_id) },
  { id: "status", header: t("projects.col.status"), width: 160, value: (c) => t(`projects.taskStatus.${c.status}`) },
  { id: "assignee", header: t("projects.col.assignee"), width: 190, sortable: true, value: (c) => c.assignee?.name ?? "" },
  { id: "due_at", header: t("projects.col.due"), width: 140, sortable: true },
  { id: "priority", header: t("projects.col.priority"), width: 110, sortable: true, value: (c) => t(`projects.taskPriority.${c.priority}`) },
  { id: "milestone", header: t("projects.col.milestone"), width: 170, value: (c) => milestoneName(c.milestone_id) },
  { id: "labels", header: t("projects.col.labels"), width: 200, value: (c) => c.label_ids.map((id) => props.project.labels.find((l) => l.id === id)?.name).join(", ") },
  { id: "minutes", header: t("projects.col.time"), width: 90, numeric: true, sortable: true, value: (c) => hhmm(c.minutes) },
]);

function open(card: Card): void {
  void router.replace({ query: { ...router.currentRoute.value.query, card: String(card.id) } });
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <TextInput v-model="q" :icon="Search" size="sm" clearable :placeholder="t('projects.board.search')" class="w-full sm:w-72" />
    <DataTable
      :state="table"
      :columns="columns"
      :rows="rows"
      row-key="id"
      clickable
      hide-pagination
      :loading="query.isPending.value"
      :error="query.error.value"
      :retry="() => query.refetch()"
      :filtered="!!q"
      :empty-title="t('projects.list.emptyTitle')"
      :empty-description="t('projects.list.emptyBody')"
      :empty-icon="Rows3"
      :csv-name="`${project.key}-cards`"
      :caption="t('projects.tab.list')"
      @row-click="open"
      @clear-filters="q = ''"
    >
      <template #cell-title="{ row }">
        <div class="flex min-w-0 items-center gap-2 py-1">
          <span class="shrink-0 font-mono text-xs text-subtle">{{ row.key }}</span>
          <span class="truncate font-medium" :class="row.status === 'done' ? 'text-muted line-through' : 'text-fg'">{{ row.title }}</span>
        </div>
      </template>
      <template #cell-status="{ row }"><StatusPill size="sm" :tone="TASK_TONE[row.status]" :label="t(`projects.taskStatus.${row.status}`)" /></template>
      <template #cell-assignee="{ row }"><PersonCell :person="row.assignee" size="sm" /></template>
      <template #cell-due_at="{ row }">
        <span v-if="row.due_at" :class="['inline-flex h-6 items-center rounded-[6px] px-1.5 text-xs font-medium tabular-nums', DUE_CLASS[dueState(row, now) ?? 'later']]">{{ fmt.instant(row.due_at, "short") }}</span>
        <span v-else class="text-subtle">—</span>
      </template>
      <template #cell-labels="{ row }">
        <div class="flex flex-wrap gap-1">
          <span
            v-for="id in row.label_ids"
            :key="id"
            class="rounded-full px-2 py-0.5 text-[11px] font-semibold"
            :style="{ background: tint(project.labels.find((l) => l.id === id)?.color, 18), color: colorVar(project.labels.find((l) => l.id === id)?.color) }"
            >{{ project.labels.find((l) => l.id === id)?.name }}</span
          >
        </div>
      </template>
      <template #card="{ row }">
        <div class="flex flex-col gap-1.5">
          <p class="flex items-center gap-2"><span class="font-mono text-xs text-subtle">{{ row.key }}</span><StatusPill size="sm" :tone="TASK_TONE[row.status]" :label="t(`projects.taskStatus.${row.status}`)" /></p>
          <p class="font-medium text-fg">{{ row.title }}</p>
          <div class="flex items-center gap-2 text-xs text-muted">
            <PersonCell :person="row.assignee" size="sm" />
            <span class="flex-1" />
            <span v-if="row.due_at" class="tabular-nums">{{ fmt.instant(row.due_at, "short") }}</span>
          </div>
        </div>
      </template>
    </DataTable>
  </div>
</template>
