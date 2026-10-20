<script setup lang="ts">
/**
 * A row of KPIs in one card with dividers (the top of Overview, Sales, Finance): four across on
 * desktop, two on tablets, one per row on phones. Pass `items` (KpiCard props) or KpiCards with
 * `variant="plain"` in the slot.
 *
 *   <KpiStrip :items="[{ label: t('sales.net'), value: totals.net, previous: prev.net, format: 'money', compact: true }, …]" />
 */
import { computed } from "vue";

import KpiCard from "./KpiCard.vue";

type KpiProps = InstanceType<typeof KpiCard>["$props"];

const props = withDefaults(defineProps<{ items?: Array<KpiProps & { id?: string }>; loading?: boolean; columns?: 2 | 3 | 4 | 5 }>(), {
  items: () => [],
  loading: false,
  columns: undefined,
});

const count = computed(() => props.columns ?? Math.min(5, Math.max(1, props.items.length || 4)));
const grid = computed(
  () =>
    ({
      1: "grid-cols-1",
      2: "grid-cols-1 sm:grid-cols-2",
      3: "grid-cols-1 sm:grid-cols-3",
      4: "grid-cols-1 sm:grid-cols-2 xl:grid-cols-4",
      5: "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5",
    })[count.value] ?? "grid-cols-1",
);
</script>

<template>
  <div class="ui-card overflow-hidden">
    <div :class="['kpi-strip grid', grid]">
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
</style>
