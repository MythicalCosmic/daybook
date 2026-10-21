<script setup lang="ts">
/**
 * One headline number (plan §6.2: "KPI strip (label, tweened value, delta vs compare, sparkline,
 * link to the filtered list)"). The value tweens only when it changes; the delta is computed from
 * `previous` with exact decimals (or given as `delta`); `inverse` when lower is better. With `to`
 * the whole card links to the list behind the number.
 *
 *   <KpiCard :label="t('sales.net')" :value="totals.net" :previous="previous?.net" format="money" :spark="series.map((p) => p.net)" :to="…" />
 */
import { ArrowUpRight } from "@lucide/vue";
import { computed, type Component } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, type RouteLocationRaw } from "vue-router";

import type { Currency, Money } from "@/api/types";
import { changePercent } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";
import { useTween } from "@/lib/useTween";

import { toNumber } from "./chartCard";
import DeltaBadge from "./DeltaBadge.vue";
import ErrorState from "./ErrorState.vue";
import SkeletonBlock from "./SkeletonBlock.vue";
import SparkLine from "./SparkLine.vue";

const props = withDefaults(
  defineProps<{
    label: string;
    value: Money | number | null | undefined;
    format?: "money" | "number" | "percent" | "duration" | ((value: number) => string);
    currency?: Currency;
    /** Compact money ("48,1 mln so‘m"); the full amount is in the tooltip. */
    compact?: boolean;
    previous?: Money | number | null;
    /** A ready change in percent (overrides `previous`). */
    delta?: number | null;
    inverse?: boolean;
    /** "vs last month". */
    deltaLabel?: string;
    /** Percentage points instead of percent (rates). */
    points?: boolean;
    spark?: Array<number | string | null>;
    sparkColor?: string;
    to?: RouteLocationRaw;
    hint?: string;
    icon?: Component;
    loading?: boolean;
    /** The number failed to load: the tile keeps its label and says so, with Try again. */
    error?: unknown;
    retry?: () => unknown;
    /** "plain" for use inside KpiStrip (no own border). */
    variant?: "card" | "plain";
  }>(),
  {
    format: "number",
    currency: undefined,
    compact: false,
    previous: undefined,
    delta: undefined,
    inverse: false,
    deltaLabel: undefined,
    points: false,
    spark: undefined,
    sparkColor: "var(--c-chart-1)",
    to: undefined,
    hint: undefined,
    icon: undefined,
    loading: false,
    error: undefined,
    retry: undefined,
    variant: "card",
  },
);

const { t } = useI18n();
const fmt = useFormat();

const numeric = computed(() => toNumber(props.value));
const tween = useTween(numeric);

function render(value: number | null, exact: boolean): string {
  if (value === null) return "—";
  if (typeof props.format === "function") return props.format(value);
  switch (props.format) {
    case "money":
      // The exact API string at rest; tween frames are rounded display only.
      return fmt.money(exact && props.value !== null && props.value !== undefined ? props.value : Math.round(value), props.currency, { compact: props.compact, decimals: "never" });
    case "percent":
      return fmt.percent(value, 1);
    case "duration":
      return fmt.duration(value);
    default:
      return fmt.number(value, exact ? 1 : 0);
  }
}

const text = computed(() => render(tween.running.value ? tween.value.value : numeric.value, !tween.running.value));
const full = computed(() => (props.format === "money" && props.compact && numeric.value !== null ? fmt.money(props.value) : undefined));

const change = computed(() => {
  if (props.delta !== undefined) return props.delta;
  if (props.previous === undefined || props.previous === null || props.value === null || props.value === undefined) return null;
  if (props.points) {
    const now = toNumber(props.value);
    const before = toNumber(props.previous);
    return now === null || before === null ? null : now - before;
  }
  return changePercent(props.value, props.previous);
});
</script>

<template>
  <component
    :is="to ? RouterLink : 'div'"
    :to="to"
    :class="[
      'group relative flex min-w-0 flex-col p-4 @container',
      variant === 'card' && 'ui-card transition-colors',
      to && 'cursor-pointer',
      to && variant === 'card' && 'hover:border-line-strong',
      to && variant === 'plain' && 'rounded-[10px] hover:bg-surface-2/50',
    ]"
    :aria-busy="loading || undefined"
  >
    <div class="flex items-center gap-2">
      <component :is="icon" v-if="icon" :size="15" class="shrink-0 text-subtle" aria-hidden="true" />
      <span class="min-w-0 flex-1 truncate text-sm font-medium text-muted" :title="label">{{ label }}</span>
      <ArrowUpRight v-if="to" :size="15" class="shrink-0 text-subtle opacity-0 transition-opacity group-hover:opacity-100" :aria-label="t('common.kpi.open')" />
    </div>
    <ErrorState v-if="error" class="mt-2.5" compact bare :error="error" :retry="retry" @click.stop.prevent />
    <template v-else-if="loading">
      <SkeletonBlock class="mt-2.5" width="62%" height="26px" />
      <SkeletonBlock class="mt-3" width="40%" height="14px" />
    </template>
    <template v-else>
      <p class="kpi-value mt-1.5 truncate" :title="full ?? text" aria-live="polite">{{ text }}</p>
      <!-- A narrow tile has no room for the trend beside its delta; in a row made tall by richer
           tiles, it draws the trend across the free middle instead (only when there is room). -->
      <div v-if="spark && spark.length > 1" class="kpi-spare hidden min-h-0 flex-1 @max-[15rem]:flex" aria-hidden="true" data-kpi-spare>
        <SparkLine :data="spark" :color="sparkColor" fluid :height="40" class="kpi-spare-line" />
      </div>
      <div class="mt-auto flex min-h-[32px] items-end justify-between gap-3 pt-2" data-kpi-foot>
        <div class="flex min-w-0 flex-col gap-1">
          <DeltaBadge v-if="change !== null || previous !== undefined || delta !== undefined" :value="change" :inverse="inverse" :points="points" :suffix="deltaLabel" />
          <span v-if="hint" class="line-clamp-2 text-xs text-muted">{{ hint }}</span>
          <slot />
        </div>
        <!-- Two tiles per row on a phone leave no room beside the delta: the trend steps aside. -->
        <SparkLine v-if="spark && spark.length > 1" :data="spark" :color="sparkColor" :width="104" :height="32" class="shrink-0 @max-[15rem]:hidden" />
      </div>
    </template>
  </component>
</template>

<style scoped>
/* Its height comes only from the free space (size containment): none in a short tile. */
.kpi-spare {
  container-type: size;
  flex-direction: column;
  justify-content: flex-end;
}
.kpi-spare-line {
  display: none;
}
@container (min-height: 3.5rem) {
  .kpi-spare-line {
    display: block;
  }
}
</style>
