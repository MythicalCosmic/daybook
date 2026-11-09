<script setup lang="ts">
/** Davomat's mark: a check inside the corners of a face scan, on an indigo tile (core/brand.ts draws the same as the favicon). */
import { useId } from "vue";

withDefaults(defineProps<{ size?: number }>(), { size: 40 });

const id = `dm-${useId()}`;
</script>

<template>
  <svg viewBox="0 0 48 48" :width="size" :height="size" class="shrink-0" aria-hidden="true">
    <defs>
      <linearGradient :id="id" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#6d6af6" />
        <stop offset="1" stop-color="#3f3bd0" />
      </linearGradient>
    </defs>
    <rect width="48" height="48" rx="13" :fill="`url(#${id})`" />
    <path
      d="M13.5 19.5v-3.2a2.8 2.8 0 0 1 2.8-2.8h3.2M28.5 13.5h3.2a2.8 2.8 0 0 1 2.8 2.8v3.2M34.5 28.5v3.2a2.8 2.8 0 0 1-2.8 2.8h-3.2M19.5 34.5h-3.2a2.8 2.8 0 0 1-2.8-2.8v-3.2"
      fill="none"
      stroke="#fff"
      stroke-opacity=".82"
      stroke-width="2.6"
      stroke-linecap="round"
    />
    <path d="M18.6 24.4l3.9 3.9 7.9-8.3" fill="none" stroke="#fff" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" />
  </svg>
</template>
