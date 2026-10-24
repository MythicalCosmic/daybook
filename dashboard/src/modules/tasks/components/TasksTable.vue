<script setup lang="ts">
/**
 * Every task as a table (plan §6.2): server paging and sorting, a column picker, selection with the
 * bulk bar (reassign, move the deadline, priority, nudge, confirm, cancel), cards on phones. Rows
 * open the drawer (`?task=`).
 */
import { BellRing, CalendarClock, CheckCheck, Eye, EyeOff, Flag, FolderKanban, Gift, Inbox, Repeat, UserRoundCog, X } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import DataTable from "@/components/DataTable.vue";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import MoneyCell from "@/components/MoneyCell.vue";
import PersonCell from "@/components/PersonCell.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import UiPopover from "@/components/UiPopover.vue";
import { useConfirm } from "@/components/useConfirm";
import type { DataTableState } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { usePermission } from "@/lib/usePermission";

import { useBulk, useTaskList, useTaskOptions } from "../api";
import { cardKey, isUnseen } from "../meta";
import type { BulkAction, BulkInput, TaskPriority, TaskRow } from "../types";
import { PRIORITIES } from "../types";
import DueLabel from "./DueLabel.vue";
import PriorityFlag from "./PriorityFlag.vue";
import TaskCard from "./TaskCard.vue";
import TaskFlags from "./TaskFlags.vue";
import TaskStatusPill from "./TaskStatusPill.vue";

const props = defineProps<{
  state: DataTableState;
  params: Record<string, string | string[]>;
  filtered: boolean;
  activeId: number | null;
}>();

const emit = defineEmits<{ open: [task: TaskRow]; "clear-filters": []; "include-routines": [] }>();

const { t } = useI18n();
const fmt = useFormat();
const { can } = usePermission();
const confirm = useConfirm();

const query = useTaskList(computed(() => ({ ...props.params, ...props.state.params.value })));
// The list leaves routine work out (the Tasks page's one-off work): an empty list says so and
// offers it, since a routine's title finds nothing here otherwise.
const withoutRoutines = computed(() => props.params.routines === "without");
const emptyBody = computed(() => {
  if (props.filtered) return t(withoutRoutines.value ? "tasks.empty.filteredRoutinesBody" : "tasks.empty.filteredBody");
  return t("tasks.empty.body");
});
const options = useTaskOptions();
const people = computed(() => (options.data.value?.people ?? []).map((p) => ({ id: p.id, name: p.name, photo_url: p.photo_url, subtitle: [p.position, p.branch].filter(Boolean).join(" · ") })));

watch(
  () => JSON.stringify(props.params),
  () => props.state.resetPage(),
);

const columns = computed<TableColumn<TaskRow>[]>(() => [
  { id: "title", header: t("tasks.col.task"), sortable: true, minWidth: 260, hideable: false, sticky: true, csv: (row) => row.title },
  { id: "assignee", header: t("tasks.col.assignee"), sortable: true, width: 210, value: (row) => row.assignee.name },
  { id: "status", header: t("tasks.col.status"), sortable: true, width: 150, value: (row) => t(`tasks.status.${row.status}`) },
  { id: "due_at", header: t("tasks.col.due"), sortable: true, width: 260, value: (row) => row.due_at, csv: (row) => (row.due_at ? fmt.instant(row.due_at) : "") },
  { id: "priority", header: t("tasks.col.priority"), sortable: true, width: 120, value: (row) => t(`tasks.priority.${row.priority}`) },
  { id: "branch", header: t("tasks.col.branch"), width: 130, value: (row) => row.branch?.name ?? "" },
  { id: "routine", header: t("tasks.col.routine"), width: 190, value: (row) => row.routine?.title ?? "" },
  { id: "created_by", header: t("tasks.col.givenBy"), width: 170, value: (row) => row.created_by?.name ?? "" },
  { id: "proof", header: t("tasks.col.proof"), width: 90, align: "center", value: (row) => (row.has_proof ? "✓" : "") },
  { id: "reward", header: t("tasks.col.reward"), width: 140, numeric: true, value: (row) => row.reward ?? "" },
  { id: "completed_at", header: t("tasks.col.finished"), sortable: true, width: 160, value: (row) => row.completed_at, csv: (row) => (row.completed_at ? fmt.instant(row.completed_at) : "") },
  // When the assignee first opened it (contract 10): a column to turn on.
  { id: "seen_at", header: t("tasks.field.seen"), width: 150, value: (row) => row.seen_at ?? "", csv: (row) => (row.seen_at ? fmt.instant(row.seen_at) : "") },
]);

