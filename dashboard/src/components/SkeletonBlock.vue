<script setup lang="ts">
/**
 * A loading placeholder shaped like the content it stands for. Show it through useDelayedPending
 * so it only appears after 150 ms. `lines` draws a paragraph whose last line is shorter.
 */
withDefaults(
  defineProps<{
    width?: string;
    height?: string;
    radius?: string;
    lines?: number;
    circle?: boolean;
  }>(),
  { width: "100%", height: "14px", radius: "6px", lines: 0, circle: false },
);
</script>

<template>
  <span v-if="lines > 0" class="flex w-full flex-col gap-2" aria-hidden="true">
    <span
      v-for="line in lines"
      :key="line"
      class="skeleton block"
      :style="{ width: line === lines && lines > 1 ? '62%' : width, height, borderRadius: radius }"
    />
  </span>
  <span
    v-else
    class="skeleton block shrink-0"
    aria-hidden="true"
    :style="{ width: circle ? height : width, height, borderRadius: circle ? '999px' : radius }"
  />
</template>

<style scoped>
.skeleton {
  background-color: var(--c-skeleton);
  background-image: linear-gradient(90deg, transparent 0%, var(--c-skeleton-shine) 50%, transparent 100%);
  background-size: 200% 100%;
  background-repeat: no-repeat;
  animation: shimmer 1.6s var(--ease-standard) infinite;
}
</style>
