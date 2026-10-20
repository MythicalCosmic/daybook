<script setup lang="ts">
/**
 * A horizontal bar: completion, budget burn, read rate, pacing. One value (`value` of `max`), or
 * stacked `segments` (a payment mix). `target` draws a tick; `tone="auto"` turns warning above 80%
 * and danger above 100% (budgets). `indeterminate` for work of unknown length.
 *
 *   <ProgressBar :value="38" :max="52" show-value />
 *   <ProgressBar :segments="[{ value: 62, color: 'var(--c-chart-1)', label: 'Cash' }, …]" />
 */
import { computed } from "vue";

import { useFormat } from "@/lib/useFormat";

export interface ProgressSegment {
  value: number;
  color?: string;
  label?: string;
}

const props = withDefaults(
  defineProps<{
    value?: number;
    max?: number;
    segments?: ProgressSegment[];
    tone?: "primary" | "success" | "warning" | "danger" | "info" | "neutral" | "auto";
    size?: "xs" | "sm" | "md" | "lg";
    target?: number;
    label?: string;
    showValue?: boolean;
    indeterminate?: boolean;
  }>(),
  { value: 0, max: 100, segments: undefined, tone: "primary", size: "sm", target: undefined, label: undefined, showValue: false, indeterminate: false },
);

const fmt = useFormat();
const percent = computed(() => (props.max > 0 ? (props.value / props.max) * 100 : 0));
const width = computed(() => Math.min(100, Math.max(0, percent.value)));

const color = computed(() => {
  const tone =
    props.tone === "auto" ? (percent.value > 100 ? "danger" : percent.value >= 80 ? "warning" : "success") : props.tone;
  return { primary: "var(--c-primary)", success: "var(--c-success)", warning: "var(--c-warning)", danger: "var(--c-danger)", info: "var(--c-info)", neutral: "var(--c-muted)" }[tone];
});

const stacked = computed(() => {
  if (!props.segments?.length) return [];
  const total = props.segments.reduce((sum, s) => sum + Math.max(0, s.value), 0) || 1;
  return props.segments.map((segment, index) => ({
    ...segment,
    width: (Math.max(0, segment.value) / total) * 100,
    color: segment.color ?? `var(--c-chart-${(index % 8) + 1})`,
  }));
});

const heights = { xs: "h-1", sm: "h-1.5", md: "h-2", lg: "h-2.5" } as const;
</script>

<template>
  <div class="flex min-w-0 flex-col gap-1.5">
    <div v-if="label || showValue" class="flex items-baseline justify-between gap-3 text-sm">
      <span class="min-w-0 truncate font-medium text-fg">{{ label }}</span>
      <span v-if="showValue" class="shrink-0 tabular-nums text-muted">
        <template v-if="max === 100">{{ fmt.percent(percent) }}</template>
        <template v-else>{{ fmt.number(value) }}<span class="text-subtle"> / {{ fmt.number(max) }}</span></template>
      </span>
    </div>
    <div
      role="progressbar"
      :aria-valuenow="indeterminate || stacked.length ? undefined : Math.round(percent)"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-label="label"
      :class="['relative w-full overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--c-text)_8%,transparent)]', heights[size]]"
    >
      <div v-if="indeterminate" class="progress-indeterminate absolute inset-y-0 w-1/3 rounded-full" :style="{ background: color }" />
      <div v-else-if="stacked.length" class="flex h-full w-full gap-px">
        <div
          v-for="(segment, index) in stacked"
          :key="index"
          class="h-full transition-[width] duration-500 ease-out first:rounded-l-full last:rounded-r-full"
          :style="{ width: `${segment.width}%`, background: segment.color }"
          :title="segment.label ? `${segment.label}: ${fmt.percent(segment.width)}` : undefined"
        />
      </div>
      <div v-else class="h-full rounded-full transition-[width] duration-500 ease-out" :style="{ width: `${width}%`, background: color }" />
      <span
        v-if="target !== undefined"
        class="absolute inset-y-[-2px] w-0.5 rounded-full bg-fg/70"
        :style="{ left: `calc(${Math.min(100, Math.max(0, (target / max) * 100))}% - 1px)` }"
        aria-hidden="true"
      />
    </div>
  </div>
</template>

<style scoped>
.progress-indeterminate {
  animation: progress-slide 1.2s var(--ease-standard) infinite;
}
@keyframes progress-slide {
  from {
    left: -33%;
  }
  to {
    left: 100%;
  }
}
</style>
