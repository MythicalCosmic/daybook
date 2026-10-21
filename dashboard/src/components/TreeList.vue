<script setup lang="ts">
/**
 * A tree you can reorganise (knowledge base pages, departments, finance categories): expand and
 * collapse, select, drag a row by its handle above, below or into another (`maxDepth` limits
 * nesting), or use Alt + arrows. It emits `move` ({ id, parentId, index }); apply it with
 * `moveNode(tree, move)` optimistically and save it.
 *
 *   <TreeList v-model:selected="pageId" v-model:expanded="open" :nodes="pages" draggable :max-depth="3" @move="savePage" />
 */
import { ChevronRight, GripVertical } from "@lucide/vue";
import { computed, nextTick, onBeforeUnmount, ref, useId } from "vue";
import { useI18n } from "vue-i18n";

import { dropMove, flattenTree, keyboardMove, locate, zoneAt, type DropZone, type FlatNode, type TreeId, type TreeMove, type TreeNode } from "./tree";

const selected = defineModel<TreeId | null>("selected", { default: null });
const expanded = defineModel<TreeId[]>("expanded", { default: () => [] });

const props = withDefaults(defineProps<{ nodes: TreeNode[]; draggable?: boolean; maxDepth?: number; indent?: number; label?: string }>(), {
  draggable: false,
  maxDepth: Infinity,
  indent: 18,
  label: undefined,
});

const emit = defineEmits<{ move: [move: TreeMove]; select: [node: TreeNode] }>();
defineSlots<{ node?: (props: { node: TreeNode; depth: number }) => unknown; actions?: (props: { node: TreeNode }) => unknown }>();

const { t } = useI18n();
const treeId = useId();
const root = ref<HTMLElement | null>(null);
const expandedSet = computed(() => new Set(expanded.value));
const flat = computed(() => flattenTree(props.nodes, expandedSet.value));
const focusId = ref<TreeId | null>(null);
const announcement = ref("");

const tabStop = computed(() => {
  const ids = flat.value.map((row) => row.node.id);
  if (focusId.value !== null && ids.includes(focusId.value)) return focusId.value;
  if (selected.value !== null && ids.includes(selected.value)) return selected.value;
  return ids[0] ?? null;
});

function toggle(id: TreeId, open?: boolean): void {
  const isOpen = expandedSet.value.has(id);
  const next = open ?? !isOpen;
  if (next === isOpen) return;
  expanded.value = next ? [...expanded.value, id] : expanded.value.filter((item) => item !== id);
}

function choose(row: FlatNode): void {
  selected.value = row.node.id;
  emit("select", row.node);
}

async function focusRow(id: TreeId): Promise<void> {
  focusId.value = id;
  await nextTick();
  root.value?.querySelector<HTMLElement>(`[data-tree-id="${CSS.escape(String(id))}"]`)?.focus();
}

function commit(move: TreeMove | null): void {
  if (!move) return;
  emit("move", move);
  const name = locate(props.nodes, move.id)?.node.label ?? "";
  announcement.value = t("common.tree.moved", { name });
  if (move.parentId !== null) toggle(move.parentId, true);
  void focusRow(move.id);
}

function onKeydown(event: KeyboardEvent, row: FlatNode, position: number): void {
  const id = row.node.id;
  if (event.altKey && props.draggable && !row.node.locked) {
    const action = { ArrowUp: "up", ArrowDown: "down", ArrowRight: "indent", ArrowLeft: "outdent" }[event.key] as "up" | "down" | "indent" | "outdent" | undefined;
    if (action) {
      event.preventDefault();
      commit(keyboardMove(props.nodes, id, action, props.maxDepth));
    }
    return;
  }
  const rows = flat.value;
  switch (event.key) {
    case "ArrowDown":
      event.preventDefault();
      if (rows[position + 1]) void focusRow(rows[position + 1]!.node.id);
      break;
    case "ArrowUp":
      event.preventDefault();
      if (rows[position - 1]) void focusRow(rows[position - 1]!.node.id);
      break;
    case "ArrowRight":
      event.preventDefault();
      if (row.hasChildren && !row.expanded) toggle(id, true);
      else if (row.expanded && rows[position + 1]) void focusRow(rows[position + 1]!.node.id);
      break;
    case "ArrowLeft":
      event.preventDefault();
      if (row.expanded) toggle(id, false);
      else if (row.parentId !== null) void focusRow(row.parentId);
      break;
    case "Home":
      event.preventDefault();
      if (rows[0]) void focusRow(rows[0].node.id);
      break;
    case "End":
      event.preventDefault();
      if (rows.length) void focusRow(rows[rows.length - 1]!.node.id);
      break;
    case "Enter":
    case " ":
      event.preventDefault();
      choose(row);
      break;
  }
}

// Pointer drag.
const drag = ref<{ id: TreeId; started: boolean; x: number; y: number } | null>(null);
const drop = ref<{ overId: TreeId; zone: DropZone; move: TreeMove | null } | null>(null);
let pointerId: number | null = null;

function onHandleDown(event: PointerEvent, row: FlatNode): void {
  if (!props.draggable || row.node.locked || event.button !== 0) return;
  event.preventDefault();
  drag.value = { id: row.node.id, started: false, x: event.clientX, y: event.clientY };
  pointerId = event.pointerId;
  window.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", onPointerUp, { once: true });
  window.addEventListener("pointercancel", cancelDrag, { once: true });
}

