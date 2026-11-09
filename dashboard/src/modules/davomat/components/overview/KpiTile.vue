<script setup lang="ts">
/**
 * One number of the Overview strip: a label, the number (it glides when it changes), one line
 * under it, and optionally a ring with a share. Clicking filters the board (or opens a page); the
 * chosen tile stays highlighted.
 */
import type { Component } from "vue";
import { computed } from "vue";
import type { RouteLocationRaw } from "vue-router";

import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { useFormat } from "@/lib/useFormat";
import { useTween } from "@/lib/useTween";

type Tone = "success" | "warning" | "danger" | "info" | "primary" | "neutral";

const props = withDefaults(
  defineProps<{
    label: string;
    value: number | null;
    sub?: string;
    icon: Component;
    tone?: Tone;
    /** 0–1: a ring with this share next to the number. */
    share?: number | null;
    total?: number | null;
    active?: boolean;
    to?: RouteLocationRaw;
    loading?: boolean;
    /** A small pulse by the label (all terminals fine, or one is quiet). */
    pulse?: "success" | "warning" | null;
  }>(),
  { sub: "", tone: "neutral", share: null, total: null, active: false, to: undefined, loading: false, pulse: null },
);
const emit = defineEmits<{ select: [] }>();

const fmt = useFormat();
const tween = useTween(() => props.value);
const shown = computed(() => (tween.value.value === null ? "—" : fmt.number(Math.round(tween.value.value))));

const iconTone: Record<Tone, string> = {
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  info: "bg-info-soft text-info",
  primary: "bg-accent-soft text-accent-fg",
  neutral: "bg-surface-2 text-muted",
};
const ringStroke: Record<Tone, string> = {
  success: "var(--c-success)",
  warning: "var(--c-warning)",
  danger: "var(--c-danger)",
  info: "var(--c-info)",
  primary: "var(--c-primary)",
  neutral: "var(--c-subtle)",
};
const RADIUS = 25;
const LENGTH = 2 * Math.PI * RADIUS;
const dash = computed(() => Math.max(0, Math.min(1, props.share ?? 0)) * LENGTH);
const percent = computed(() => (props.share === null ? null : fmt.percent(Math.round((props.share ?? 0) * 100))));
</script>

<template>
  <component
    :is="to ? 'RouterLink' : 'button'"
    :to="to"
    :type="to ? undefined : 'button'"
    :aria-pressed="to ? undefined : active"
    :class="[
      'tile pressable group relative flex min-w-0 flex-col rounded-[16px] border bg-surface p-3.5 text-left transition-[border-color,box-shadow,transform] duration-200 sm:p-4 md:p-5',
      active ? 'border-primary/50 shadow-[0_0_0_3px_var(--c-accent-soft)]' : 'border-line hover:border-line-strong hover:shadow-xs',
    ]"
    @click="!to && emit('select')"
  >
    <div class="flex items-center gap-2.5">
      <span :class="['grid size-8 shrink-0 place-items-center rounded-[10px]', iconTone[tone]]"><component :is="icon" :size="17" aria-hidden="true" /></span>
      <span class="line-clamp-2 min-w-0 flex-1 text-sm font-medium leading-tight text-muted">{{ label }}</span>
      <span v-if="pulse" class="relative flex size-2.5 shrink-0" aria-hidden="true">
        <span :class="['absolute inline-flex size-full animate-ping rounded-full opacity-60 motion-reduce:hidden', pulse === 'success' ? 'bg-success' : 'bg-warning']" />
        <span :class="['relative inline-flex size-2.5 rounded-full', pulse === 'success' ? 'bg-success' : 'bg-warning']" />
      </span>
    </div>
    <div class="mt-2.5 flex items-center justify-between gap-3 sm:mt-3">
      <SkeletonBlock v-if="loading" width="64px" height="34px" radius="8px" />
      <p v-else class="min-w-0 truncate text-[26px] font-bold leading-none tracking-[-0.03em] tabular-nums text-fg sm:text-[32px]">
        {{ shown }}<span v-if="total !== null" class="ml-1 text-lg font-semibold tracking-normal text-subtle">/{{ fmt.number(total) }}</span>
      </p>
      <div v-if="share !== null && !loading" class="relative -my-2 shrink-0" :title="percent ?? undefined">
        <svg width="52" height="52" viewBox="0 0 60 60" class="-rotate-90" aria-hidden="true">
          <circle cx="30" cy="30" :r="RADIUS" fill="none" stroke="var(--c-surface-3)" stroke-width="6" />
          <circle
            v-if="dash > 0"
            cx="30"
            cy="30"
            :r="RADIUS"
            fill="none"
            :stroke="ringStroke[tone]"
            stroke-width="6"
            stroke-linecap="round"
            :stroke-dasharray="`${dash} ${LENGTH}`"
            class="transition-[stroke-dasharray] duration-500 ease-out motion-reduce:transition-none"
          />
        </svg>
        <span class="absolute inset-0 grid place-items-center text-[11px] font-bold tabular-nums text-fg">{{ percent }}</span>
      </div>
    </div>
    <SkeletonBlock v-if="loading" class="mt-2.5" width="110px" height="12px" />
    <p v-else-if="sub" class="mt-2 line-clamp-2 text-xs leading-snug text-muted sm:mt-2.5 sm:text-sm" :title="sub">{{ sub }}</p>
  </component>
</template>

<style scoped>
.tile:active {
  transform: scale(0.99);
}
@media (prefers-reduced-motion: reduce) {
  .tile:active {
    transform: none;
  }
}
</style>
