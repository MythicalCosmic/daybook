<script setup lang="ts">
/**
 * The board (plan §1.3): To do, In progress, Waiting, Sent back, Done (last 7 days). A card only
 * goes where its rules allow (the server's `moves`): finishing your own work, accepting it or
 * sending it back (which asks why). Other columns dim while dragging. Click a card to open it.
 */
import { useElementSize } from "@vueuse/core";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/ErrorState.vue";
import type { KanbanColumn, KanbanMove } from "@/components/kanban";
import KanbanBoard from "@/components/KanbanBoard.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { returnReasonFields } from "@/components/returnReasons";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useDelayedPending } from "@/lib/useDelayedPending";

import { useBoard, useMoveCard } from "../api";
import { boardOrder, COLUMN_COLOR } from "../meta";
import type { BoardColumnId, TaskRow } from "../types";
import { BOARD_COLUMNS } from "../types";
import TaskCard from "./TaskCard.vue";

const props = defineProps<{ params: Record<string, string | string[]> }>();
const emit = defineEmits<{ open: [task: TaskRow] }>();

const { t } = useI18n();
const confirm = useConfirm();
const { isPhone } = useBreakpoints();

// All five columns fit a laptop screen when they can (gap-3 between them); narrower screens
// scroll sideways with columns no thinner than a readable card.
const host = ref<HTMLElement | null>(null);
const { width } = useElementSize(host);
const columnWidth = computed(() => {
  if (isPhone.value) return 300;
  const fit = Math.floor((width.value - 4 * 12) / BOARD_COLUMNS.length);
  return Math.max(208, Math.min(296, fit || 296));
});

// The board shows every status itself, so the status filter doesn't apply here.
const boardParams = computed(() => {
  const { status: _status, ...rest } = props.params;
  return rest;
});
const query = useBoard(boardParams);
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const move = useMoveCard();

const counts = computed(() => Object.fromEntries((query.data.value?.columns ?? []).map((c) => [c.id, c.count])) as Record<BoardColumnId, number>);
const columns = computed<KanbanColumn[]>(() =>
  BOARD_COLUMNS.map((id) => ({ id, title: t(`tasks.column.${id}`), color: COLUMN_COLOR[id], description: t(`tasks.column.${id}Hint`) })),
);
const cards = computed(() => (query.data.value?.columns ?? []).flatMap((column) => boardOrder(column.items)));

/** Enter on a focused card opens it (Space picks it up to move, as the board says). */
function onEnter(event: KeyboardEvent): void {
  const key = (event.target as HTMLElement | null)?.closest<HTMLElement>("[data-card-key]")?.dataset.cardKey;
  const task = key ? cards.value.find((card) => String(card.id) === key) : undefined;
  if (task && !event.defaultPrevented) emit("open", task);
}

async function onMove(change: KanbanMove<TaskRow>): Promise<void> {
  if (change.from === change.to) return;
  const to = change.to as BoardColumnId;
  let reason = "";
  if (to === "returned") {
    const answer = await confirm({
      title: t("tasks.sendBack.title"),
      message: change.item.title,
      ...returnReasonFields(t),
      reasonLabel: t("tasks.sendBack.reason"),
      reasonPlaceholder: t("tasks.sendBack.placeholder"),
      confirmLabel: t("tasks.action.return"),
      tone: "danger",
    });
    if (!answer) {
      void query.refetch(); // the card snaps back
      return;
    }
    reason = answer.reason;
  }
  try {
    await move.mutateAsync({ task: change.item, to, reason });
    toast.success(t(`tasks.moved.${to}`), { description: change.item.title });
  } catch {
    // Rolled back; the HTTP layer showed why.
  }
}
</script>

<template>
  <div ref="host" class="min-w-0">
    <div v-if="skeleton" class="flex gap-3 overflow-hidden">
      <div v-for="n in 5" :key="n" class="flex w-[288px] shrink-0 flex-col gap-2 rounded-[12px] bg-surface-2/60 p-3">
        <SkeletonBlock width="40%" height="14px" />
        <div v-for="m in 3" :key="m" class="ui-card flex flex-col gap-2 p-3"><SkeletonBlock width="80%" /><SkeletonBlock width="50%" height="12px" /></div>
      </div>
    </div>
    <ErrorState v-else-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="() => query.refetch()" />
    <KanbanBoard
      v-else
      :columns="columns"
      @keydown.enter="onEnter"
      :items="cards"
      :item-key="(task) => task.id"
      :column-of="(task) => task.status"
      :can-drop="(task, _from, to) => task.moves.includes(to as BoardColumnId)"
      :sortable="false"
      :column-width="columnWidth"
      height="max(460px, calc(100dvh - 480px))"
      @move="onMove"
    >
      <template #column-header="{ column }">
        <span class="size-2 shrink-0 rounded-full" :style="{ background: column.color }" aria-hidden="true" />
        <h3 class="min-w-0 truncate text-sm font-semibold text-fg" :title="column.description">{{ column.title }}</h3>
        <span class="rounded-full px-1.5 py-px text-[11px] font-semibold tabular-nums text-muted">{{ counts[column.id as BoardColumnId] ?? 0 }}</span>
      </template>
      <template #card="{ item }">
        <div class="cursor-pointer" @click="emit('open', item)">
          <TaskCard :task="item" />
        </div>
      </template>
      <template #empty="{ column }">{{ t(`tasks.column.${column.id}Empty`) }}</template>
    </KanbanBoard>
  </div>
</template>
