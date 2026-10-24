<script setup lang="ts">
/**
 * A row of KPIs in one card with dividers (the top of Overview, Sales, Finance): four across on
 * desktop, two on tablets, one per row on phones. Pass `items` (KpiCard props) or KpiCards with
 * `variant="plain"` in the slot.
 *
 * `phone` changes the phone layout (below 640 px) for pages whose list should start on the first
 * screen: "grid" keeps two numbers per row (three when there are three) with an odd last one
 * spanning the row; "compact" does the same with tighter cells and without each number's footer
 * (hint, change, sparkline).
 *
 *   <KpiStrip :items="[{ label: t('sales.net'), value: totals.net, previous: prev.net, format: 'money', compact: true }, …]" />
 *   <KpiStrip :items="kpis" :columns="4" phone="compact" />
 */
import { computed } from "vue";

import KpiCard from "./KpiCard.vue";

type KpiProps = InstanceType<typeof KpiCard>["$props"];

const props = withDefaults(
  defineProps<{ items?: Array<KpiProps & { id?: string }>; loading?: boolean; columns?: 2 | 3 | 4 | 5; phone?: "stack" | "grid" | "compact" | "line" }>(),
  {
    items: () => [],
    loading: false,
    columns: undefined,
    phone: "stack",
  },
);

const count = computed(() => props.columns ?? Math.min(5, Math.max(1, props.items.length || 4)));
/**
 * Columns below 640 px: one stack by default, else two (three for a strip of three); "line" keeps
 * up to four numbers on one short row, for lists that must start on the first screen.
 */
const phoneColumns = computed(() => (props.phone === "stack" ? 1 : props.phone === "line" ? Math.min(4, count.value) : count.value === 3 ? 3 : 2));
const grid = computed(() => {
  const base = ({ 1: "grid-cols-1", 2: "grid-cols-2", 3: "grid-cols-3", 4: "grid-cols-4" } as Record<number, string>)[phoneColumns.value];
  const wider =
    ({
      1: "",
      2: "sm:grid-cols-2",
      3: "sm:grid-cols-3",
      4: "sm:grid-cols-2 xl:grid-cols-4",
      // Six tracks between 1024 and 1279 px: three numbers over two, each row full (styles below).
      5: "sm:grid-cols-2 lg:grid-cols-6 xl:grid-cols-5",
    } as Record<number, string>)[count.value] ?? "";
  return `${base} ${wider}`.trim();
});
</script>

<template>
  <div class="ui-card overflow-hidden">
    <div :class="['kpi-strip grid', grid]" :data-phone="phone" :data-phone-columns="phoneColumns" :data-count="count">
      <slot>
        <KpiCard v-for="(item, index) in items" :key="item.id ?? index" v-bind="item" :loading="loading || item.loading" variant="plain" />
      </slot>
    </div>
  </div>
</template>

<style scoped>
/* Hairlines between cells in every layout: each cell draws its top and left edge, the outer ones are hidden by the card. */
.kpi-strip {
  margin: -1px 0 0 -1px;
}
.kpi-strip > :deep(*) {
  border-top: 1px solid var(--c-border);
  border-left: 1px solid var(--c-border);
  border-radius: 0;
}
/* Five numbers never leave an empty cell: on tablets the odd last one takes its row (2 + 2 + 1);
   from 1024 to 1279 px the six tracks hold three numbers over two (2 tracks each, then 3 each). */
@media (40rem <= width < 64rem) {
  .kpi-strip[data-count="5"] > :deep(*:last-child:nth-child(odd)) {
    grid-column: 1 / -1;
  }
}
@media (64rem <= width < 80rem) {
  .kpi-strip[data-count="5"] > :deep(*) {
    grid-column: span 2;
  }
  .kpi-strip[data-count="5"] > :deep(*:nth-child(n + 4)) {
    grid-column: span 3;
  }
}
/* Phone layouts (`phone`): below Tailwind's sm, where the grid classes switch. */
@media (width < 40rem) {
  .kpi-strip[data-phone-columns="2"] > :deep(*:last-child:nth-child(odd)) {
    grid-column: 1 / -1;
  }
  .kpi-strip[data-phone="compact"] > :deep(*) {
    padding: 0.75rem 1rem;
  }
  .kpi-strip[data-phone="compact"][data-phone-columns="3"] > :deep(*) {
    padding: 0.75rem;
  }
  .kpi-strip[data-phone="compact"] :deep([data-kpi-foot]) {
    display: none;
  }
  /* One short row: a small two-line label over the number, nothing else. */
  .kpi-strip[data-phone="line"] > :deep(*) {
    padding: 0.5rem 0.625rem 0.625rem;
  }
  .kpi-strip[data-phone="line"] :deep(.kpi-label) {
    min-height: 1.75rem;
    font-size: 0.6875rem;
    line-height: 0.875rem;
  }
  .kpi-strip[data-phone="line"] :deep(.kpi-label ~ svg) {
    display: none;
  }
  .kpi-strip[data-phone="line"] :deep(.kpi-value) {
    margin-top: 0.25rem;
    font-size: 1.125rem;
    line-height: 1.5rem;
  }
  .kpi-strip[data-phone="line"] :deep([data-kpi-foot]),
  .kpi-strip[data-phone="line"] :deep([data-kpi-spare]) {
    display: none;
  }
}
</style>
