<script setup lang="ts">
/** A count or a short label: sidebar badges, tab counts, "New". Numbers above `max` read "99+". */
import { computed } from "vue";

import { formatCount } from "@/lib/format";

export type BadgeTone = "neutral" | "primary" | "success" | "warning" | "danger" | "info";

const props = withDefaults(
  defineProps<{
    tone?: BadgeTone;
    variant?: "soft" | "solid" | "outline";
    size?: "sm" | "md";
    count?: number;
    max?: number;
  }>(),
  { tone: "neutral", variant: "soft", size: "sm", count: undefined, max: 99 },
);

const soft: Record<BadgeTone, string> = {
  neutral: "bg-surface-2 text-muted dark:bg-surface-3",
  primary: "bg-accent-soft text-accent-fg",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  info: "bg-info-soft text-info",
};
const solid: Record<BadgeTone, string> = {
  neutral: "bg-muted text-surface",
  primary: "bg-primary text-on-primary",
  success: "bg-success text-white dark:text-[#14200b]",
  warning: "bg-warning text-white dark:text-[#2a1c05]",
  danger: "bg-danger text-white dark:text-[#2a0c06]",
  info: "bg-info text-white dark:text-[#0c1622]",
};
const outline: Record<BadgeTone, string> = {
  neutral: "border border-line text-muted",
  primary: "border border-[color-mix(in_srgb,var(--c-primary)_35%,transparent)] text-primary",
  success: "border border-[color-mix(in_srgb,var(--c-success)_35%,transparent)] text-success",
  warning: "border border-[color-mix(in_srgb,var(--c-warning)_35%,transparent)] text-warning",
  danger: "border border-[color-mix(in_srgb,var(--c-danger)_35%,transparent)] text-danger",
  info: "border border-[color-mix(in_srgb,var(--c-info)_35%,transparent)] text-info",
};

const tones = computed(() => (props.variant === "solid" ? solid : props.variant === "outline" ? outline : soft)[props.tone]);
const text = computed(() => (props.count === undefined ? null : formatCount(props.count, props.max)));
</script>

<template>
  <span
    :class="[
      'inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-full font-semibold tabular-nums leading-none',
      size === 'sm' ? 'h-[18px] min-w-[18px] px-1.5 text-[11px]' : 'h-[22px] min-w-[22px] px-2 text-xs',
      tones,
    ]"
  >
    <template v-if="text !== null">{{ text }}</template>
    <slot v-else />
  </span>
</template>
