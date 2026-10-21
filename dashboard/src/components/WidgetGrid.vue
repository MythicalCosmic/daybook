<script setup lang="ts" generic="W extends LayoutWidget">
/**
 * The Overview's widget grid (plan §6.2): four columns on desktop, two on tablets, one on phones;
 * each widget spans 1–4. In `editing` ("Customize") mode widgets can be dragged by their handle (or
 * moved with ← → on the focused handle) and hidden with the eye; the arrangement is
 * `v-model:layout` ({ order, hidden }), which the page saves as the person's SavedView.
 *
 *   <WidgetGrid v-model:layout="layout" :widgets="widgets" :editing="customizing">
 *     <template #widget="{ widget }"><component :is="widget.component" v-bind="widgetProps" /></template>
 *   </WidgetGrid>
 *
 * The drag library loads the first time Customize opens, so the Overview's first paint never pays
 * for it.
 */
import { Eye, EyeOff, GripVertical } from "@lucide/vue";
import type Sortable from "sortablejs";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { arrange, moveWidget, toggleWidget, type LayoutWidget, type WidgetLayout } from "./widgetLayout";

const layout = defineModel<WidgetLayout>("layout", { default: () => ({ order: [], hidden: [] }) });

const props = withDefaults(defineProps<{ widgets: W[]; editing?: boolean; gap?: string }>(), { editing: false, gap: "12px" });

const { t } = useI18n();
const grid = ref<HTMLElement | null>(null);

const arranged = computed(() => arrange(props.widgets, layout.value));
/** Editing shows hidden widgets too (dimmed), so they can be shown again. */
const list = computed(() => (props.editing ? arranged.value : arranged.value.filter((item) => !item.hidden)));

function move(from: number, to: number): void {
  if (from === to) return;
  layout.value = moveWidget(layout.value, props.widgets, from, to);
}

// Drag and drop: Sortable moves the DOM node; it is put back at once and the new order goes into
// `layout`, so Vue stays the only one rendering the list.
let sortable: Sortable | null = null;
let loading: Promise<void> | null = null;

async function enableDrag(): Promise<void> {
  loading ??= import("sortablejs").then(({ default: SortableJs }) => {
    if (!props.editing || !grid.value || sortable) return;
    sortable = SortableJs.create(grid.value, {
      animation: 200,
      handle: "[data-widget-handle]",
      // Pointer events instead of native drag and drop: the same on touch screens, and the
      // dragged card follows the pointer instead of a translucent browser snapshot.
      forceFallback: true,
      fallbackOnBody: true,
      ghostClass: "widget-ghost",
      chosenClass: "widget-chosen",
      onEnd: (event) => {
        const { item, from, oldIndex, newIndex } = event;
        if (oldIndex === undefined || newIndex === undefined || oldIndex === newIndex) return;
        from.removeChild(item);
        from.insertBefore(item, from.children[oldIndex] ?? null);
        move(oldIndex, newIndex);
      },
    });
  });
  try {
    await loading;
  } finally {
    loading = null;
  }
}

function disableDrag(): void {
  sortable?.destroy();
  sortable = null;
}

watch(
  () => props.editing,
  (editing) => (editing ? void enableDrag() : disableDrag()),
  { immediate: true },
);
onBeforeUnmount(disableDrag);

function onHandleKey(event: KeyboardEvent, index: number): void {
  if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
    event.preventDefault();
    move(index, index - 1);
  } else if (event.key === "ArrowRight" || event.key === "ArrowDown") {
    event.preventDefault();
    move(index, index + 1);
  }
}

const spans = { 1: "", 2: "md:col-span-2", 3: "md:col-span-2 lg:col-span-3", 4: "md:col-span-2 lg:col-span-4" } as const;
</script>

<template>
  <div ref="grid" :class="['grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4', editing && 'pt-3']" :style="{ columnGap: gap, rowGap: editing ? `calc(${gap} + 16px)` : gap }">
    <div
      v-for="(widget, index) in list"
      :key="widget.id"
      :data-widget="widget.id"
      :class="[
        // A widget with nothing to show today (Get started once done) leaves no empty cell behind.
        'relative min-w-0 has-[>[data-widget-body]:empty]:hidden',
        spans[widget.span],
        editing && 'rounded-card outline-2 outline-dashed outline-offset-2 outline-line-strong',
        editing && widget.hidden && 'opacity-45',
      ]"
    >
      <div :class="['h-full', editing && 'pointer-events-none select-none']" data-widget-body>
        <slot name="widget" :widget="widget" />
      </div>
      <!-- On the card's top edge, not over its header: "View all" and counts stay readable while customizing. -->
      <div v-if="editing" class="absolute -top-3.5 right-3 z-10 flex items-center gap-0.5 rounded-[9px] border border-line bg-surface p-0.5 shadow-pop">
        <button
          type="button"
          data-widget-handle
          class="grid size-7 cursor-grab place-items-center rounded-[7px] text-muted hover:bg-highlight hover:text-fg active:cursor-grabbing"
          :aria-label="t('common.widget.drag')"
          @keydown="onHandleKey($event, index)"
        >
          <GripVertical :size="15" />
        </button>
        <button
          type="button"
          class="grid size-7 place-items-center rounded-[7px] text-muted hover:bg-highlight hover:text-fg"
          :aria-label="widget.hidden ? t('common.widget.show') : t('common.widget.hide')"
          :aria-pressed="widget.hidden"
          @click="layout = toggleWidget(layout, widget.id)"
        >
          <EyeOff v-if="widget.hidden" :size="15" />
          <Eye v-else :size="15" />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
:deep(.widget-ghost) {
  opacity: 0.35;
}
:deep(.widget-chosen) {
  box-shadow: var(--sh-pop);
  border-radius: var(--r-card);
}
</style>
