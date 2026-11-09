<script setup lang="ts">
/** A badge's medal: its icon on bronze, silver or gold; still to earn, a quiet outline. */
import { computed } from "vue";

import { badgeIcon } from "../lib";
import type { Tier } from "../types";

const props = withDefaults(defineProps<{ icon: string; tier: Tier; size?: number; locked?: boolean }>(), { size: 44, locked: false });
const glyph = computed(() => badgeIcon(props.icon));
</script>

<template>
  <span class="rcg-medal" :class="[`rcg-medal--${tier}`, { 'rcg-medal--locked': locked }]" :style="{ width: `${size}px`, height: `${size}px` }" aria-hidden="true">
    <component :is="glyph" :size="Math.round(size * 0.46)" :stroke-width="2.2" />
  </span>
</template>

<style scoped>
.rcg-medal {
  display: inline-grid;
  place-items: center;
  flex: none;
  border-radius: 9999px;
  color: #3a2a1a;
  box-shadow:
    inset 0 -2px 0 rgb(0 0 0 / 0.14),
    0 1px 3px rgb(0 0 0 / 0.12);
}
.rcg-medal--bronze {
  background: radial-gradient(circle at 32% 28%, #e8b07a, #b7733d);
}
.rcg-medal--silver {
  background: radial-gradient(circle at 32% 28%, #eef1f4, #a5adb6);
}
.rcg-medal--gold {
  background: radial-gradient(circle at 32% 28%, #ffe08a, #d39b22);
}
.rcg-medal--locked {
  background: var(--c-surface-2);
  color: var(--c-subtle);
  box-shadow: inset 0 0 0 1.5px var(--c-border-strong);
}
</style>
