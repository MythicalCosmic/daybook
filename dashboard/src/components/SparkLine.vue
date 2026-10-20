<script setup lang="ts">
/**
 * A tiny trend line for KPI tiles, table cells and cards: plain SVG (no ECharts, so it costs
 * nothing on the Overview), a soft wash, the last point marked. Values may be decimal strings.
 *
 *   <SparkLine :data="last30" color="var(--c-chart-3)" />
 */
import { computed, useId } from "vue";

import { toNumber } from "./chartCard";

const props = withDefaults(
  defineProps<{ data: Array<number | string | null>; color?: string; width?: number; height?: number; area?: boolean; dot?: boolean; label?: string; fluid?: boolean }>(),
  { color: "var(--c-chart-1)", width: 120, height: 32, area: true, dot: true, label: undefined, fluid: false },
);

const gradientId = useId();
const PAD = 3;

const points = computed(() => {
  const values = props.data.map(toNumber);
  const present = values.filter((v): v is number => v !== null);
  if (present.length < 2) return [];
  const min = Math.min(...present);
  const max = Math.max(...present);
  const span = max - min || 1;
  const step = (props.width - PAD * 2) / Math.max(1, values.length - 1);
  return values.map((v, i) =>
    v === null ? null : { x: PAD + i * step, y: props.height - PAD - ((v - min) / span) * (props.height - PAD * 2) },
  );
});

const line = computed(() => {
  let path = "";
  let pen = false;
  for (const point of points.value) {
    if (!point) {
      pen = false;
      continue;
    }
    path += `${pen ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)} `;
    pen = true;
  }
  return path.trim();
});

const fill = computed(() => {
  const present = points.value.filter((p): p is { x: number; y: number } => !!p);
  if (present.length < 2) return "";
  const first = present[0]!;
  const last = present[present.length - 1]!;
  return `${line.value} L${last.x.toFixed(1)},${props.height} L${first.x.toFixed(1)},${props.height} Z`;
});

const last = computed(() => [...points.value].reverse().find((p): p is { x: number; y: number } => !!p) ?? null);
</script>

<template>
  <svg
    :viewBox="`0 0 ${width} ${height}`"
    :width="width"
    :height="height"
    class="block max-w-full overflow-visible"
    :style="fluid ? { width: '100%' } : undefined"
    :role="label ? 'img' : undefined"
    :aria-label="label"
    :aria-hidden="label ? undefined : 'true'"
    preserveAspectRatio="none"
  >
    <defs>
      <linearGradient :id="gradientId" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" :stop-color="color" stop-opacity="0.22" />
        <stop offset="100%" :stop-color="color" stop-opacity="0" />
      </linearGradient>
    </defs>
    <path v-if="area && fill" :d="fill" :fill="`url(#${gradientId})`" />
    <path v-if="line" :d="line" fill="none" :stroke="color" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke" />
    <circle v-if="dot && last" :cx="last.x" :cy="last.y" r="2.75" :fill="color" stroke="var(--c-surface)" stroke-width="1.5" />
  </svg>
</template>
