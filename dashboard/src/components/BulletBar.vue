<script setup lang="ts">
/**
 * Actual against target with pacing (sales targets, budgets, project budget burn): the bar is the
 * actual, the tick the target, and an optional "expected by today" mark shows whether it is on pace.
 * `inverse` reads lower as better (budgets: over the target is bad).
 *
 *   <BulletBar :label="t('sales.target')" value="48120000" target="60000000" :expected="0.65" value-format="money" />
 */
import { computed } from "vue";

import type { Currency } from "@/api/types";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { toNumber, type ValueFormat } from "./chartCard";
import { valueText } from "./chartOptions";

const props = withDefaults(
  defineProps<{
    value: number | string | null;
    target: number | string | null;
    label?: string;
    /** Share of the period gone (0–1): where the bar should be by now. */
    expected?: number | null;
    inverse?: boolean;
    valueFormat?: ValueFormat;
    currency?: Currency;
    size?: "sm" | "md";
  }>(),
  { label: undefined, expected: null, inverse: false, valueFormat: "number", currency: undefined, size: "md" },
);

const fmt = useFormat();
const company = useCompanyStore();
const ctx = computed(() => ({ lang: fmt.lang.value, currency: props.currency ?? company.currency }));

const actual = computed(() => toNumber(props.value) ?? 0);
const goal = computed(() => toNumber(props.target) ?? 0);
const scale = computed(() => Math.max(goal.value * 1.15, actual.value, 1));
const ratio = computed(() => (goal.value > 0 ? actual.value / goal.value : 0));
const pace = computed(() => (props.expected === null || props.expected <= 0 ? null : ratio.value / props.expected));

const tone = computed(() => {
  if (props.inverse) {
    if (ratio.value > 1) return "danger";
    if (pace.value !== null && pace.value > 1.05) return "warning";
    return "success";
  }
  if (ratio.value >= 1) return "success";
  if (pace.value === null) return "primary";
  return pace.value >= 0.95 ? "success" : pace.value >= 0.8 ? "warning" : "danger";
});
const color = computed(() => `var(--c-${tone.value})`);
const pct = (n: number) => `${Math.min(100, Math.max(0, (n / scale.value) * 100))}%`;
</script>

<template>
  <div class="flex min-w-0 flex-col gap-1.5">
    <div class="flex items-baseline justify-between gap-3 text-sm">
      <span class="min-w-0 truncate font-medium text-fg">{{ label }}</span>
      <span class="shrink-0 tabular-nums">
        <span class="font-semibold text-fg">{{ valueText(actual, valueFormat, ctx) }}</span>
        <span class="text-subtle"> / {{ valueText(goal, valueFormat, ctx) }}</span>
        <span class="ml-1.5 text-xs font-semibold" :style="{ color }">{{ fmt.percent(ratio * 100) }}</span>
      </span>
    </div>
    <div
      role="meter"
      :aria-valuenow="Math.round(ratio * 100)"
      aria-valuemin="0"
      :aria-valuemax="Math.round((scale / Math.max(goal, 1)) * 100)"
      :aria-label="label"
      :class="['relative w-full rounded-full bg-[color-mix(in_srgb,var(--c-text)_8%,transparent)]', size === 'sm' ? 'h-1.5' : 'h-2.5']"
    >
      <div class="absolute inset-y-0 left-0 rounded-full transition-[width] duration-500 ease-out" :style="{ width: pct(actual), background: color }" />
      <span
        v-if="expected !== null && expected > 0 && goal > 0"
        class="absolute -inset-y-1 w-px bg-[repeating-linear-gradient(to_bottom,var(--c-muted)_0_2px,transparent_2px_4px)]"
        :style="{ left: pct(goal * expected) }"
        aria-hidden="true"
      />
      <span v-if="goal > 0" class="absolute -inset-y-1 w-0.5 rounded-full bg-fg" :style="{ left: `calc(${pct(goal)} - 1px)` }" aria-hidden="true" />
    </div>
  </div>
</template>
