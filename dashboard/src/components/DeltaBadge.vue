<script setup lang="ts">
/**
 * A change in percent with direction: "▲ +8,2%" in green, "▼ −12%" in red. `inverse` flips the
 * colors where lower is better (expenses, late tasks, cash differences). Null shows a neutral dash.
 *
 *   <DeltaBadge :value="changePercent(totals.net, previous.net)" />
 *   <DeltaBadge :value="12.4" inverse variant="text" suffix="vs last month" />
 */
import { ArrowDownRight, ArrowUpRight, Minus } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useFormat } from "@/lib/useFormat";

const props = withDefaults(
  defineProps<{
    value: number | null | undefined;
    inverse?: boolean;
    variant?: "badge" | "text";
    size?: "sm" | "md";
    decimals?: number;
    suffix?: string;
    /** Percentage points instead of percent ("+3,1 pp" for on-time rates). */
    points?: boolean;
  }>(),
  { inverse: false, variant: "badge", size: "sm", decimals: 1, suffix: undefined, points: false },
);

const { t } = useI18n();
const fmt = useFormat();

const direction = computed(() => {
  const v = props.value;
  if (v === null || v === undefined || !Number.isFinite(v) || Math.abs(v) < 0.05) return 0;
  return v > 0 ? 1 : -1;
});
const good = computed(() => (direction.value === 0 ? null : (direction.value > 0) !== props.inverse));
const text = computed(() => {
  if (props.value === null || props.value === undefined) return "—";
  if (!props.points) return fmt.delta(props.value, props.decimals);
  const magnitude = fmt.number(Math.abs(props.value), props.decimals);
  return `${props.value > 0 ? "+" : props.value < 0 ? "−" : ""}${magnitude} ${t("common.delta.points")}`;
});
const icon = computed(() => (direction.value > 0 ? ArrowUpRight : direction.value < 0 ? ArrowDownRight : Minus));
const tone = computed(() => (good.value === null ? "neutral" : good.value ? "good" : "bad"));
const label = computed(() => t(`common.delta.${direction.value > 0 ? "up" : direction.value < 0 ? "down" : "flat"}`, { value: text.value }));
</script>

<template>
  <span class="inline-flex items-center gap-1.5 whitespace-nowrap" :aria-label="suffix ? `${label} ${suffix}` : label">
    <span
      :class="[
        'inline-flex items-center gap-0.5 font-semibold tabular-nums leading-none',
        variant === 'badge' && (size === 'sm' ? 'h-5 rounded-full px-1.5 text-[11px]' : 'h-6 rounded-full px-2 text-xs'),
        variant === 'text' && (size === 'sm' ? 'text-xs' : 'text-sm'),
        tone === 'good' && (variant === 'badge' ? 'bg-success-soft text-success' : 'text-success'),
        tone === 'bad' && (variant === 'badge' ? 'bg-danger-soft text-danger' : 'text-danger'),
        tone === 'neutral' && (variant === 'badge' ? 'bg-surface-2 text-muted dark:bg-surface-3' : 'text-muted'),
      ]"
      aria-hidden="true"
    >
      <component :is="icon" :size="size === 'sm' ? 12 : 14" :stroke-width="2.25" class="-ml-0.5" />
      {{ text }}
    </span>
    <span v-if="suffix" class="text-xs text-muted" aria-hidden="true">{{ suffix }}</span>
  </span>
</template>
