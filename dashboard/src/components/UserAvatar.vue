<script setup lang="ts">
/**
 * A person's photo, or their initials on a warm tint picked from their name. `status` adds a dot
 * (in, late, off, away) on the corner.
 */
import { computed, ref, watch } from "vue";

import { hashIndex, initials } from "@/lib/format";

export type AvatarStatus = "in" | "late" | "off" | "away";

const props = withDefaults(
  defineProps<{
    name: string;
    src?: string | null;
    size?: number;
    status?: AvatarStatus;
    shape?: "circle" | "rounded";
  }>(),
  { src: null, size: 32, status: undefined, shape: "circle" },
);

const failed = ref(false);
const loaded = ref(false);
watch(
  () => props.src,
  () => {
    failed.value = false;
    loaded.value = false;
  },
);

const tint = computed(() => `var(--c-chart-${hashIndex(props.name, 7) + 1})`);
const text = computed(() => initials(props.name));
const fontSize = computed(() => Math.max(9, Math.round(props.size * 0.38)));
const dotSize = computed(() => Math.max(6, Math.round(props.size * 0.28)));
const statusColor: Record<AvatarStatus, string> = {
  in: "var(--c-success)",
  late: "var(--c-warning)",
  off: "var(--c-subtle)",
  away: "var(--c-info)",
};
</script>

<template>
  <span
    class="relative inline-flex shrink-0 select-none"
    :style="{ width: `${size}px`, height: `${size}px` }"
    role="img"
    :aria-label="name"
  >
    <span
      :class="['flex size-full items-center justify-center overflow-hidden font-semibold', shape === 'circle' ? 'rounded-full' : 'rounded-[28%]']"
      :style="{
        fontSize: `${fontSize}px`,
        background: `color-mix(in srgb, ${tint} 20%, var(--c-surface))`,
        color: `color-mix(in srgb, ${tint} 72%, var(--c-text))`,
        boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${tint} 22%, transparent)`,
      }"
    >
      <img
        v-if="src && !failed"
        :src="src"
        alt=""
        loading="lazy"
        decoding="async"
        :class="['size-full object-cover transition-opacity duration-200', loaded ? 'opacity-100' : 'opacity-0']"
        @load="loaded = true"
        @error="failed = true"
      />
      <span v-if="!src || failed || !loaded" :class="src && !failed ? 'absolute' : ''" aria-hidden="true">{{ text }}</span>
    </span>
    <span
      v-if="status"
      class="absolute -bottom-px -right-px rounded-full ring-2 ring-[var(--avatar-ring,var(--c-surface))]"
      :style="{ width: `${dotSize}px`, height: `${dotSize}px`, background: statusColor[status] }"
      aria-hidden="true"
    />
  </span>
</template>
