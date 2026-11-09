<script setup lang="ts">
/**
 * A scan's snapshot: round, with a soft ring in the colour of what the scan did. Without a photo
 * (or while one fails to load) the initials stand in, on the same ring, so rows never jump.
 */
import { ref, watch } from "vue";

import { initials } from "../lib";

const props = withDefaults(defineProps<{ src: string | null; name: string; size?: number; ring?: string; alt?: string }>(), {
  size: 40,
  ring: "var(--c-line)",
  alt: "",
});

const failed = ref(false);
watch(
  () => props.src,
  () => (failed.value = false),
);
</script>

<template>
  <span
    class="faceid-snap relative inline-grid shrink-0 place-items-center overflow-hidden rounded-full bg-surface-2 text-muted"
    :style="{ width: `${size}px`, height: `${size}px`, '--ring': ring }"
  >
    <img v-if="src && !failed" :src="src" :alt="alt || name" class="size-full object-cover" loading="lazy" decoding="async" @error="failed = true" />
    <span v-else class="select-none font-semibold" :style="{ fontSize: `${Math.max(11, Math.round(size * 0.36))}px` }" aria-hidden="true">{{ initials(name) }}</span>
  </span>
</template>

<style scoped>
.faceid-snap {
  box-shadow:
    0 0 0 2px var(--c-surface),
    0 0 0 4px color-mix(in srgb, var(--ring) 70%, transparent);
}
</style>
