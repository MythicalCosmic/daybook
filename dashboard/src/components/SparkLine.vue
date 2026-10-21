<script setup lang="ts">
/**
 * A tiny trend line for KPI tiles, table cells and cards: plain SVG (no ECharts, so it costs
 * nothing on the Overview), a soft wash, the last point marked. Values may be decimal strings.
 *
 * A missing value (a day with nothing due) is stepped over: the line joins the days on either side,
 * where a gap would leave a stray dash and a wash cut at an angle that read as a broken chart.
 * `fluid` stretches the line to the width of its box (and to its height, given a height class);
 * the last point stays round however it is stretched.
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

/** The values that are there, each at its own day's place (a missing day keeps its slot). */
const points = computed(() => {
  const values = props.data.map(toNumber);
  const present = values.filter((v): v is number => v !== null);
  if (present.length < 2) return [];
  const min = Math.min(...present);
  const max = Math.max(...present);
  const span = max - min || 1;
  const step = (props.width - PAD * 2) / Math.max(1, values.length - 1);
  return values.flatMap((v, i) => (v === null ? [] : [{ x: PAD + i * step, y: props.height - PAD - ((v - min) / span) * (props.height - PAD * 2) }]));
});

const line = computed(() => points.value.map((point, i) => `${i ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" "));

const fill = computed(() => {
  const first = points.value[0];
  const last = points.value.at(-1);
  if (!first || !last || points.value.length < 2) return "";
  return `${line.value} L${last.x.toFixed(1)},${props.height} L${first.x.toFixed(1)},${props.height} Z`;
});

/** The last point as a zero-length stroke with round caps: a dot that stays round when `fluid` stretches the drawing. */
const lastDot = computed(() => {
  const last = points.value.at(-1);
  return last ? `M${last.x.toFixed(1)},${last.y.toFixed(1)} h0` : "";
});
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
    <path v-if="area && fill" :d="fill" :fill="`url(#${gradientId})`" data-spark-fill />
    <path v-if="line" :d="line" fill="none" :stroke="color" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke" data-spark-line />
    <template v-if="dot && lastDot">
      <path :d="lastDot" stroke="var(--c-surface)" stroke-width="8.5" stroke-linecap="round" vector-effect="non-scaling-stroke" />
      <path :d="lastDot" :stroke="color" stroke-width="5.5" stroke-linecap="round" vector-effect="non-scaling-stroke" data-spark-dot />
    </template>
  </svg>
</template>
