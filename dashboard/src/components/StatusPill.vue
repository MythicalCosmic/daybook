<script setup lang="ts">
/**
 * A status with a colored dot: "Opened 08:57", "NOT OPENED +12 min", "Late", "Verified".
 * `live` makes the dot breathe (something happening now).
 */
import type { Component } from "vue";

export type StatusTone = "neutral" | "primary" | "success" | "warning" | "danger" | "info";

withDefaults(
  defineProps<{
    tone?: StatusTone;
    label?: string;
    variant?: "soft" | "outline" | "plain";
    size?: "sm" | "md";
    live?: boolean;
    icon?: Component;
    dot?: boolean;
  }>(),
  { tone: "neutral", label: undefined, variant: "soft", size: "md", live: false, icon: undefined, dot: true },
);

const surfaces: Record<StatusTone, string> = {
  neutral: "bg-surface-2 text-muted dark:bg-surface-3",
  primary: "bg-accent-soft text-accent-fg",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  info: "bg-info-soft text-info",
};
const outlines: Record<StatusTone, string> = {
  neutral: "border border-line text-muted",
  primary: "border border-line text-accent-fg",
  success: "border border-line text-success",
  warning: "border border-line text-warning",
  danger: "border border-line text-danger",
  info: "border border-line text-info",
};
const plain: Record<StatusTone, string> = {
  neutral: "text-muted",
  primary: "text-primary",
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
  info: "text-info",
};
</script>

<template>
  <span
    :class="[
      'inline-flex max-w-full shrink-0 items-center whitespace-nowrap rounded-full font-medium leading-none',
      size === 'sm' ? 'h-5 gap-1 px-1.5 text-[11px]' : 'h-6 gap-1.5 px-2 text-xs',
      variant === 'plain' && 'px-0',
      variant === 'soft' ? surfaces[tone] : variant === 'outline' ? outlines[tone] : plain[tone],
    ]"
  >
    <component :is="icon" v-if="icon" :size="size === 'sm' ? 12 : 13" aria-hidden="true" />
    <span
      v-else-if="dot"
      :class="['status-dot shrink-0 rounded-full bg-current', size === 'sm' ? 'size-1.5' : 'size-[7px]', live && 'is-live']"
      aria-hidden="true"
    />
    <span class="truncate"><slot>{{ label }}</slot></span>
  </span>
</template>

<style scoped>
.status-dot.is-live {
  animation: breathe 2s var(--ease-standard) infinite;
}
</style>
