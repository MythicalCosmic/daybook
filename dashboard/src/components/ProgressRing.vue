<script setup lang="ts">
/**
 * A ring for one share: tasks done today, setup progress, project completion. The middle shows the
 * percentage (`show-value`) or the default slot. `tone="auto"` goes red below 50%, ochre below 80%.
 */
import { computed } from "vue";

import { useFormat } from "@/lib/useFormat";

const props = withDefaults(
  defineProps<{
    value: number;
    max?: number;
    size?: number;
    stroke?: number;
    tone?: "primary" | "success" | "warning" | "danger" | "info" | "auto";
    showValue?: boolean;
    label?: string;
  }>(),
  { max: 100, size: 44, stroke: undefined, tone: "primary", showValue: false, label: undefined },
);

const fmt = useFormat();
const percent = computed(() => (props.max > 0 ? Math.min(100, Math.max(0, (props.value / props.max) * 100)) : 0));
const width = computed(() => props.stroke ?? Math.max(3, Math.round(props.size / 11)));
const radius = computed(() => (props.size - width.value) / 2);
const circumference = computed(() => 2 * Math.PI * radius.value);
const color = computed(() => {
  const tone = props.tone === "auto" ? (percent.value < 50 ? "danger" : percent.value < 80 ? "warning" : "success") : props.tone;
  return `var(--c-${tone})`;
});
</script>

<template>
  <span
    class="relative inline-grid shrink-0 place-items-center"
    :style="{ width: `${size}px`, height: `${size}px` }"
    role="progressbar"
    :aria-valuenow="Math.round(percent)"
    aria-valuemin="0"
    aria-valuemax="100"
    :aria-label="label"
  >
    <svg :width="size" :height="size" :viewBox="`0 0 ${size} ${size}`" class="-rotate-90" aria-hidden="true">
      <circle :cx="size / 2" :cy="size / 2" :r="radius" fill="none" stroke="color-mix(in srgb, var(--c-text) 8%, transparent)" :stroke-width="width" />
      <circle
        :cx="size / 2"
        :cy="size / 2"
        :r="radius"
        fill="none"
        :stroke="color"
        :stroke-width="width"
        stroke-linecap="round"
        :stroke-dasharray="circumference"
        :stroke-dashoffset="circumference * (1 - percent / 100)"
        class="transition-[stroke-dashoffset] duration-700 ease-out"
      />
    </svg>
    <span class="absolute inset-0 grid place-items-center">
      <slot>
        <span v-if="showValue" class="font-semibold tabular-nums text-fg" :style="{ fontSize: `${Math.max(10, Math.round(size * 0.24))}px` }">{{
          fmt.percent(percent)
        }}</span>
      </slot>
    </span>
  </span>
</template>
