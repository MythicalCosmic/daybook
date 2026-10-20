<script setup lang="ts">
/**
 * A timeline of rows with bars and milestone diamonds (Projects "Timeline", the Roadmap, time-off
 * plans): day, week or month zoom, weekends shaded, a today line, labels that stay put while you
 * scroll. Drag a bar to move it, its edges to change the start or end, a diamond to move a
 * milestone; the component emits `change` / `milestone-change` and the page saves. Keyboard:
 * ← → move the focused bar a day, Shift + ← → change its end, Enter opens it.
 *
 *   <GanttTimeline v-model:zoom="zoom" :rows="rows" @change="({ rowId, barId, start, end }) => reschedule(barId, start, end)" />
 */
import { CalendarClock } from "@lucide/vue";
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { diffDays, formatDay, todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { isWeekend } from "./calendar";
import { barBox, dayCenter, dragDates, dragModeAt, isoWeek, pxToDays, PX_PER_DAY, ticks, timelineRange, type DragMode, type GanttBar, type GanttMilestone, type GanttRow, type GanttZoom } from "./gantt";
import SegmentedControl from "./SegmentedControl.vue";
import UiButton from "./UiButton.vue";
import UserAvatar from "./UserAvatar.vue";

const zoom = defineModel<GanttZoom>("zoom", { default: "week" });

const props = withDefaults(
  defineProps<{
    rows: GanttRow[];
    editable?: boolean;
    rowHeight?: number;
    labelWidth?: number;
    maxHeight?: string;
    label?: string;
  }>(),
  { editable: true, rowHeight: 44, labelWidth: 232, maxHeight: "min(calc(100dvh - 260px), 720px)", label: undefined },
);

const emit = defineEmits<{
  change: [change: { rowId: GanttRow["id"]; barId: GanttBar["id"]; start: string; end: string; mode: DragMode }];
  "milestone-change": [change: { rowId: GanttRow["id"]; milestoneId: GanttMilestone["id"]; date: string }];
  "bar-click": [target: { row: GanttRow; bar: GanttBar }];
  "row-click": [row: GanttRow];
}>();

defineSlots<{ label?: (props: { row: GanttRow }) => unknown }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const scroller = ref<HTMLElement | null>(null);

const today = computed(() => todayIn(company.timezone));
const range = computed(() => timelineRange(props.rows, today.value, zoom.value));
const ppd = computed(() => PX_PER_DAY[zoom.value]);
const width = computed(() => (diffDays(range.value.from, range.value.to) + 1) * ppd.value);
const header = computed(() => ticks(range.value, zoom.value));
const weekends = computed(() => {
  if (zoom.value !== "day") return [];
  const out: number[] = [];
  for (let i = 0; i <= diffDays(range.value.from, range.value.to); i++) {
    const day = new Date(`${range.value.from}T00:00:00Z`);
    day.setUTCDate(day.getUTCDate() + i);
    if (isWeekend(day.toISOString().slice(0, 10))) out.push(i * ppd.value);
  }
  return out;
});

const zoomOptions = computed(() => [
  { value: "day" as GanttZoom, label: t("common.gantt.day") },
  { value: "week" as GanttZoom, label: t("common.gantt.week") },
  { value: "month" as GanttZoom, label: t("common.gantt.month") },
]);

function topLabel(day: string): string {
  return zoom.value === "month" ? day.slice(0, 4) : formatDay(day, fmt.lang.value, "monthYear");
}

function bottomLabel(day: string): string {
  if (zoom.value === "day") return String(Number(day.slice(8)));
  if (zoom.value === "week") return `${formatDay(day, fmt.lang.value, "short")}`;
  return formatDay(day, fmt.lang.value, "monthYear").split(/[ ,]/)[0]!;
}

// Dragging bars and milestones.
interface DragState {
  kind: "bar" | "milestone";
  rowId: GanttRow["id"];
  id: GanttBar["id"];
  start: string;
  end: string;
  mode: DragMode;
  x: number;
  delta: number;
  moved: boolean;
}
const drag = ref<DragState | null>(null);

function preview(row: GanttRow, bar: GanttBar): { start: string; end: string } {
  const state = drag.value;
  if (state?.kind === "bar" && state.rowId === row.id && state.id === bar.id) return dragDates(state, state.mode, state.delta);
  return bar;
}

function previewDate(row: GanttRow, milestone: GanttMilestone): string {
  const state = drag.value;
  if (state?.kind === "milestone" && state.rowId === row.id && state.id === milestone.id) return dragDates({ start: state.start, end: state.start }, "move", state.delta).start;
  return milestone.date;
}

function canEdit(item: { editable?: boolean }): boolean {
  return props.editable && item.editable !== false;
}

function onBarDown(event: PointerEvent, row: GanttRow, bar: GanttBar): void {
  if (event.button !== 0) return;
  const target = event.currentTarget as HTMLElement;
  const rect = target.getBoundingClientRect();
  const mode = canEdit(bar) ? dragModeAt(event.clientX - rect.left, rect.width) : "move";
  drag.value = { kind: "bar", rowId: row.id, id: bar.id, start: bar.start, end: bar.end, mode, x: event.clientX, delta: 0, moved: false };
  target.setPointerCapture(event.pointerId);
}

function onMilestoneDown(event: PointerEvent, row: GanttRow, milestone: GanttMilestone): void {
  if (event.button !== 0) return;
  drag.value = { kind: "milestone", rowId: row.id, id: milestone.id, start: milestone.date, end: milestone.date, mode: "move", x: event.clientX, delta: 0, moved: false };
  (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
}

function onPointerMove(event: PointerEvent, item: { editable?: boolean }): void {
  const state = drag.value;
  if (!state) return;
  if (Math.abs(event.clientX - state.x) > 3) state.moved = true;
  if (canEdit(item)) state.delta = pxToDays(event.clientX - state.x, zoom.value);
}

function onBarUp(row: GanttRow, bar: GanttBar): void {
  const state = drag.value;
  drag.value = null;
  if (!state) return;
  if (!state.moved) {
    emit("bar-click", { row, bar });
    return;
  }
  if (state.delta === 0) return;
  emit("change", { rowId: row.id, barId: bar.id, ...dragDates(state, state.mode, state.delta), mode: state.mode });
}

function onMilestoneUp(row: GanttRow, milestone: GanttMilestone): void {
  const state = drag.value;
  drag.value = null;
  if (!state || state.delta === 0) return;
  emit("milestone-change", { rowId: row.id, milestoneId: milestone.id, date: dragDates({ start: milestone.date, end: milestone.date }, "move", state.delta).start });
}

function onBarKey(event: KeyboardEvent, row: GanttRow, bar: GanttBar): void {
  if (event.key === "Enter") {
    event.preventDefault();
    emit("bar-click", { row, bar });
    return;
  }
  if (!canEdit(bar) || (event.key !== "ArrowLeft" && event.key !== "ArrowRight")) return;
  event.preventDefault();
  const delta = event.key === "ArrowLeft" ? -1 : 1;
  const mode: DragMode = event.shiftKey ? "end" : "move";
  emit("change", { rowId: row.id, barId: bar.id, ...dragDates(bar, mode, delta), mode });
}

function rangeText(dates: { start: string; end: string }): string {
  const days = diffDays(dates.start, dates.end) + 1;
  return `${formatDay(dates.start, fmt.lang.value, "short")} – ${formatDay(dates.end, fmt.lang.value, "short")} · ${t("common.gantt.days", { n: days })}`;
}

function barColor(row: GanttRow, bar: GanttBar): string {
  return bar.color ?? row.color ?? "var(--c-primary)";
}

async function scrollToToday(smooth = true): Promise<void> {
  await nextTick();
  const el = scroller.value;
  if (!el) return;
  const x = dayCenter(today.value, range.value.from, zoom.value);
  const left = Math.max(0, x - (el.clientWidth - props.labelWidth) / 3);
  if (typeof el.scrollTo === "function") el.scrollTo({ left, behavior: smooth ? "smooth" : "auto" });
  else el.scrollLeft = left;
}

onMounted(() => void scrollToToday(false));
watch(zoom, () => void scrollToToday(false));
</script>

<template>
  <div class="flex min-w-0 flex-col gap-3">
    <div class="flex flex-wrap items-center gap-2">
      <SegmentedControl v-model="zoom" :options="zoomOptions" size="sm" :aria-label="t('common.gantt.zoom')" />
      <UiButton size="sm" variant="ghost" :icon="CalendarClock" @click="scrollToToday()">{{ t("common.today") }}</UiButton>
      <p class="sr-only">{{ t("common.gantt.help") }}</p>
    </div>

    <div class="ui-card relative overflow-hidden">
      <div ref="scroller" class="overflow-auto overscroll-contain" :style="{ maxHeight }">
        <div class="relative" :style="{ width: `${labelWidth + width}px` }">
          <!-- Header -->
          <div class="sticky top-0 z-[4] flex border-b border-line bg-surface">
            <div class="sticky left-0 z-[5] flex shrink-0 items-end border-r border-line bg-surface px-3 pb-2 text-xs font-semibold text-muted" :style="{ width: `${labelWidth}px` }">
              {{ label ?? t("common.gantt.rows") }}
            </div>
            <div class="relative h-14 shrink-0" :style="{ width: `${width}px` }">
              <div
                v-for="tick in header.top"
                :key="`t${tick.day}`"
                class="absolute top-0 flex h-7 items-center overflow-hidden border-l border-line px-2 text-xs font-semibold text-fg first:border-l-0"
                :style="{ left: `${tick.left}px`, width: `${tick.width}px` }"
              >
                <span class="sticky left-2 truncate">{{ topLabel(tick.day) }}</span>
              </div>
              <div
                v-for="tick in header.bottom"
                :key="`b${tick.day}`"
                :class="[
                  'absolute bottom-0 flex h-7 items-center justify-center overflow-hidden border-l border-t border-line text-[11px] tabular-nums',
                  tick.day === today ? 'font-bold text-primary' : 'text-muted',
                  zoom === 'day' && isWeekend(tick.day) && 'bg-surface-2/50',
                ]"
                :style="{ left: `${tick.left}px`, width: `${tick.width}px` }"
                :title="zoom === 'week' ? `W${isoWeek(tick.day)}` : undefined"
              >
                {{ bottomLabel(tick.day) }}
              </div>
            </div>
          </div>

          <!-- Body -->
          <div class="relative">
            <div class="pointer-events-none absolute inset-y-0" :style="{ left: `${labelWidth}px`, width: `${width}px` }" aria-hidden="true">
              <div v-for="x in weekends" :key="`w${x}`" class="absolute inset-y-0 bg-surface-2/45 dark:bg-surface-2/60" :style="{ left: `${x}px`, width: `${ppd}px` }" />
              <div v-for="tick in header.bottom" :key="`l${tick.day}`" class="absolute inset-y-0 w-px bg-line/70" :style="{ left: `${tick.left}px` }" />
              <div class="absolute inset-y-0 z-[2] w-0.5 bg-danger/80" :style="{ left: `${dayCenter(today, range.from, zoom) - 1}px` }">
                <span class="absolute -left-[3px] -top-1 size-2 rounded-full bg-danger" />
              </div>
            </div>

            <div v-for="row in rows" :key="row.id" class="group/row flex border-b border-line last:border-b-0" :style="{ height: `${rowHeight}px` }">
              <button
                type="button"
                class="sticky left-0 z-[3] flex shrink-0 items-center gap-2.5 border-r border-line bg-surface px-3 text-left transition-colors hover:bg-surface-2"
                :style="{ width: `${labelWidth}px` }"
                @click="emit('row-click', row)"
              >
                <slot name="label" :row="row">
                  <UserAvatar v-if="row.avatar" :name="row.avatar.name" :src="row.avatar.src" :size="24" />
                  <span v-else-if="row.color" class="size-2.5 shrink-0 rounded-[3px]" :style="{ background: row.color }" />
                  <span class="min-w-0 leading-tight">
                    <span class="block truncate text-sm font-semibold text-fg">{{ row.label }}</span>
                    <span v-if="row.sublabel" class="block truncate text-xs text-muted">{{ row.sublabel }}</span>
                  </span>
                </slot>
              </button>
              <div class="relative shrink-0 transition-colors group-hover/row:bg-highlight/40" :style="{ width: `${width}px` }">
                <div
                  v-for="bar in row.bars"
                  :key="bar.id"
                  role="button"
                  tabindex="0"
                  :aria-label="`${bar.label ?? row.label}: ${rangeText(preview(row, bar))}`"
                  :class="[
                    'gantt-bar group/bar absolute top-1/2 flex h-7 -translate-y-1/2 touch-none select-none items-center overflow-visible rounded-[7px] outline-offset-2',
                    canEdit(bar) ? 'cursor-grab active:cursor-grabbing' : 'cursor-pointer',
                    drag?.kind === 'bar' && drag.id === bar.id && 'z-[3] shadow-pop',
                  ]"
                  :style="{
                    left: `${barBox(preview(row, bar), range.from, zoom).left + 1}px`,
                    width: `${Math.max(6, barBox(preview(row, bar), range.from, zoom).width - 2)}px`,
                    background: `color-mix(in srgb, ${barColor(row, bar)} 22%, var(--c-surface))`,
                    boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${barColor(row, bar)} 45%, transparent)`,
                  }"
                  @pointerdown="onBarDown($event, row, bar)"
                  @pointermove="onPointerMove($event, bar)"
                  @pointerup="onBarUp(row, bar)"
                  @pointercancel="drag = null"
                  @keydown="onBarKey($event, row, bar)"
                >
                  <span
                    v-if="bar.progress"
                    class="absolute inset-y-0 left-0 rounded-l-[7px]"
                    :class="bar.progress >= 100 && 'rounded-r-[7px]'"
                    :style="{ width: `${Math.min(100, bar.progress)}%`, background: `color-mix(in srgb, ${barColor(row, bar)} 55%, var(--c-surface))` }"
                  />
                  <span
                    :class="[
                      'text-xs font-semibold',
                      barBox(preview(row, bar), range.from, zoom).width < 64 ? 'absolute left-full ml-1.5 whitespace-nowrap text-muted' : 'relative truncate px-2 text-fg',
                    ]"
                    >{{ bar.label ?? row.label }}</span
                  >
                  <template v-if="canEdit(bar)">
                    <span class="absolute inset-y-1 left-0.5 w-1 rounded-full bg-fg/25 opacity-0 transition-opacity group-hover/bar:opacity-100" aria-hidden="true" />
                    <span class="absolute inset-y-1 right-0.5 w-1 rounded-full bg-fg/25 opacity-0 transition-opacity group-hover/bar:opacity-100" aria-hidden="true" />
                  </template>
                  <span
                    v-if="drag?.kind === 'bar' && drag.id === bar.id && drag.moved"
                    class="pointer-events-none absolute -top-8 left-0 z-[4] whitespace-nowrap rounded-[6px] bg-[#201e1d] px-2 py-1 text-[11px] font-semibold tabular-nums text-[#f7f3ec] shadow-pop dark:bg-surface-3 dark:text-fg"
                    >{{ rangeText(preview(row, bar)) }}</span
                  >
                </div>
                <div
                  v-for="milestone in row.milestones ?? []"
                  :key="`m${milestone.id}`"
                  role="button"
                  tabindex="0"
                  :aria-label="`${t('common.gantt.milestone')}: ${milestone.label}, ${formatDay(previewDate(row, milestone), fmt.lang.value, 'medium')}`"
                  class="absolute top-1/2 z-[2] flex -translate-y-1/2 touch-none select-none items-center gap-1.5 outline-offset-2"
                  :class="canEdit(milestone) ? 'cursor-grab active:cursor-grabbing' : ''"
                  :style="{ left: `${dayCenter(previewDate(row, milestone), range.from, zoom) - 7}px` }"
                  @pointerdown="onMilestoneDown($event, row, milestone)"
                  @pointermove="onPointerMove($event, milestone)"
                  @pointerup="onMilestoneUp(row, milestone)"
                  @pointercancel="drag = null"
                >
                  <span
                    class="size-3.5 rotate-45 rounded-[3px] border-2 shadow-xs"
                    :style="{
                      borderColor: milestone.color ?? 'var(--c-text)',
                      background: milestone.done ? (milestone.color ?? 'var(--c-text)') : 'var(--c-surface)',
                    }"
                  />
                  <span class="whitespace-nowrap rounded-[5px] bg-surface/90 px-1 text-[11px] font-semibold text-fg backdrop-blur-sm">{{ milestone.label }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
