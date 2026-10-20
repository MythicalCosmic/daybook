<script setup lang="ts">
/** A project's colour square with its icon: the project's "avatar" everywhere it is listed. */
import { computed } from "vue";

import { colorVar, projectIcon, tint } from "../lib";

const props = withDefaults(defineProps<{ color?: string | null; icon?: string | null; size?: number }>(), { color: null, icon: null, size: 36 });

const Icon = computed(() => projectIcon(props.icon));
</script>

<template>
  <span
    class="grid shrink-0 place-items-center"
    :style="{
      width: `${size}px`,
      height: `${size}px`,
      borderRadius: `${Math.round(size * 0.28)}px`,
      background: tint(color, 20),
      color: colorVar(color),
      boxShadow: `inset 0 0 0 1px ${tint(color, 34)}`,
    }"
    aria-hidden="true"
  >
    <component :is="Icon" :size="Math.round(size * 0.5)" :stroke-width="1.9" />
  </span>
</template>
