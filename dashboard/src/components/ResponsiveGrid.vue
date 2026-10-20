<script setup lang="ts">
/**
 * A grid that fits as many columns as there is room for, each at least `min` wide (cards, branch
 * tiles, KPI tiles), or a fixed column count per breakpoint with `cols`.
 *
 *   <ResponsiveGrid min="280px"> …cards… </ResponsiveGrid>
 *   <ResponsiveGrid :cols="{ base: 1, md: 2, xl: 4 }" gap="12px"> … </ResponsiveGrid>
 */
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    min?: string;
    cols?: { base?: number; sm?: number; md?: number; lg?: number; xl?: number };
    gap?: string;
    as?: string;
  }>(),
  { min: "260px", cols: undefined, gap: "12px", as: "div" },
);

const style = computed(() => {
  const vars: Record<string, string> = { gap: props.gap };
  if (!props.cols) {
    vars.gridTemplateColumns = `repeat(auto-fill, minmax(min(100%, ${props.min}), 1fr))`;
    return vars;
  }
  const cols = props.cols;
  const base = cols.base ?? 1;
  vars["--cols-base"] = String(base);
  vars["--cols-sm"] = String(cols.sm ?? base);
  vars["--cols-md"] = String(cols.md ?? cols.sm ?? base);
  vars["--cols-lg"] = String(cols.lg ?? cols.md ?? cols.sm ?? base);
  vars["--cols-xl"] = String(cols.xl ?? cols.lg ?? cols.md ?? cols.sm ?? base);
  return vars;
});
</script>

<template>
  <component :is="as" :class="['grid min-w-0', cols && 'grid-cols-[repeat(var(--cols),minmax(0,1fr))] responsive-cols']" :style="style">
    <slot />
  </component>
</template>

<style scoped>
.responsive-cols {
  --cols: var(--cols-base);
}
@media (min-width: 40rem) {
  .responsive-cols {
    --cols: var(--cols-sm);
  }
}
@media (min-width: 48rem) {
  .responsive-cols {
    --cols: var(--cols-md);
  }
}
@media (min-width: 64rem) {
  .responsive-cols {
    --cols: var(--cols-lg);
  }
}
@media (min-width: 80rem) {
  .responsive-cols {
    --cols: var(--cols-xl);
  }
}
</style>
