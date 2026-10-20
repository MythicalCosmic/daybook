<script setup lang="ts" generic="Item">
/**
 * A board of columns and cards (plan §6.3; Tasks, Projects, CRM and Hiring use it). Cards drag
 * between and within columns (vue-draggable-plus); `canDrop(item, from, to)` decides where a card
 * may go, so disallowed columns dim and refuse it while dragging. The board never moves data on
 * its own server: it emits `move` with the card, both columns, the new index and its neighbours,
 * and the page saves it (optimistically; on failure it refetches and the board snaps back).
 * Keyboard: focus a card, Space picks it up, arrows move it, Space drops, Escape cancels.
 *
 *   <KanbanBoard :columns="lists" :items="cards" :item-key="(c) => c.id" :column-of="(c) => c.list_id"
 *     :can-drop="(card, from, to) => card.actions.includes(to)" @move="saveMove">
 *     <template #card="{ item }">…</template>
 *     <template #quick-add="{ column, close }">…</template>
 *   </KanbanBoard>
 */
import { Plus } from "@lucide/vue";
import { VueDraggable } from "vue-draggable-plus";
import { computed, nextTick, ref, shallowRef, toRaw, useId, watch, type Ref } from "vue";
import { useI18n } from "vue-i18n";

import { describeMove, findCard, groupItems, moveCard, nextColumn, type KanbanColumn, type KanbanMove, type Lists } from "./kanban";

const props = withDefaults(
  defineProps<{
    columns: KanbanColumn[];
    items: Item[];
    itemKey: (item: Item) => string | number;
    columnOf: (item: Item) => string;
    canDrop?: (item: Item, from: string, to: string) => boolean;
    /** Reordering inside a column (off for boards sorted by the server). */
    sortable?: boolean;
    disabled?: boolean;
    columnWidth?: number;
    /** Board height; columns scroll inside it. */
    height?: string;
  }>(),
  { canDrop: undefined, sortable: true, disabled: false, columnWidth: 288, height: "calc(100dvh - 260px)" },
);

const emit = defineEmits<{ move: [move: KanbanMove<Item>]; "add-open": [column: KanbanColumn] }>();

defineSlots<{
  card: (props: { item: Item; column: KanbanColumn; lifted: boolean }) => unknown;
  "column-header"?: (props: { column: KanbanColumn; count: number }) => unknown;
  "column-actions"?: (props: { column: KanbanColumn }) => unknown;
  "quick-add"?: (props: { column: KanbanColumn; close: () => void }) => unknown;
  empty?: (props: { column: KanbanColumn }) => unknown;
}>();

const { t } = useI18n();
const boardId = useId();
const helpId = `${boardId}-help`;
const keyOf = (item: Item) => String(props.itemKey(item));

const lists = ref<Lists<Item>>({}) as Ref<Lists<Item>>;
const dragging = shallowRef<{ item: Item; from: string } | null>(null);
const lifted = shallowRef<{ key: string; from: string; snapshot: Lists<Item> } | null>(null);
const announcement = ref("");
const adding = ref<string | null>(null);

function sync(): void {
  lists.value = groupItems(props.columns, props.items, props.columnOf);
}
watch(
  () => [props.items, props.columns] as const,
  () => {
    if (!dragging.value && !lifted.value) sync();
  },
  { immediate: true, deep: false },
);

/** Cards keep their identity when they change columns (the library would otherwise copy them through JSON). */
const keepReference = (item: Item) => item;

/** The card objects the page gave, not the board's reactive copies. */
function plain(move: KanbanMove<Item>): KanbanMove<Item> {
  return { ...move, item: toRaw(move.item), before: move.before && toRaw(move.before), after: move.after && toRaw(move.after) };
}

function allowed(item: Item, from: string, to: string): boolean {
  if (from === to) return true;
  return props.canDrop ? props.canDrop(item, from, to) : true;
}

const blocked = computed(() => {
  const active = dragging.value ?? (lifted.value ? { item: findCard(lists.value, lifted.value.key, keyOf)?.item, from: lifted.value.from } : null);
  if (!active?.item) return new Set<string>();
  const item = active.item;
  return new Set(props.columns.filter((column) => !allowed(item, active.from, column.id)).map((column) => column.id));
});

function itemFromElement(el: HTMLElement | null | undefined): Item | null {
  const key = el?.dataset.cardKey;
  if (!key) return null;
  return findCard(lists.value, key, keyOf)?.item ?? null;
}

function groupFor(columnId: string) {
  return {
    name: boardId,
    pull: true,
    put: (_to: unknown, _from: unknown, dragEl: HTMLElement) => {
      const item = itemFromElement(dragEl);
      const from = dragging.value?.from;
      return !!item && !!from && allowed(item, from, columnId);
    },
  };
}

