<script setup lang="ts">
/**
 * One department of the org chart and, hanging from it, its sub-departments. They take as many
 * columns as fit side by side (a line from the trunk runs over each row and drops into every card);
 * where only one fits, on a phone or deep inside a column, they become an indented list with elbow
 * lines. Each sub-department lays out its own children the same way, so the chart never runs wider
 * than the page.
 */
import { useElementSize } from "@vueuse/core";
import { computed, ref } from "vue";

import { columnsFor, type DepartmentNode } from "../departments";
import type { Department } from "../types";
import DepartmentCard from "./DepartmentCard.vue";
import type { DepartmentAction } from "./departmentMenu";

const props = withDefaults(defineProps<{ node: DepartmentNode; selectedId?: number | null; canEdit?: boolean; top?: boolean }>(), {
  selectedId: null,
  canEdit: false,
  top: false,
});
const emit = defineEmits<{ open: [department: Department]; action: [action: DepartmentAction, department: Department] }>();

/** A column's narrowest width and the gap between columns (px, as in the styles below). */
const MIN_COLUMN = 232;
const COLUMN_GAP = 16;

const box = ref<HTMLElement | null>(null);
const { width } = useElementSize(box);
const children = computed(() => props.node.children);
const columns = computed(() => columnsFor(width.value, children.value.length, MIN_COLUMN, COLUMN_GAP));

/** Where a sub-department sits in its row, for the connector lines. */
function place(index: number): Record<string, boolean> {
  const cols = columns.value;
  if (cols === 1) return {};
  const count = children.value.length;
  return {
    "row-end": index % cols === cols - 1 || index === count - 1,
    "row-first": index % cols === 0,
    "last-row": Math.floor(index / cols) === Math.floor((count - 1) / cols),
  };
}
</script>

<template>
  <li class="dept-branch min-w-0" :data-branch="node.department.id">
    <span class="dept-drop" aria-hidden="true" />
    <DepartmentCard
      :department="node.department"
      :has-children="children.length > 0"
      :selected="selectedId === node.department.id"
      :can-edit="canEdit"
      :top="top"
      @open="emit('open', node.department)"
      @action="(action) => emit('action', action, node.department)"
    />
    <ul
      v-if="children.length"
      ref="box"
      :class="['dept-children', columns > 1 ? 'is-rows' : 'is-list']"
      :style="columns > 1 ? { gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` } : undefined"
      :data-columns="columns"
    >
      <DepartmentBranch
        v-for="(child, index) in children"
        :key="child.department.id"
        :node="child"
        :class="place(index)"
        :selected-id="selectedId"
        :can-edit="canEdit"
        @open="(department) => emit('open', department)"
        @action="(action, department) => emit('action', action, department)"
      />
    </ul>
  </li>
</template>

<style scoped>
/*
 * The connectors. --t: the trunk's x under the card above; --indent: how far sub-departments sit
 * in (indent - t = 16px, the column gap, so the first card's bus piece starts on the trunk like the
 * others start in their gap); --s: the drop into a card in a row; --g: the gap between rows and
 * under the card above; --e: where an elbow meets a card (its title row).
 */
.dept-children {
  --t: 20px;
  --indent: 36px;
  --s: 12px;
  --g: 20px;
  --e: 25px;
  --w: 1.5px;
  --line: var(--c-border-strong);
  position: relative;
  padding-left: var(--indent);
  padding-top: var(--g);
}
.dept-children::before {
  content: "";
  position: absolute;
  top: 0;
  left: var(--t);
  width: var(--w);
  background: var(--line);
}

/* One column: an indented list, an elbow into each card, the trunk running on to the last one. */
.is-list {
  display: flex;
  flex-direction: column;
  gap: var(--g);
}
.is-list::before {
  height: calc(var(--g) + var(--e));
}
.is-list > li {
  position: relative;
}
.is-list > li::before {
  content: "";
  position: absolute;
  top: var(--e);
  left: calc(var(--t) - var(--indent));
  width: calc(var(--indent) - var(--t));
  height: var(--w);
  background: var(--line);
}
.is-list > li:not(:last-child)::after {
  content: "";
  position: absolute;
  top: var(--e);
  bottom: calc(-1 * (var(--g) + var(--e)));
  left: calc(var(--t) - var(--indent));
  width: var(--w);
  background: var(--line);
}

/* Columns: each card draws its piece of the row's line (from its gap, or from the trunk for the
   first, up to the middle of the last card) and its drop into the card's middle (the card is at
   most 21rem wide, left-aligned in its column); the first of a row carries the trunk on. */
.is-rows {
  display: grid;
  column-gap: 16px;
  row-gap: var(--g);
}
.is-rows::before {
  height: calc(var(--g) - var(--s));
}
.is-rows > li {
  --mid: min(50%, 10.5rem);
  position: relative;
}
.is-rows > li::before {
  content: "";
  position: absolute;
  top: calc(-1 * var(--s));
  left: calc(var(--t) - var(--indent));
  right: 0;
  height: var(--w);
  background: var(--line);
}
.is-rows > li.row-end::before {
  right: calc(100% - var(--mid) - var(--w) / 2);
}
.dept-drop {
  display: none;
}
.is-rows > li > .dept-drop {
  display: block;
  position: absolute;
  top: calc(-1 * var(--s));
  left: calc(var(--mid) - var(--w) / 2);
  width: var(--w);
  height: var(--s);
  background: var(--line);
}
.is-rows > li.row-first:not(.last-row)::after {
  content: "";
  position: absolute;
  top: calc(-1 * var(--s));
  bottom: calc(-1 * (var(--g) - var(--s)));
  left: calc(var(--t) - var(--indent));
  width: var(--w);
  background: var(--line);
}
</style>
