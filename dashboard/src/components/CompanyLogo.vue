<script setup lang="ts">
/** A company's logo, or its initials on a color picked from its name (switcher, portfolio cards). */
import { computed, ref, watch } from "vue";

import { hashIndex, initials } from "@/lib/format";

const props = withDefaults(defineProps<{ name: string; src?: string | null; size?: number; alert?: boolean }>(), {
  src: null,
  size: 28,
  alert: false,
});

const failed = ref(false);
watch(
  () => props.src,
  () => (failed.value = false),
);

const color = computed(() => `var(--c-chart-${[1, 3, 2, 6, 5, 4, 7][hashIndex(props.name, 7)]})`);
const text = computed(() => initials(props.name));
const radius = computed(() => Math.round(props.size * 0.28));
</script>

<template>
  <span class="relative inline-flex shrink-0" :style="{ width: `${size}px`, height: `${size}px` }" aria-hidden="true">
    <img
      v-if="src && !failed"
      :src="src"
      alt=""
      class="size-full object-cover"
      :style="{ borderRadius: `${radius}px` }"
      @error="failed = true"
    />
    <span
      v-else
      class="flex size-full items-center justify-center font-bold tracking-[-0.02em]"
      :style="{
        borderRadius: `${radius}px`,
        background: color,
        color: 'var(--c-surface)',
        fontSize: `${Math.round(size * 0.4)}px`,
        boxShadow: 'inset 0 0 0 1px rgb(0 0 0 / 0.06), inset 0 1px 0 rgb(255 255 255 / 0.18)',
      }"
      >{{ text }}</span
    >
    <span
      v-if="alert"
      class="absolute -right-0.5 -top-0.5 size-2.5 rounded-full bg-danger ring-2 ring-[var(--logo-ring,var(--c-nav))]"
    />
  </span>
</template>