// Bulk actions -------------------------------------------------------------------------------
const bulk = useBulk();
const reassignOpen = ref(false);
const reassignTo = ref<number | null>(null);

async function runBulk(selected: string[], clear: () => void, action: BulkAction, payload?: BulkInput["payload"]): Promise<void> {
  const ids = selected.map(Number);
  try {
    const result = await bulk.mutateAsync({ ids, action, payload });
    if (result.failed === 0) toast.success(t("tasks.bulk.done", { n: result.done }, result.done));
    else {
      const first = result.results.find((r) => !r.ok)?.error ?? "";
      toast.warning(t("tasks.bulk.partly", { done: result.done, failed: result.failed }), { description: first });
    }
    clear();
  } catch {
    // The HTTP layer showed why.
  }
}

async function cancelMany(selected: string[], clear: () => void): Promise<void> {
  const answer = await confirm({
    title: t("tasks.bulk.cancelTitle", { n: selected.length }),
    message: t("tasks.bulk.cancelBody"),
    tone: "danger",
    confirmLabel: t("tasks.bulk.cancel"),
    cancelLabel: t("common.close"),
  });
  if (answer) await runBulk(selected, clear, "cancel");
}

function dueMenu(selected: string[], clear: () => void): MenuEntry[] {
  return [1, 2, 7].map((days) => ({
    label: t("tasks.bulk.shiftDays", { n: days }, days),
    onSelect: () => runBulk(selected, clear, "reschedule", { shift_days: days }),
  }));
}

function priorityMenu(selected: string[], clear: () => void): MenuEntry[] {
  return PRIORITIES.map((priority: TaskPriority) => ({
    label: t(`tasks.priority.${priority}`),
    onSelect: () => runBulk(selected, clear, "priority", { priority }),
  }));
}

async function reassignMany(selected: string[], clear: () => void): Promise<void> {
  if (!reassignTo.value) return;
  reassignOpen.value = false;
  await runBulk(selected, clear, "reassign", { assignee_id: reassignTo.value });
  reassignTo.value = null;
}
</script>

