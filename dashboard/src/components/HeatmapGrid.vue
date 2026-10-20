<script setup lang="ts">
/**
 * A grid of shaded cells (people × days, hour × weekday, branch × week): darker means more. Hover
 * or focus shows the value; `show-values` prints numbers; cells can be clicked. The scale runs from
 * the surface to `color` (the brand terracotta by default); empty cells are hatched.
 *
 *   <HeatmapGrid :rows="branches" :columns="hours" :value="(row, col) => sales[row.key]?.[col.key] ?? null" :format="fmt.money" />
 */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { useFormat } from "@/lib/useFormat";

export interface HeatmapAxis {
  key: string;
  label: string;
  /** Shorter label for narrow columns. */
  short?: string;
  sublabel?: string;
}

const props = withDefaults(
  defineProps<{
    rows: HeatmapAxis[];
    columns: HeatmapAxis[];
    value: (row: HeatmapAxis, column: HeatmapAxis) => number | null | undefined;
    format?: (value: number) => string;
    /** Short text inside cells with `show-values` (default `format`). */
    cellFormat?: (value: number) => string;
    color?: string;
    max?: number;
    min?: number;
    showValues?: boolean;
    cellSize?: number;
    clickable?: boolean;
    legend?: boolean;
    rowLabelWidth?: number;
    label?: string;
  }>(),
  {
    format: undefined,
    cellFormat: undefined,
    color: "var(--c-primary)",
    max: undefined,
    min: undefined,
    showValues: false,
    cellSize: 30,
    clickable: false,
    legend: true,
    rowLabelWidth: 140,
    label: undefined,
  },
);

const emit = defineEmits<{ "cell-click": [cell: { row: HeatmapAxis; column: HeatmapAxis; value: number | null }] }>();

const { t } = useI18n();
const fmt = useFormat();

const matrix = computed(() => props.rows.map((row) => props.columns.map((column) => props.value(row, column) ?? null)));
const values = computed(() => matrix.value.flat().filter((v): v is number => v !== null && Number.isFinite(v)));
const high = computed(() => props.max ?? Math.max(0, ...values.value));
const low = computed(() => props.min ?? Math.min(0, ...values.value));

function shade(value: number | null): string | undefined {
  if (value === null) return undefined;
  const span = high.value - low.value || 1;
  const ratio = Math.min(1, Math.max(0, (value - low.value) / span));
  const strength = value === 0 ? 0 : Math.round(10 + ratio * 82);
  return `color-mix(in srgb, ${props.color} ${strength}%, var(--c-surface-2))`;
}

function text(value: number | null): string {
  if (value === null) return "—";
  return props.format ? props.format(value) : fmt.number(value, 1);
}

const hover = ref<{ row: number; column: number; x: number; y: number } | null>(null);
const host = ref<HTMLElement | null>(null);

function show(event: Event, row: number, column: number): void {
  const cell = event.currentTarget as HTMLElement;
  const box = host.value?.getBoundingClientRect();
  const rect = cell.getBoundingClientRect();
  if (!box) return;
  hover.value = { row, column, x: rect.left - box.left + rect.width / 2, y: rect.top - box.top };
}

const legendSteps = [0, 0.25, 0.5, 0.75, 1];
const dark = (value: number | null) => value !== null && high.value - low.value > 0 && (value - low.value) / (high.value - low.value) > 0.6;
</script>

<template>
  <div ref="host" class="relative min-w-0">
    <div class="overflow-x-auto">
      <table class="border-separate border-spacing-[3px]" :aria-label="label">
        <thead>
          <tr>
            <th :style="{ width: `${rowLabelWidth}px`, minWidth: `${rowLabelWidth}px` }" />
            <th
              v-for="column in columns"
              :key="column.key"
              scope="col"
              class="px-0 pb-1 text-center align-bottom text-[10px] font-semibold text-muted"
              :style="{ minWidth: `${cellSize}px` }"
              :title="column.label"
            >
              {{ column.short ?? column.label }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, r) in rows" :key="row.key">
            <th scope="row" class="max-w-0 pr-2 text-left font-normal">
              <span class="block truncate text-xs font-medium text-fg">{{ row.label }}</span>
              <span v-if="row.sublabel" class="block truncate text-[10px] text-subtle">{{ row.sublabel }}</span>
            </th>
            <td v-for="(column, c) in columns" :key="column.key" class="p-0">
              <component
                :is="clickable ? 'button' : 'div'"
                :type="clickable ? 'button' : undefined"
                :tabindex="clickable ? undefined : 0"
                :aria-label="`${row.label}, ${column.label}: ${text(matrix[r]![c]!)}`"
                :class="[
                  'heat-cell grid place-items-center overflow-hidden whitespace-nowrap rounded-[5px] text-[10px] font-semibold tabular-nums outline-offset-1 transition-transform duration-100 hover:scale-110 focus-visible:scale-110',
                  matrix[r]![c] === null && 'heat-empty',
                  clickable && 'cursor-pointer',
                  dark(matrix[r]![c]!) ? 'text-white dark:text-[#1e130b]' : 'text-fg/70',
                ]"
                :style="{ width: `${cellSize}px`, height: `${Math.round(cellSize * 0.86)}px`, background: shade(matrix[r]![c]!) }"
                @mouseenter="show($event, r, c)"
                @focus="show($event, r, c)"
                @mouseleave="hover = null"
                @blur="hover = null"
                @click="clickable && emit('cell-click', { row, column, value: matrix[r]![c]! })"
              >
                <template v-if="showValues && matrix[r]![c] !== null">{{ cellFormat ? cellFormat(matrix[r]![c]!) : text(matrix[r]![c]!) }}</template>
              </component>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="legend && values.length" class="mt-2 flex items-center justify-end gap-1.5 text-[11px] text-muted" aria-hidden="true">
      {{ t("common.heatmap.less") }}
      <span
        v-for="step in legendSteps"
        :key="step"
        class="size-3 rounded-[3px]"
        :style="{ background: step === 0 ? 'var(--c-surface-2)' : `color-mix(in srgb, ${color} ${Math.round(10 + step * 82)}%, var(--c-surface-2))` }"
      />
      {{ t("common.heatmap.more") }}
    </div>
    <div
      v-if="hover"
      class="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-[7px] bg-[#201e1d] px-2 py-1 text-xs text-[#f7f3ec] shadow-pop dark:bg-surface-3 dark:text-fg"
      :style="{ left: `${hover.x}px`, top: `${hover.y - 6}px` }"
      role="tooltip"
    >
      <span class="text-[#f7f3ec]/70 dark:text-muted">{{ rows[hover.row]?.label }} · {{ columns[hover.column]?.label }}</span>
      <span class="ml-1.5 font-semibold tabular-nums">{{ text(matrix[hover.row]![hover.column]!) }}</span>
    </div>
  </div>
</template>

<style scoped>
.heat-empty {
  background-image: repeating-linear-gradient(135deg, var(--c-border) 0 1px, transparent 1px 5px);
  background-color: transparent;
}
</style>