function onStart(event: { item: HTMLElement; from: HTMLElement }): void {
  const item = itemFromElement(event.item);
  const from = event.from.dataset.column;
  if (item && from) dragging.value = { item, from };
}

function onEnd(event: { item: HTMLElement; from: HTMLElement; to: HTMLElement; oldIndex?: number; newIndex?: number }): void {
  const from = event.from.dataset.column;
  const to = event.to.dataset.column;
  const key = event.item.dataset.cardKey;
  dragging.value = null;
  if (!from || !to || !key) return;
  if (from === to && event.oldIndex === event.newIndex) return;
  const move = describeMove(lists.value, key, from, keyOf);
  if (move) {
    emit("move", plain(move));
    announce(t("common.kanban.dropped", { title: titleOf(move.item), column: columnTitle(move.to) }));
  }
}

// Keyboard moves.
function titleOf(item: Item): string {
  const record = item as Record<string, unknown>;
  return String(record.title ?? record.name ?? keyOf(item));
}
function columnTitle(id: string): string {
  return props.columns.find((column) => column.id === id)?.title ?? id;
}
function announce(text: string): void {
  announcement.value = "";
  void nextTick(() => (announcement.value = text));
}

async function focusCard(key: string): Promise<void> {
  await nextTick();
  document.querySelector<HTMLElement>(`[data-board="${boardId}"] [data-card-key="${CSS.escape(key)}"]`)?.focus();
}

function onCardKeydown(event: KeyboardEvent, item: Item): void {
  if (props.disabled) return;
  const key = keyOf(item);
  const where = findCard(lists.value, key, keyOf);
  if (!where) return;
  if (!lifted.value) {
    if (event.key === " ") {
      event.preventDefault();
      lifted.value = { key, from: where.column, snapshot: lists.value };
      announce(t("common.kanban.lifted", { title: titleOf(item) }));
    }
    return;
  }
  if (lifted.value.key !== key) return;
  if (event.key === " " || event.key === "Enter") {
    event.preventDefault();
    const from = lifted.value.from;
    const before = findCard(lifted.value.snapshot, key, keyOf);
    lifted.value = null;
    const move = describeMove(lists.value, key, from, keyOf);
    if (move && (move.to !== from || move.index !== before?.index)) {
      emit("move", plain(move));
      announce(t("common.kanban.dropped", { title: titleOf(item), column: columnTitle(move.to) }));
    } else announce(t("common.kanban.cancelled"));
    return;
  }
  if (event.key === "Escape") {
    event.preventDefault();
    lists.value = lifted.value.snapshot;
    lifted.value = null;
    announce(t("common.kanban.cancelled"));
    void focusCard(key);
    return;
  }
  let target: { column: string; index: number } | null = null;
  if (event.key === "ArrowUp" && props.sortable) target = { column: where.column, index: where.index - 1 };
  if (event.key === "ArrowDown" && props.sortable) target = { column: where.column, index: where.index + 1 };
  if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    const from = lifted.value.from;
    const column = nextColumn(props.columns, where.column, event.key === "ArrowLeft" ? -1 : 1, (id) => allowed(item, from, id));
    if (column) target = { column, index: props.sortable ? where.index : (lists.value[column]?.length ?? 0) };
  }
  if (!target) return;
  event.preventDefault();
  const length = lists.value[target.column]?.length ?? 0;
  const index = Math.max(0, Math.min(target.column === where.column ? length - 1 : length, target.index));
  lists.value = moveCard(lists.value, key, target.column, index, keyOf);
  announce(t("common.kanban.over", { title: titleOf(item), column: columnTitle(target.column), position: index + 1 }));
  void focusCard(key);
}

function openAdd(column: KanbanColumn): void {
  adding.value = column.id;
  emit("add-open", column);
}

function wipTone(column: KanbanColumn): "over" | "at" | null {
  if (!column.wipLimit) return null;
  const count = lists.value[column.id]?.length ?? 0;
  return count > column.wipLimit ? "over" : count === column.wipLimit ? "at" : null;
}
</script>