<template>
  <DataTable
    :state="state"
    :columns="columns"
    :rows="query.data.value?.results"
    :total="query.data.value?.count"
    row-key="id"
    :loading="query.isPending.value"
    :fetching="query.isFetching.value"
    :error="query.error.value"
    :retry="() => query.refetch()"
    selectable
    clickable
    :active-key="activeId"
    :filtered="filtered"
    :empty-title="filtered ? t('tasks.empty.filteredTitle') : t('tasks.empty.title')"
    :empty-description="filtered ? t('tasks.empty.filteredBody') : t('tasks.empty.body')"
    export-kind="tasks.list"
    :export-params="params"
    :csv-name="t('tasks.title')"
    :row-class="(row) => (row.status === 'cancelled' ? 'opacity-55' : undefined)"
    hide-toolbar
    @row-click="(row) => emit('open', row)"
    @clear-filters="emit('clear-filters')"
  >
    <template #empty>
      <EmptyState size="sm" :icon="Inbox" tone="neutral" :title="filtered ? t('tasks.empty.filteredTitle') : t('tasks.empty.title')" :description="emptyBody">
        <div v-if="filtered || withoutRoutines" class="flex flex-wrap justify-center gap-2">
          <UiButton v-if="filtered" size="sm" @click="emit('clear-filters')">{{ t("common.filter.clearAll") }}</UiButton>
          <UiButton v-if="withoutRoutines" size="sm" :icon="Repeat" data-testid="empty-include-routines" @click="emit('include-routines')">{{ t("tasks.filter.includeRoutines") }}</UiButton>
        </div>
      </EmptyState>
    </template>
    <template #cell-title="{ row }">
      <div class="min-w-0 py-0.5">
        <p :class="['truncate font-medium', row.status === 'done' || row.status === 'cancelled' ? 'text-muted' : 'text-fg']" :title="row.project ? `${cardKey(row.project)} · ${row.title}` : row.title">
          <span v-if="row.project" class="mr-1 font-mono text-xs font-semibold text-subtle">{{ cardKey(row.project) }}</span>{{ row.title }}
        </p>
        <p class="flex min-w-0 items-center gap-2 text-xs text-subtle">
          <span v-if="row.routine" class="inline-flex min-w-0 items-center gap-1"><Repeat :size="11" aria-hidden="true" /><span class="truncate">{{ row.routine.onboarding ? t("tasks.kind.onboarding") : t("tasks.kind.routine") }}</span></span>
          <span v-else-if="row.project" class="inline-flex min-w-0 items-center gap-1"><FolderKanban :size="11" aria-hidden="true" /><span class="truncate">{{ row.project.name }}</span></span>
          <span v-else>{{ t(`tasks.kind.${row.kind}`) }}</span>
          <span v-if="row.checklist.total" :class="['inline-flex items-center gap-0.5 tabular-nums', row.checklist.done === row.checklist.total && 'text-success']"><CheckCheck :size="11" />{{ row.checklist.done }}/{{ row.checklist.total }}</span>
          <span v-if="row.reward" class="inline-flex items-center gap-0.5 text-success"><Gift :size="11" />{{ t("tasks.reward.short") }}</span>
          <TaskFlags :task="row" />
        </p>
      </div>
    </template>
    <template #cell-seen_at="{ row }">
      <span v-if="row.seen_at" class="inline-flex items-center gap-1 text-sm tabular-nums text-muted" :title="fmt.instant(row.seen_at, 'datetime')"><Eye :size="13" aria-hidden="true" />{{ fmt.instant(row.seen_at, "short") }}</span>
      <span v-else-if="isUnseen(row)" class="inline-flex items-center gap-1 text-sm text-subtle"><EyeOff :size="13" aria-hidden="true" />{{ t("tasks.seen.not") }}</span>
      <span v-else class="text-subtle">—</span>
    </template>
    <template #cell-assignee="{ row }">
      <PersonCell :person="row.assignee" :subtitle="row.assignee.position" size="sm" link />
    </template>
    <template #cell-status="{ row }">
      <TaskStatusPill :status="row.status" :overdue="row.is_overdue" />
    </template>
    <template #cell-due_at="{ row }">
      <DueLabel :due="row.due_at" :overdue="row.is_overdue" />
    </template>
    <template #cell-priority="{ row }">
      <PriorityFlag :priority="row.priority" quiet />
    </template>
    <template #cell-branch="{ row }">
      <span class="truncate text-sm text-muted">{{ row.branch?.name ?? "—" }}</span>
    </template>
    <template #cell-proof="{ row }">
      <img v-if="row.proof_thumb" :src="row.proof_thumb" alt="" loading="lazy" class="mx-auto size-8 rounded-[6px] border border-line object-cover" />
      <span v-else-if="row.has_proof" class="text-success">✓</span>
      <span v-else class="text-subtle">—</span>
    </template>
    <template #cell-reward="{ row }">
      <MoneyCell :value="row.reward" />
    </template>
    <template #cell-completed_at="{ row }">
      <span class="text-sm tabular-nums text-muted">{{ row.completed_at ? fmt.instant(row.completed_at, "short") : "—" }}</span>
    </template>
    <template #card="{ row }">
      <TaskCard :task="row" show-status />
    </template>
    <template #bulk="{ selected, clear }">
      <UiPopover v-if="can(['tasks.assign', 'tasks.templates'])" v-model:open="reassignOpen" align="center" side="top" width="300px">
        <template #trigger><UiButton size="sm" :icon="UserRoundCog">{{ t("tasks.action.reassign") }}</UiButton></template>
        <div class="flex flex-col gap-2 p-3">
          <p class="text-sm font-semibold text-fg">{{ t("tasks.bulk.reassignTitle", { n: selected.length }) }}</p>
          <PersonPicker v-model="reassignTo" :people="people" size="sm" />
          <UiButton size="sm" variant="primary" :disabled="!reassignTo" :loading="bulk.isPending.value" @click="reassignMany(selected, clear)">{{ t("tasks.action.reassign") }}</UiButton>
        </div>
      </UiPopover>
      <DropdownMenu :items="dueMenu(selected, clear)">
        <template #trigger><UiButton size="sm" :icon="CalendarClock">{{ t("tasks.bulk.moveDue") }}</UiButton></template>
      </DropdownMenu>
      <DropdownMenu :items="priorityMenu(selected, clear)">
        <template #trigger><UiButton size="sm" :icon="Flag">{{ t("tasks.col.priority") }}</UiButton></template>
      </DropdownMenu>
      <UiButton size="sm" :icon="BellRing" @click="runBulk(selected, clear, 'nudge')">{{ t("tasks.action.nudge") }}</UiButton>
      <UiButton v-if="can('tasks.confirm')" size="sm" :icon="CheckCheck" @click="runBulk(selected, clear, 'confirm')">{{ t("tasks.action.confirm") }}</UiButton>
      <UiButton size="sm" variant="ghost" :icon="X" class="hover:!text-danger" data-testid="bulk-cancel" @click="cancelMany(selected, clear)">{{ t("tasks.bulk.cancel") }}</UiButton>
    </template>
  </DataTable>
</template>
