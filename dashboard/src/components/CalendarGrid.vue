<script setup lang="ts">
/**
 * One month of days for DatePicker and DateRangePicker: Monday first, today marked, a selected day
 * or a range (with its ends), an optional compare range underlined, days outside min/max disabled.
 * Keyboard: arrows move a day/week, PageUp/PageDown a month (Shift: a year), Home/End the week,
 * Enter/Space picks. The focused day is the grid's single tab stop.
 */
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import type { Range } from "@/api/types";
import { formatDay } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";

import { inRange, keyTarget, monthGrid, monthOf, type Month } from "./calendar";

const props = withDefaults(
  defineProps<{
    month: Month;
    today: string;
    selected?: string | null;
    range?: Range | null;
    compare?: Range | null;
    min?: string | null;
    max?: string | null;
    disabledDays?: (day: string) => boolean;
    focusDay?: string | null;
    /** Leave days of other months blank (two months side by side). */
    hideOutside?: boolean;
  }>(),
  { selected: null, range: null, compare: null, min: null, max: null, disabledDays: undefined, focusDay: null, hideOutside: false },
);

const emit = defineEmits<{ select: [day: string]; hover: [day: string | null]; "update:focusDay": [day: string]; navigate: [month: Month] }>();

const { t } = useI18n();
const fmt = useFormat();
const root = ref<HTMLElement | null>(null);

const weeks = computed(() => monthGrid(props.month));
const focusTarget = computed(() => {
  if (props.focusDay && monthOf(props.focusDay) === props.month) return props.focusDay;
  if (props.selected && monthOf(props.selected) === props.month) return props.selected;
  if (monthOf(props.today) === props.month) return props.today;
  return `${props.month}-01`;
});

function disabled(day: string): boolean {
  return (!!props.min && day < props.min) || (!!props.max && day > props.max) || !!props.disabledDays?.(day);
}

function cellState(day: string) {
  const outside = monthOf(day) !== props.month;
  const range = props.range;
  const isStart = !!range && day === range.from;
  const isEnd = !!range && day === range.to;
  const inside = inRange(day, range);
  return {
    outside,
    selected: day === props.selected || isStart || isEnd,
    middle: inside && !isStart && !isEnd,
    isStart,
    isEnd,
    single: !!range && range.from === range.to,
    compared: inRange(day, props.compare),
    today: day === props.today,
    disabled: disabled(day),
  };
}

function onKeydown(event: KeyboardEvent, day: string): void {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    if (!disabled(day)) emit("select", day);
    return;
  }
  const target = keyTarget(day, event.key, event.shiftKey);
  if (!target) return;
  event.preventDefault();
  emit("update:focusDay", target);
  if (monthOf(target) !== props.month) emit("navigate", monthOf(target));
}

// Keep DOM focus on the focused day when it changes by keyboard.
watch(
  () => props.focusDay,
  async (day) => {
    if (!day || !root.value?.contains(document.activeElement)) return;
    await nextTick();
    root.value?.querySelector<HTMLElement>(`[data-day="${day}"]`)?.focus();
  },
);

defineExpose({ focus: () => root.value?.querySelector<HTMLElement>(`[data-day="${focusTarget.value}"]`)?.focus() });
</script>

<template>
  <div ref="root" role="grid" :aria-label="formatDay(`${month}-01`, fmt.lang.value, 'monthYear')" class="select-none" @mouseleave="emit('hover', null)">
    <div role="row" class="mb-1 grid grid-cols-7">
      <span v-for="n in 7" :key="n" role="columnheader" class="grid h-7 place-items-center text-[11px] font-semibold uppercase tracking-wide text-subtle">
        {{ t(`common.weekday.min.${n - 1}`) }}
      </span>
    </div>
    <div v-for="(week, w) in weeks" :key="w" role="row" class="grid grid-cols-7">
      <template v-for="day in week" :key="day">
        <span v-if="hideOutside && cellState(day).outside" role="gridcell" class="h-9" />
        <span
          v-else
          role="gridcell"
          :aria-selected="cellState(day).selected || cellState(day).middle"
          :class="[
            'relative h-9',
            cellState(day).middle && 'bg-accent-soft',
            cellState(day).isStart && !cellState(day).single && 'rounded-l-[8px] bg-accent-soft',
            cellState(day).isEnd && !cellState(day).single && 'rounded-r-[8px] bg-accent-soft',
          ]"
        >
          <button
            type="button"
            :data-day="day"
            :tabindex="day === focusTarget ? 0 : -1"
            :disabled="cellState(day).disabled"
            :aria-label="formatDay(day, fmt.lang.value, 'long')"
            :aria-current="cellState(day).today ? 'date' : undefined"
            :class="[
              'relative grid size-9 place-items-center rounded-[8px] text-sm tabular-nums outline-offset-0 transition-colors duration-100',
              cellState(day).selected
                ? 'bg-primary font-semibold text-on-primary'
                : cellState(day).middle
                  ? 'font-medium text-accent-fg hover:bg-[color-mix(in_srgb,var(--c-primary)_14%,transparent)]'
                  : cellState(day).outside
                    ? 'text-subtle/70 hover:bg-highlight'
                    : 'text-fg hover:bg-highlight',
              cellState(day).today && !cellState(day).selected && 'font-semibold text-primary',
              cellState(day).disabled && 'pointer-events-none opacity-30',
            ]"
            @click="emit('select', day)"
            @mouseenter="emit('hover', day)"
            @focus="emit('update:focusDay', day)"
            @keydown="onKeydown($event, day)"
          >
            {{ Number(day.slice(8)) }}
            <span
              v-if="cellState(day).today"
              :class="['absolute bottom-1 size-1 rounded-full', cellState(day).selected ? 'bg-on-primary' : 'bg-primary']"
              aria-hidden="true"
            />
            <span
              v-if="cellState(day).compared"
              class="absolute inset-x-2 bottom-0.5 h-0.5 rounded-full bg-[var(--c-chart-3)] opacity-70"
              aria-hidden="true"
            />
          </button>
        </span>
      </template>
    </div>
  </div>
</template>