<template>
  <div class="relative min-w-0" :data-board="boardId">
    <p :id="helpId" class="sr-only">{{ t("common.kanban.help") }}</p>
    <p class="sr-only" aria-live="assertive">{{ announcement }}</p>
    <div class="no-scrollbar flex snap-x snap-mandatory gap-3 overflow-x-auto pb-2 md:snap-none" :style="{ height }">
      <section
        v-for="column in columns"
        :key="column.id"
        :aria-label="column.title"
        :class="[
          'flex h-full shrink-0 snap-start flex-col rounded-[12px] bg-surface-2/60 transition-[opacity,box-shadow] duration-150 max-md:w-[85vw] dark:bg-surface-2/70',
          blocked.has(column.id) && 'opacity-45',
          (dragging || lifted) && !blocked.has(column.id) && 'shadow-[inset_0_0_0_1px_var(--c-border-strong)]',
        ]"
        :style="{ width: `${columnWidth}px` }"
      >
        <header class="flex shrink-0 items-center gap-2 px-3 pb-2 pt-3">
          <slot name="column-header" :column="column" :count="lists[column.id]?.length ?? 0">
            <span v-if="column.color" class="size-2 shrink-0 rounded-full" :style="{ background: column.color }" aria-hidden="true" />
            <h3 class="min-w-0 truncate text-sm font-semibold text-fg">{{ column.title }}</h3>
            <span
              :class="[
                'rounded-full px-1.5 py-px text-[11px] font-semibold tabular-nums',
                wipTone(column) === 'over' ? 'bg-danger-soft text-danger' : wipTone(column) === 'at' ? 'bg-warning-soft text-warning' : 'text-muted',
              ]"
              :title="column.wipLimit ? (wipTone(column) === 'over' ? t('common.kanban.overLimit', { n: column.wipLimit }) : t('common.kanban.wip', { n: column.wipLimit })) : undefined"
              >{{ lists[column.id]?.length ?? 0 }}<template v-if="column.wipLimit"> / {{ column.wipLimit }}</template></span
            >
          </slot>
          <span class="flex-1" />
          <slot name="column-actions" :column="column" />
          <button
            v-if="$slots['quick-add'] && !disabled"
            type="button"
            class="pressable grid size-6 place-items-center rounded-[6px] text-subtle hover:bg-highlight hover:text-fg"
            :aria-label="t('common.kanban.add')"
            @click="openAdd(column)"
          >
            <Plus :size="15" />
          </button>
        </header>
        <p v-if="blocked.has(column.id)" class="mx-3 mb-2 rounded-[8px] border border-dashed border-line-strong px-2 py-1.5 text-center text-xs font-medium text-muted">
          {{ t("common.kanban.notAllowed") }}
        </p>

        <VueDraggable
          :model-value="lists[column.id] ?? []"
          :data-column="column.id"
          :clone="keepReference"
          :group="groupFor(column.id)"
          :sort="sortable"
          :disabled="disabled"
          :animation="180"
          :delay="150"
          :delay-on-touch-only="true"
          ghost-class="kanban-ghost"
          chosen-class="kanban-chosen"
          drag-class="kanban-drag"
          :force-fallback="false"
          class="flex min-h-[60px] flex-1 flex-col gap-2 overflow-y-auto overscroll-contain px-2 pb-2"
          @update:model-value="(value: Item[]) => (lists[column.id] = value)"
          @start="onStart"
          @end="onEnd"
        >
          <div
            v-for="item in lists[column.id]"
            :key="keyOf(item)"
            :data-card-key="keyOf(item)"
            tabindex="0"
            :aria-describedby="helpId"
            :aria-pressed="lifted?.key === keyOf(item) || undefined"
            :class="[
              'kanban-card group/card relative cursor-grab rounded-[10px] border border-line bg-surface p-3 text-left shadow-xs outline-offset-2 transition-[border-color,box-shadow,transform] duration-150 hover:border-line-strong active:cursor-grabbing',
              lifted?.key === keyOf(item) && 'z-[1] -rotate-1 scale-[1.02] border-primary shadow-pop',
            ]"
            @keydown="onCardKeydown($event, item)"
          >
            <slot name="card" :item="item" :column="column" :lifted="lifted?.key === keyOf(item)" />
          </div>
        </VueDraggable>

        <p v-if="!(lists[column.id]?.length) && adding !== column.id" class="pointer-events-none -mt-12 mb-6 px-3 text-center text-xs text-subtle">
          <slot name="empty" :column="column">{{ t("common.kanban.empty") }}</slot>
        </p>

        <div v-if="$slots['quick-add'] && !disabled" class="shrink-0 px-2 pb-2">
          <div v-if="adding === column.id" class="rounded-[10px] border border-line bg-surface p-2 shadow-xs">
            <slot name="quick-add" :column="column" :close="() => (adding = null)" />
          </div>
          <button
            v-else
            type="button"
            class="flex h-8 w-full items-center gap-1.5 rounded-[8px] px-2 text-sm font-medium text-muted transition-colors hover:bg-highlight hover:text-fg"
            @click="openAdd(column)"
          >
            <Plus :size="15" />{{ t("common.kanban.add") }}
          </button>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
:deep(.kanban-ghost) {
  border-style: dashed !important;
  border-color: var(--c-primary) !important;
  background: color-mix(in srgb, var(--c-accent-soft) 70%, transparent) !important;
  box-shadow: none !important;
}
:deep(.kanban-ghost > *) {
  opacity: 0;
}
:deep(.kanban-drag) {
  transform: rotate(-2deg);
  box-shadow: var(--sh-pop);
}
</style>