function onPointerMove(event: PointerEvent): void {
  if (!drag.value || event.pointerId !== pointerId) return;
  if (!drag.value.started && Math.hypot(event.clientX - drag.value.x, event.clientY - drag.value.y) < 4) return;
  drag.value.started = true;
  const element = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>(`[data-tree="${treeId}"] [data-tree-id]`);
  const row = element ? flat.value.find((item) => String(item.node.id) === element.dataset.treeId) : undefined;
  if (!element || !row) {
    drop.value = null;
    return;
  }
  const rect = element.getBoundingClientRect();
  const zone = zoneAt(event.clientY - rect.top, rect.height, !row.node.locked);
  drop.value = { overId: row.node.id, zone, move: dropMove(props.nodes, drag.value.id, row, zone, props.maxDepth) };
}

function onPointerUp(): void {
  const move = drag.value?.started ? drop.value?.move : null;
  cancelDrag();
  if (move) commit(move);
}

function cancelDrag(): void {
  drag.value = null;
  drop.value = null;
  pointerId = null;
  window.removeEventListener("pointermove", onPointerMove);
  window.removeEventListener("pointerup", onPointerUp);
  window.removeEventListener("pointercancel", cancelDrag);
}
onBeforeUnmount(cancelDrag);
</script>

<template>
  <div ref="root" :data-tree="treeId" class="relative min-w-0 select-none" :class="drag?.started && 'cursor-grabbing'">
    <p class="sr-only" aria-live="polite">{{ announcement }}</p>
    <p :id="`${treeId}-help`" class="sr-only">{{ draggable ? t("common.tree.help") : "" }}</p>
    <ul role="tree" :aria-label="label" :aria-describedby="draggable ? `${treeId}-help` : undefined" class="flex flex-col">
      <li
        v-for="(row, position) in flat"
        :key="row.node.id"
        role="treeitem"
        :data-tree-id="row.node.id"
        :aria-level="row.depth + 1"
        :aria-expanded="row.hasChildren ? row.expanded : undefined"
        :aria-selected="row.node.id === selected"
        :aria-setsize="row.siblings"
        :aria-posinset="row.index + 1"
        :tabindex="row.node.id === tabStop ? 0 : -1"
        :class="[
          'group/row relative flex h-8 cursor-pointer items-center gap-1 rounded-[7px] pr-1.5 text-base outline-offset-[-2px] transition-colors',
          row.node.id === selected ? 'bg-accent-soft font-semibold text-accent-fg' : 'text-fg hover:bg-highlight',
          drag?.started && drag.id === row.node.id && 'opacity-40',
          drop?.overId === row.node.id && drop.zone === 'inside' && (drop.move ? 'bg-accent-soft ring-1 ring-inset ring-primary' : 'ring-1 ring-inset ring-danger/50'),
        ]"
        :style="{ paddingLeft: `${4 + row.depth * indent}px` }"
        @click="choose(row)"
        @focus="focusId = row.node.id"
        @keydown="onKeydown($event, row, position)"
      >
        <span
          v-if="drop?.overId === row.node.id && drop.zone !== 'inside' && drop.move"
          class="pointer-events-none absolute right-1 z-[1] h-0.5 rounded-full bg-primary"
          :class="drop.zone === 'before' ? '-top-px' : '-bottom-px'"
          :style="{ left: `${8 + row.depth * indent}px` }"
          aria-hidden="true"
        >
          <span class="absolute -left-1 -top-[3px] size-2 rounded-full border-2 border-primary bg-surface" />
        </span>
        <!-- On touch screens: always shown (nothing hovers there), wider, and the finger's drag is
             ours (touch-none), not a page scroll that cancels it. -->
        <button
          v-if="draggable && !row.node.locked"
          type="button"
          tabindex="-1"
          class="-ml-0.5 grid h-6 w-4 shrink-0 cursor-grab touch-none place-items-center rounded-[4px] text-subtle opacity-0 transition-opacity hover:text-fg group-hover/row:opacity-100 active:cursor-grabbing pointer-coarse:h-8 pointer-coarse:w-7 pointer-coarse:opacity-100"
          :aria-label="t('common.tree.drag')"
          data-tree-handle
          @pointerdown="onHandleDown($event, row)"
          @click.stop
        >
          <GripVertical :size="13" />
        </button>
        <button
          v-if="row.hasChildren"
          type="button"
          tabindex="-1"
          class="grid size-5 shrink-0 place-items-center rounded-[5px] text-subtle hover:bg-[color-mix(in_srgb,var(--c-text)_8%,transparent)] hover:text-fg"
          :aria-label="row.expanded ? t('common.tree.collapse') : t('common.tree.expand')"
          @click.stop="toggle(row.node.id)"
        >
          <ChevronRight :size="14" :class="['transition-transform duration-150', row.expanded && 'rotate-90']" />
        </button>
        <span v-else class="w-5 shrink-0" />
        <slot name="node" :node="row.node" :depth="row.depth">
          <component :is="row.node.icon" v-if="row.node.icon" :size="15" :class="['shrink-0', row.node.id === selected ? 'text-accent-fg' : 'text-muted']" aria-hidden="true" />
          <span class="min-w-0 flex-1 truncate">{{ row.node.label }}</span>
          <span v-if="row.node.meta" class="shrink-0 truncate text-xs font-normal text-subtle">{{ row.node.meta }}</span>
          <span v-if="row.node.badge !== undefined" class="shrink-0 rounded-full px-1.5 text-[11px] font-semibold tabular-nums text-muted">{{ row.node.badge }}</span>
        </slot>
        <span v-if="$slots.actions" class="flex shrink-0 items-center opacity-0 transition-opacity focus-within:opacity-100 group-hover/row:opacity-100" @click.stop>
          <slot name="actions" :node="row.node" />
        </span>
      </li>
    </ul>
  </div>
</template>
