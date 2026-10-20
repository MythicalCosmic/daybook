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
 */
import { Eye, EyeOff, GripVertical } from "@lucide/vue";
import { useDraggable } from "vue-draggable-plus";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { arrange, moveWidget, toggleWidget, type LayoutWidget, type WidgetLayout } from "./widgetLayout";

const layout = defineModel<WidgetLayout>("layout", { default: () => ({ order: [], hidden: [] }) });

const props = withDefaults(defineProps<{ widgets: W[]; editing?: boolean; gap?: string }>(), { editing: false, gap: "12px" });

const { t } = useI18n();
const grid = ref<HTMLElement | null>(null);

const arranged = computed(() => arrange(props.widgets, layout.value));
const list = ref<Array<W & { hidden: boolean }>>([]);
watch(
  [arranged, () => props.editing],
  ([items, editing]) => {
    list.value = editing ? [...items] : items.filter((item) => !item.hidden);
  },
  { immediate: true },
);

const draggable = useDraggable(grid, list, {
  animation: 200,
  handle: "[data-widget-handle]",
  ghostClass: "widget-ghost",
  chosenClass: "widget-chosen",
  disabled: !props.editing,
  onEnd: () => {
    layout.value = { ...layout.value, order: list.value.map((item) => item.id) };
  },
});
watch(
  () => props.editing,
  (editing) => draggable.option("disabled", !editing),
);

function nudge(index: number, step: -1 | 1): void {
  layout.value = moveWidget(layout.value, props.widgets, index, index + step);
}

function onHandleKey(event: KeyboardEvent, index: number): void {
  if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
    event.preventDefault();
    nudge(index, -1);
  } else if (event.key === "ArrowRight" || event.key === "ArrowDown") {
    event.preventDefault();
    nudge(index, 1);
  }
}

const spans = { 1: "", 2: "md:col-span-2", 3: "md:col-span-2 lg:col-span-3", 4: "md:col-span-2 lg:col-span-4" } as const;
</script>

<template>
  <div ref="grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4" :style="{ gap }">
    <div
      v-for="(widget, index) in list"
      :key="widget.id"
      :data-widget="widget.id"
      :class="[
        'relative min-w-0',
        spans[widget.span],
        editing && 'rounded-card outline-2 outline-dashed outline-offset-2 outline-line-strong',
        editing && widget.hidden && 'opacity-45',
      ]"
    >
      <div :class="editing && 'pointer-events-none select-none'">
        <slot name="widget" :widget="widget" />
      </div>
      <div v-if="editing" class="absolute right-2 top-2 z-10 flex items-center gap-0.5 rounded-[9px] border border-line bg-surface/95 p-0.5 shadow-pop backdrop-blur">
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
